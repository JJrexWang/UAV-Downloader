"""On-demand transcoding of library videos to HLS for browser playback.

Files the browser cannot decode natively (see probe.py) are transcoded
by ffmpeg into an event-type HLS stream under ``<state>/transcode/<id>``
and served by server.py.  Each session is a single ffmpeg process with
input seeking, so a seek beyond the buffered range is served by simply
starting a new session at the requested offset.  Hardware encoding via
VAAPI is attempted when a render node exists; if that ffmpeg dies
immediately without producing a segment, VAAPI is marked broken for the
process lifetime and the session respawns with libx264.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time

from . import library, metadata

MAX_SESSIONS = 2
_IDLE_LIMIT = 90          # Seconds without a playlist/segment GET.
_FAILED_GRACE = 15        # Seconds before a dead, unfinished session is reaped.
_REAPER_INTERVAL = 5
_VAAPI_DEVICE = '/dev/dri/renderD128'
_ID_RE = re.compile(r'^[a-f0-9]{16}$')

_lock = threading.Lock()
_sessions = {}
_vaapi_broken = False
_reaper_started = False


def transcode_root():
    path = Path(metadata.state_dir()) / 'transcode'
    path.mkdir(parents=True, exist_ok=True)
    return path


def valid_id(session_id):
    return isinstance(session_id, str) and bool(_ID_RE.match(session_id))


def _video_filter(encoder):
    if encoder == 'vaapi':
        return "scale_vaapi=w=-2:h='min(1080,ih)'"
    return "scale=w=-2:h='min(1080,ih)'"


def _build_command(session, target):
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin']
    if session['offset'] > 0:
        cmd += ['-ss', f"{session['offset']:.3f}"]
    if session['encoder'] == 'vaapi':
        cmd += ['-hwaccel', 'vaapi', '-hwaccel_device', _VAAPI_DEVICE,
                '-hwaccel_output_format', 'vaapi']
    cmd += ['-i', str(target),
            '-map', '0:v:0', '-map', '0:a:0?',
            '-vf', _video_filter(session['encoder'])]
    if session['encoder'] == 'vaapi':
        cmd += ['-c:v', 'h264_vaapi', '-b:v', '8M']
    else:
        cmd += ['-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23']
    cmd += ['-c:a', 'aac', '-b:a', '192k', '-ac', '2',
            '-f', 'hls', '-hls_time', '4', '-hls_playlist_type', 'event',
            '-hls_flags', 'independent_segments', '-start_number', '0',
            '-hls_segment_filename', str(session['dir'] / 'seg%05d.ts'),
            str(session['dir'] / 'index.m3u8')]
    return cmd


def _spawn(session, target):
    log = open(session['dir'] / 'ffmpeg.log', 'ab')
    try:
        proc = subprocess.Popen(
            _build_command(session, target),
            stdout=subprocess.DEVNULL, stderr=log,
            start_new_session=True)
    finally:
        log.close()
    session['proc'] = proc
    return proc


def _segments_exist(session):
    try:
        return any(session['dir'].glob('seg*.ts'))
    except OSError:
        return False


def _playlist_complete(session):
    try:
        return '#EXT-X-ENDLIST' in (
            session['dir'] / 'index.m3u8').read_text(encoding='utf-8')
    except OSError:
        return False


def _kill(session):
    proc = session.get('proc')
    if proc is None:
        return
    if proc.poll() is None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (OSError, ProcessLookupError):
            try:
                proc.kill()
            except OSError:
                pass
    try:
        proc.wait(timeout=5)
    except Exception:
        pass


def _remove(session):
    _kill(session)
    shutil.rmtree(session['dir'], ignore_errors=True)


def _ensure_reaper():
    global _reaper_started
    if _reaper_started:
        return
    _reaper_started = True
    threading.Thread(target=_reaper_loop, daemon=True,
                     name='uav-transcode-reaper').start()


def _reaper_loop():
    while True:
        time.sleep(_REAPER_INTERVAL)
        now = time.monotonic()
        with _lock:
            doomed = []
            for session in list(_sessions.values()):
                idle = now - session['last_access']
                proc = session.get('proc')
                ended = proc is not None and proc.poll() is not None
                if idle > _IDLE_LIMIT:
                    doomed.append(session)
                elif (ended and not _playlist_complete(session)
                        and idle > _FAILED_GRACE):
                    doomed.append(session)
            for session in doomed:
                _sessions.pop(session['id'], None)
        for session in doomed:
            _remove(session)


def purge_all():
    """Kill every session and clear the transcode dir (server startup)."""
    with _lock:
        sessions = list(_sessions.values())
        _sessions.clear()
    for session in sessions:
        _remove(session)
    root = transcode_root()
    for child in root.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                pass


def start(rel, offset=0.0):
    """Start a transcode session for *rel* at *offset* seconds.

    Returns the session dict.  Raises ValueError('not_found') when *rel*
    does not resolve, ValueError('busy') when MAX_SESSIONS are active.
    """
    global _vaapi_broken
    target = library.resolve_stream(rel)
    if not target:
        raise ValueError('not_found')
    try:
        offset = max(0.0, float(offset))
    except (TypeError, ValueError):
        offset = 0.0
    _ensure_reaper()
    session_id = secrets.token_hex(8)
    session_dir = transcode_root() / session_id
    with _lock:
        if len(_sessions) >= MAX_SESSIONS:
            raise ValueError('busy')
        session_dir.mkdir(parents=True, exist_ok=True)
        encoder = ('vaapi' if Path(_VAAPI_DEVICE).exists()
                   and not _vaapi_broken else 'libx264')
        session = {'id': session_id, 'dir': session_dir, 'proc': None,
                   'rel': rel, 'offset': offset, 'encoder': encoder,
                   'last_access': time.monotonic()}
        _sessions[session_id] = session
    try:
        proc = _spawn(session, target)
        if encoder == 'vaapi':
            # Watchdog: a VAAPI ffmpeg that exits non-zero within ~2s
            # without producing a segment means the hardware path is
            # unusable; mark it broken and respawn in software.
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline:
                if proc.poll() is not None:
                    break
                time.sleep(0.1)
            if (proc.poll() not in (None, 0)
                    and not _segments_exist(session)):
                _vaapi_broken = True
                session['encoder'] = 'libx264'
                for child in session_dir.iterdir():
                    try:
                        child.unlink()
                    except OSError:
                        pass
                _spawn(session, target)
    except Exception:
        with _lock:
            _sessions.pop(session_id, None)
        _remove(session)
        raise
    return session


def get(session_id):
    if not valid_id(session_id):
        return None
    with _lock:
        return _sessions.get(session_id)


def touch(session_id):
    with _lock:
        session = _sessions.get(session_id)
        if session is not None:
            session['last_access'] = time.monotonic()


def stop(session_id):
    """Kill and remove a session; unknown ids are ignored."""
    if not valid_id(session_id):
        return
    with _lock:
        session = _sessions.pop(session_id, None)
    if session is not None:
        _remove(session)

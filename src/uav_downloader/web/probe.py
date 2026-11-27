"""Container/codec probing for the library player, via ffprobe.

The browser <video> element only plays a narrow set of containers and
codecs, so before playback the UI asks for a verdict: files the browser
can handle are streamed directly, everything else is transcoded on
demand (see transcode.py).  Results are cached as JSON files under
``<state>/probe`` keyed by a fingerprint of rel|size|mtime, like the
thumbnail cache.  Probing must never break playback: any failure
degrades to a transcode verdict.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

from . import library, metadata

_TIMEOUT = 15

DIRECT_EXTS = {'.mp4', '.mov', '.webm'}
DIRECT_VIDEO = {'h264', 'av1', 'vp9'}
DIRECT_AUDIO = {'aac', 'mp3', 'opus', 'vorbis', 'flac'}


def probe_dir():
    path = Path(metadata.state_dir()) / 'probe'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _ffprobe_json(target):
    """Raw ffprobe output for *target* as a dict, or None on any failure."""
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_format', '-show_streams',
             '-of', 'json', str(target)],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            timeout=_TIMEOUT)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout.decode('utf-8', 'replace'))
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _verdict(rel, target, data):
    """Build the probe result dict from parsed ffprobe *data* (or None)."""
    ext = Path(target).suffix.lower()
    result = {'container': '', 'duration': 0.0, 'video': None, 'audio': [],
              'direct': False, 'mode': 'transcode', 'reason': 'probe_failed'}
    if not data:
        return result
    fmt = data.get('format') or {}
    result['container'] = str(fmt.get('format_name') or '')
    try:
        result['duration'] = float(fmt.get('duration') or 0)
    except (TypeError, ValueError):
        result['duration'] = 0.0
    video = None
    audio = []
    for stream in data.get('streams') or []:
        if not isinstance(stream, dict):
            continue
        codec = str(stream.get('codec_name') or '').lower()
        if stream.get('codec_type') == 'video':
            if (stream.get('disposition') or {}).get('attached_pic') == 1:
                continue  # Embedded cover art, not the picture track.
            if video is None:
                video = {'codec': codec,
                         'width': int(stream.get('width') or 0),
                         'height': int(stream.get('height') or 0)}
        elif stream.get('codec_type') == 'audio':
            audio.append(codec)
    result['video'] = video
    result['audio'] = audio
    if ext not in DIRECT_EXTS:
        result['reason'] = f'container:{ext.lstrip(".") or "unknown"}'
        return result
    if video is None:
        result['reason'] = 'video:missing'
        return result
    if video['codec'] not in DIRECT_VIDEO:
        result['reason'] = f'video:{video["codec"] or "unknown"}'
        return result
    for codec in audio:
        if codec not in DIRECT_AUDIO:
            result['reason'] = f'audio:{codec or "unknown"}'
            return result
    result['direct'] = True
    result['mode'] = 'direct'
    result['reason'] = ''
    return result


def probe(rel):
    """Probe verdict for the library item at *rel*; never raises.

    Unresolvable paths and ffprobe failures both yield a transcode
    verdict (reason 'probe_failed'), so the player can always fall back
    to the transcoding path.
    """
    fallback = {'container': '', 'duration': 0.0, 'video': None, 'audio': [],
                'direct': False, 'mode': 'transcode', 'reason': 'probe_failed'}
    try:
        target = library.resolve_stream(rel)
        if not target:
            return fallback
        source = Path(target)
        try:
            stat = source.stat()
        except OSError:
            return fallback
        key = hashlib.sha1(
            f'{rel}|{stat.st_size}|{int(stat.st_mtime)}'.encode('utf-8')
        ).hexdigest()
        cached = probe_dir() / (key + '.json')
        if cached.is_file():
            try:
                data = json.loads(cached.read_text(encoding='utf-8'))
                if isinstance(data, dict) and 'direct' in data:
                    return data
            except (OSError, ValueError):
                pass
        result = _verdict(rel, target, _ffprobe_json(target))
        try:
            tmp = cached.with_name(
                f'{cached.stem}.tmp-{os.getpid()}.json')
            tmp.write_text(json.dumps(result, ensure_ascii=True),
                           encoding='utf-8')
            os.replace(tmp, cached)
        except OSError:
            pass
        return result
    except Exception:
        return fallback

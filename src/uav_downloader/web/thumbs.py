"""On-demand video preview thumbnails, generated lazily by ffmpeg.

A thumbnail is produced only when the UI explicitly requests one through
/api/thumb — never in the background.  Results are cached as plain JPEG
files under ``<state>/thumbs`` so repeat views are static serves.  A
module-level semaphore bounds concurrent ffmpeg runs, keeping a grid of
first-time previews from swamping the host.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path
import subprocess
import threading

from . import library, metadata

_SEMAPHORE = threading.Semaphore(2)
_SEEKS = ('30', '5', '1')       # Preferred frame offsets, in seconds.
_TIMEOUT = 20                   # Per-attempt ffmpeg timeout, in seconds.
_ACQUIRE_TIMEOUT = 30           # Max wait for a generation slot, in seconds.


class ThumbBusy(Exception):
    """No generation slot freed up in time; the caller should retry later."""


def thumbs_dir():
    path = Path(metadata.state_dir()) / 'thumbs'
    path.mkdir(parents=True, exist_ok=True)
    return path


def _generate(source, cached):
    """Run ffmpeg for *source* into *cached*; return the path or None."""
    tmp = cached.with_name(
        f'{cached.stem}.tmp-{os.getpid()}-{threading.get_ident()}.jpg')
    try:
        for seek in _SEEKS:
            try:
                result = subprocess.run(
                    ['ffmpeg', '-ss', seek, '-i', str(source),
                     '-frames:v', '1', '-vf', 'scale=480:-2',
                     '-q:v', '4', '-y', str(tmp)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=_TIMEOUT)
            except (OSError, subprocess.TimeoutExpired):
                continue
            if result.returncode == 0 and tmp.is_file() and tmp.stat().st_size > 0:
                os.replace(tmp, cached)
                return cached
        return None
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def get_thumb(rel):
    """Cached thumbnail path for the video at *rel*, generating on a miss.

    Returns None when *rel* does not resolve to a video file or generation
    fails; raises ThumbBusy when no generation slot frees up in time.
    """
    target = library.resolve_stream(rel)
    if not target:
        return None
    source = Path(target)
    if source.suffix.lower() not in library.VIDEO_EXTS:
        return None
    try:
        stat = source.stat()
    except OSError:
        return None
    key = hashlib.sha1(
        f'{rel}|{stat.st_size}|{int(stat.st_mtime)}'.encode('utf-8')).hexdigest()
    cached = thumbs_dir() / (key + '.jpg')
    if cached.is_file() and cached.stat().st_size > 0:
        return cached
    if not _SEMAPHORE.acquire(timeout=_ACQUIRE_TIMEOUT):
        raise ThumbBusy(rel)
    try:
        # Another request may have generated it while we waited for a slot.
        if cached.is_file() and cached.stat().st_size > 0:
            return cached
        return _generate(source, cached)
    finally:
        _SEMAPHORE.release()

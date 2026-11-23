"""Read-only scanning of the local video library for the web UI.

The library root (LIBRARY_DIR) holds the organised collection; the downloads
root (DOWNLOAD_DIR) holds fresh downloads.  Scans are cached briefly because
the library tree can be large.  Nothing here ever writes to either tree.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import threading
import time

VIDEO_EXTS = {'.mp4', '.mkv', '.avi', '.mov', '.wmv', '.ts', '.m2ts'}
IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.webp')
CODE_RE = re.compile(r'[A-Za-z]{2,6}-?\d{2,5}')
_CODE_PARTS = re.compile(r'([A-Za-z]{2,6})-?(\d{2,5})')
_FOLDER_TITLE_RE = re.compile(r'^\[[^\]]+\]\s*(.*)$')
TOP_JAV = '01-日本JAV'
BUCKETS = {'共演·合集', 'FC2', '素人'}
CACHE_SECONDS = 60

_lock = threading.Lock()
_cache = {'at': 0.0, 'works': None, 'dl_codes': None}


def library_root():
    return os.environ.get('LIBRARY_DIR', '/library')


def downloads_root():
    return os.environ.get('DOWNLOAD_DIR', '/downloads')


def _normalize_code(raw):
    match = _CODE_PARTS.fullmatch(raw or '')
    if not match:
        return (raw or '').upper()
    return f'{match.group(1).upper()}-{match.group(2)}'


def extract_code(text):
    """First video code in *text*, normalised to ``UPPER-NNN`` form."""
    if not text:
        return ''
    match = CODE_RE.search(text)
    return _normalize_code(match.group(0)) if match else ''


def _parse_work(root, path):
    rel = path.relative_to(root).as_posix()
    parts = rel.split('/')
    parent = parts[-2] if len(parts) >= 2 else ''
    code = extract_code(parent) or extract_code(path.stem)
    title = ''
    folder_match = _FOLDER_TITLE_RE.match(parent)
    if folder_match and code:
        title = folder_match.group(1).strip()
    if not title:
        title = CODE_RE.sub('', path.stem, count=1).strip(' -_') if code else path.stem
    actress = ''
    folder = parts[0] if len(parts) >= 2 else ''
    if folder == TOP_JAV and len(parts) >= 3:
        segment = parts[1]
        if segment in BUCKETS:
            folder = segment
        else:
            actress = segment
    cover = ''
    for ext in IMAGE_EXTS:
        candidate = path.with_suffix(ext)
        if candidate.is_file():
            cover = candidate.relative_to(root).as_posix()
            break
    try:
        size = path.stat().st_size
    except OSError:
        size = 0
    return {'rel': rel, 'size': size, 'code': code, 'title': title,
            'actress': actress, 'folder': folder, 'cover': cover}


def _scan():
    root = Path(library_root())
    works = []
    if root.is_dir():
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for name in sorted(filenames):
                if Path(name).suffix.lower() not in VIDEO_EXTS:
                    continue
                try:
                    works.append(_parse_work(root, Path(dirpath) / name))
                except (OSError, ValueError):
                    continue
    works.sort(key=lambda w: (w['folder'], w['actress'], w['code'], w['rel']))
    return works


def _download_codes():
    root = Path(downloads_root())
    codes = set()
    if root.is_dir():
        for dirpath, dirnames, filenames in os.walk(root):
            for dirname in dirnames:
                code = extract_code(dirname)
                if code:
                    codes.add(code)
            for name in filenames:
                if Path(name).suffix.lower() in VIDEO_EXTS:
                    code = extract_code(Path(name).stem)
                    if code:
                        codes.add(code)
    return codes


def _fresh(moment):
    return time.time() - moment < CACHE_SECONDS


def scan_library():
    """Works in the library, cached for CACHE_SECONDS."""
    with _lock:
        if _cache['works'] is not None and _fresh(_cache['at']):
            return list(_cache['works'])
    works = _scan()
    with _lock:
        _cache['works'] = works
        _cache['at'] = time.time()
    return list(works)


def code_index():
    """All known video codes: organised library plus loose downloads."""
    codes = {work['code'] for work in scan_library() if work['code']}
    with _lock:
        cached = _cache['dl_codes'] if _fresh(_cache['at']) else None
    if cached is None:
        cached = _download_codes()
        with _lock:
            _cache['dl_codes'] = cached
    return codes | cached


def resolve_stream(rel):
    """Absolute path for *rel* under the library or downloads root, else None.

    The resolved path must stay inside one of the roots; ``..`` escapes,
    absolute inputs and non-files are rejected.
    """
    if not rel or not isinstance(rel, str) or Path(rel).is_absolute():
        return None
    for raw_root in (library_root(), downloads_root()):
        base = Path(raw_root).resolve()
        try:
            target = (base / rel).resolve()
        except (OSError, RuntimeError):
            continue
        if target.is_relative_to(base) and target.is_file():
            return str(target)
    return None

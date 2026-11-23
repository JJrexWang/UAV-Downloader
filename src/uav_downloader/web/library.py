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
_RANK_PREFIX = re.compile(r'^\d{1,4}-')
_COPY_SUFFIX = re.compile(r'-\d{1,3}$')
_FOLDER_TITLE_RE = re.compile(r'^\[[^\]]+\]\s*(.*)$')
TOP_JAV = '01-日本JAV'
BUCKETS = {'共演·合集', 'FC2', '素人'}
CACHE_SECONDS = 60

_lock = threading.Lock()
_cache = {'at': 0.0, 'works': None, 'tree': None, 'dl_codes': None}


def library_root():
    return os.environ.get('LIBRARY_DIR', '/library')


def downloads_root():
    return os.environ.get('DOWNLOAD_DIR', '/downloads')


def _normalize_code(raw):
    match = _CODE_PARTS.fullmatch(raw or '')
    if not match:
        return (raw or '').upper()
    return f'{match.group(1).upper()}-{match.group(2)}'


def clean_actress_name(name):
    """Display name for an actress directory: drop rank/copy numbering.

    Library actress folders carry a ranking prefix (``264-楓富愛``) and
    sometimes a copy suffix (``032-目黑恵美-01``); both are filing
    artefacts, not part of the name.  Anything else is returned unchanged.
    """
    text = (name or '').strip()
    text = _RANK_PREFIX.sub('', text)
    text = _COPY_SUFFIX.sub('', text)
    return text.strip()


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
    actress_dir = ''
    folder = parts[0] if len(parts) >= 2 else ''
    if folder == TOP_JAV and len(parts) >= 3:
        segment = parts[1]
        if segment in BUCKETS:
            folder = segment
        else:
            actress_dir = segment
            actress = clean_actress_name(segment)
    # Cover: an image in the video's own directory whose stem equals the
    # video's stem (any category, folder layout or loose file alike).
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
            'actress': actress, 'actress_dir': actress_dir, 'folder': folder,
            'cover': cover, 'cover_rel': cover}


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
    tree = _build_tree(works)
    with _lock:
        _cache['works'] = works
        _cache['tree'] = tree
        _cache['at'] = time.time()
    return list(works)


def invalidate_cache():
    """Drop the scan caches (e.g. after a backfill filing changed the tree)."""
    with _lock:
        _cache['works'] = None
        _cache['tree'] = None
        _cache['dl_codes'] = None
        _cache['at'] = 0.0


def _build_tree(works):
    """Directory index derived from the flat works list.

    Maps every directory rel-path ('' is the library root) to its direct
    works, its immediate subdirectories and its recursive video count.
    Ancestor directories appear even when they hold no works directly.
    """
    nodes = {'': {'direct': [], 'subdirs': {}, 'total': 0}}

    def ensure(rel):
        node = nodes.get(rel)
        if node is None:
            node = nodes[rel] = {'direct': [], 'subdirs': {}, 'total': 0}
        return node

    for work in works:
        dir_rel = work['rel'].rsplit('/', 1)[0] if '/' in work['rel'] else ''
        segments = dir_rel.split('/') if dir_rel else []
        prefix = ''
        ensure('')
        for segment in segments:
            parent = prefix
            prefix = segment if not prefix else prefix + '/' + segment
            ensure(prefix)
            ensure(parent)['subdirs'].setdefault(segment, prefix)
        ensure(dir_rel)['direct'].append(work)
        prefix = ''
        nodes['']['total'] += 1
        for segment in segments:
            prefix = segment if not prefix else prefix + '/' + segment
            nodes[prefix]['total'] += 1
    return nodes


def library_tree():
    """The cached directory index built alongside the works scan."""
    scan_library()
    with _lock:
        tree = _cache['tree']
    if tree is None:  # Works were cached before the tree existed; rebuild.
        tree = _build_tree(scan_library())
        with _lock:
            _cache['tree'] = tree
    return tree


def resolve_dir(rel):
    """Absolute path for a directory *rel* under the library root, else None.

    '' resolves to the root itself.  Absolute inputs, ``..`` escapes and
    non-directories are rejected.
    """
    if not isinstance(rel, str) or Path(rel).is_absolute():
        return None
    base = Path(library_root()).resolve()
    try:
        target = (base / rel).resolve() if rel else base
    except (OSError, RuntimeError):
        return None
    if target.is_relative_to(base) and target.is_dir():
        return str(target)
    return None


def tree_view(path):
    """Payload for GET /api/library/tree, or None when *path* is not a
    directory inside the library root."""
    if resolve_dir(path) is None:
        return None
    tree = library_tree()
    node = tree.get(path) or {'direct': [], 'subdirs': {}, 'total': 0}
    folders = [{'name': name, 'rel': child,
                'count': tree.get(child, {}).get('total', 0)}
               for name, child in sorted(node['subdirs'].items())]
    crumbs = [{'name': '片库', 'rel': ''}]
    if path:
        prefix = ''
        for segment in path.split('/'):
            prefix = segment if not prefix else prefix + '/' + segment
            crumbs.append({'name': segment, 'rel': prefix})
    return {'path': path, 'crumbs': crumbs, 'folders': folders,
            'works': list(node['direct'])}


def actress_dirs():
    """Actress folders under 01-日本JAV: [{name, dir, count}], count desc.

    *name* is the cleaned display name; when several folders clean to the
    same name, *dir* is the one holding the most works and *count* is the
    merged total across all of them.
    """
    grouped = {}
    for work in scan_library():
        if work.get('folder') == TOP_JAV and work.get('actress_dir'):
            dir_rel = TOP_JAV + '/' + work['actress_dir']
            name = work.get('actress') or clean_actress_name(work['actress_dir'])
            if not name:
                continue
            per_dir = grouped.setdefault(name, {})
            per_dir[dir_rel] = per_dir.get(dir_rel, 0) + 1
    out = []
    for name, per_dir in grouped.items():
        best_dir = max(per_dir.items(), key=lambda item: item[1])[0]
        out.append({'name': name, 'dir': best_dir,
                    'count': sum(per_dir.values())})
    out.sort(key=lambda entry: (-entry['count'], entry['name']))
    return out


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

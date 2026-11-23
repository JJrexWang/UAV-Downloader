"""Local library naming cleanup (本地整理）.

Scans a library scope, identifies each video's code, grades the rename
candidate and — only after explicit confirmation — renames in place
(same directory), with a rollback log for every executed rename.

Grading (adapted from the user's xxxmovie-rename-preview resolve rules):
- F: name already matches the standard -> excluded, counted only;
- A: metadata complete, actress CN name from the CSV map (high confidence);
- B: title found, but actress CN missing or a low-confidence transliteration;
- C: code identified, no metadata hit;
- D: suspected misidentification (camera-style names, loose no-separator
  matches) -> isolated list, NEVER executable.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import threading
import time

from . import library, metadata, naming
from .postprocess import _filename_title

SCOPES = {'', '00-待分拣', '01-日本JAV', '02-精选专辑'}
SIDECAR_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.srt', '.ass', '.ssa', '.vtt'}
_CAMERA_PREFIXES = {'MOV', 'IMG', 'DSC', 'DSCN', 'VID', 'PXL', 'REC', 'MVI',
                    'SAM', 'DCIM', 'GOPR', 'DJI', 'MAH', 'MOL', 'PICT'}
_FC2_RE = re.compile(r'fc2[^a-z\d]{0,5}(?:ppv[^a-z\d]{0,5})?(\d{5,7})', re.I)
_STRICT_RE = re.compile(r'([A-Za-z]{2,6})[-_](\d{2,5})')
_LOOSE_RE = re.compile(r'([A-Za-z]{2,})(\d{2,5})')
_FOLDER_CODE_RE = re.compile(r'^\[([^\]]+)\]')
_lock = threading.Lock()


def _scan_path():
    return Path(metadata.state_dir()) / 'organize_scan.json'


def _log_path():
    return Path(metadata.state_dir()) / 'organize_log.jsonl'


def identify(stem, parent_name):
    """(code, strength) — strength 'strong' | 'weak' | '' (none)."""
    folder = _FOLDER_CODE_RE.match(parent_name or '')
    if folder:
        code = library.extract_code(folder.group(1))
        if code:
            return code, 'strong'
    fc2 = _FC2_RE.search(stem or '')
    if fc2:
        return f'FC2-PPV-{fc2.group(1)}', 'strong'
    strict = _STRICT_RE.search(stem or '')
    if strict:
        code = f'{strict.group(1).upper()}-{strict.group(2)}'
        if strict.group(1).upper() in _CAMERA_PREFIXES:
            return code, 'weak'
        return code, 'strong'
    loose = _LOOSE_RE.search(stem or '')
    if loose:
        return f'{loose.group(1).upper()}-{loose.group(2)}', 'weak'
    return '', ''


def _multi_segment(casts_jp, casts_cn):
    segments = []
    for jp, cn in zip(casts_jp, casts_cn):
        seg = naming.actress_segment(cn, jp)
        if seg:
            segments.append(seg)
    return ','.join(segments)


def _compose(code, segment, title, ext, suffix):
    parts = [code]
    if segment:
        parts.append(segment)
    clean = ' '.join(naming.to_hw(title or '').split()).strip()
    stem = '-'.join(parts) + ('-' + clean if clean else '') + suffix
    if naming.blen(stem + ext) <= naming.MAX_BYTES:
        return stem + ext
    squeezed = clean.replace(' ', '')
    stem = '-'.join(parts) + ('-' + squeezed if squeezed else '') + suffix
    if naming.blen(stem + ext) <= naming.MAX_BYTES:
        return stem + ext
    base = '-'.join(parts) + suffix
    budget = naming.MAX_BYTES - naming.blen(base) - 1 - naming.blen(ext)
    trimmed = naming._truncate_title(squeezed, max(budget, 0))
    return '-'.join(parts) + ('-' + trimmed if trimmed else '') + suffix + ext


def scan(scope):
    """Scan *scope* (relative dir under the library) and persist the result."""
    if scope not in SCOPES:
        raise ValueError('Unsupported scope')
    root = Path(library.library_root())
    base = root / scope if scope else root
    entries, isolated = [], []
    stats = {'scanned': 0, 'renamable': 0, 'isolated': 0, 'standard': 0,
             'unidentified': 0}
    meta_cache = {}
    if base.is_dir():
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames.sort()
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if path.suffix.lower() not in library.VIDEO_EXTS:
                    continue
                stats['scanned'] += 1
                rel = path.relative_to(root).as_posix()
                code, strength = identify(path.stem, path.parent.name)
                if strength == 'weak':
                    isolated.append({
                        'id': f'd{len(isolated)}', 'src_rel': rel, 'code': code,
                        'grade': 'D', 'new_name': '', 'source': None,
                        'actress_cn': None,
                        'reason': '疑似误识别（弱匹配），已隔离'})
                    continue
                if not code:
                    stats['unidentified'] += 1
                    continue
                if code not in meta_cache:
                    meta_cache[code] = metadata.lookup(code)
                meta = meta_cache[code]
                casts_jp = meta.get('casts_jp') or []
                casts_cn = meta.get('casts_cn') or []
                suffix = naming.part_suffix(path.stem)
                ext = path.suffix.lower()
                # Prefer a Chinese title hint from the filename itself; the
                # metadata (Japanese) title is the fallback (naming standard).
                title = _filename_title(path.stem, code) or meta.get('title')
                if len(casts_jp) > 1:
                    segment = _multi_segment(casts_jp, casts_cn)
                    new_name = _compose(code, segment, title, ext, suffix)
                elif casts_jp:
                    new_name = naming.build_name(
                        code, casts_cn[0], casts_jp[0], title,
                        ext, suffix)
                else:
                    hint = _filename_title(path.stem, code)
                    new_name = naming.build_name(code, None, None, hint, ext, suffix)
                if new_name == name:
                    stats['standard'] += 1
                    continue
                if meta.get('source') and meta.get('title'):
                    grade = 'A' if (casts_cn and casts_cn[0]
                                    and not meta.get('actress_cn_low')) else 'B'
                elif meta.get('source'):
                    grade = 'B'
                else:
                    grade = 'C'
                entries.append({
                    'id': f'o{len(entries)}', 'src_rel': rel, 'code': code,
                    'grade': grade, 'new_name': new_name,
                    'source': meta.get('source'),
                    'actress_cn': casts_cn[0] if casts_cn else None,
                    'actress_cn_low': bool(meta.get('actress_cn_low')),
                    'reason': ''})
    stats['renamable'] = len(entries)
    stats['isolated'] = len(isolated)
    result = {'ts': int(time.time()), 'scope': scope, 'stats': stats,
              'entries': entries, 'isolated': isolated}
    with _lock:
        path = _scan_path()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
            os.replace(temp, path)
        except OSError:
            pass
    return result


def load_scan():
    try:
        data = json.loads(_scan_path().read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def read_log():
    lines = []
    try:
        for raw in _log_path().read_text(encoding='utf-8').splitlines():
            if raw.strip():
                item = json.loads(raw)
                if isinstance(item, dict):
                    lines.append(item)
    except OSError:
        pass
    return lines


def _append_log(item):
    path = _log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'a', encoding='utf-8') as stream:
        stream.write(json.dumps(item, ensure_ascii=False) + '\n')


def _rewrite_log(lines):
    path = _log_path()
    temp = path.with_suffix('.tmp')
    with open(temp, 'w', encoding='utf-8') as stream:
        for item in lines:
            stream.write(json.dumps(item, ensure_ascii=False) + '\n')
    os.replace(temp, path)


def _sidecars(directory, stem):
    return [p for p in directory.iterdir()
            if p.is_file() and p.stem == stem
            and p.suffix.lower() in SIDECAR_EXTS]


def execute(ids):
    """Rename the given scan entries in place; returns per-id results."""
    wanted = set(ids or [])
    results = []
    with _lock:
        data = load_scan()
        if not data:
            return results
        root = Path(library.library_root())
        remaining = []
        for entry in data['entries']:
            if entry['id'] not in wanted:
                remaining.append(entry)
                continue
            src = root / entry['src_rel']
            dest = src.parent / entry['new_name']
            if not src.is_file():
                results.append({'id': entry['id'], 'ok': False, 'reason': '源文件不存在'})
                remaining.append(entry)
                continue
            if dest.exists():
                results.append({'id': entry['id'], 'ok': False, 'reason': '目标已存在'})
                remaining.append(entry)
                continue
            blockers = [p for p in _sidecars(src.parent, src.stem)
                        if (src.parent / (Path(entry['new_name']).stem + p.suffix.lower())).exists()]
            if blockers:
                results.append({'id': entry['id'], 'ok': False, 'reason': '同名附属文件目标已存在'})
                remaining.append(entry)
                continue
            new_stem = Path(entry['new_name']).stem
            for side in _sidecars(src.parent, src.stem):
                os.replace(side, src.parent / (new_stem + side.suffix.lower()))
            os.replace(src, dest)
            _append_log({'ts': int(time.time()), 'old_rel': entry['src_rel'],
                         'new_rel': dest.relative_to(root).as_posix(),
                         'reverted': False})
            results.append({'id': entry['id'], 'ok': True, 'reason': ''})
        data['entries'] = remaining
        data['stats']['renamable'] = len(remaining)
        path = _scan_path()
        try:
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
            os.replace(temp, path)
        except OSError:
            pass
    return results


def rollback(ids=None):
    """Reverse logged renames (all outstanding, or the given log indexes)."""
    with _lock:
        lines = read_log()
        if ids is None:
            targets = {i for i, item in enumerate(lines) if not item.get('reverted')}
        else:
            targets = set()
            for raw in ids:
                try:
                    idx = int(raw)
                except (TypeError, ValueError):
                    continue
                if 0 <= idx < len(lines) and not lines[idx].get('reverted'):
                    targets.add(idx)
        root = Path(library.library_root())
        rolled, failed = 0, []
        for idx in sorted(targets, reverse=True):
            item = lines[idx]
            current = root / item['new_rel']
            dest = root / item['old_rel']
            if not current.is_file():
                failed.append({'idx': idx, 'reason': '当前文件不存在'})
                continue
            if dest.exists():
                failed.append({'idx': idx, 'reason': '原名已被占用'})
                continue
            old_stem = dest.stem
            for side in _sidecars(current.parent, current.stem):
                target = current.parent / (old_stem + side.suffix.lower())
                if not target.exists():
                    os.replace(side, target)
            os.replace(current, dest)
            item['reverted'] = True
            rolled += 1
        if targets:
            _rewrite_log(lines)
        return {'rolled': rolled, 'failed': failed}


def state_view():
    """Last scan (or empty) plus the rollback log for the UI."""
    data = load_scan() or {'ts': None, 'scope': '', 'stats': None,
                           'entries': [], 'isolated': []}
    log = [{'idx': i, 'ts': item.get('ts'), 'old_rel': item.get('old_rel'),
            'new_rel': item.get('new_rel'),
            'reverted': bool(item.get('reverted'))}
           for i, item in enumerate(read_log())]
    return {**data, 'log': log}

"""Post-download rename + filing plans (Phase 2).

When a queue job completes, a plan is built for each resulting video in the
downloads root: a new name per the user's naming standard and a target
folder inside the library (``01-日本JAV/<女优中文名>/[<番号>] <片名>/``,
``共演·合集`` for multi-actress works, ``FC2`` for FC2 codes).  Plans wait
for confirmation (``file_mode == 'preview'``) or execute immediately
(``file_mode == 'auto'``).  Nothing is ever overwritten: an existing target
marks the plan ``conflict`` and leaves the source untouched.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
import uuid

from . import library, metadata, naming

SIDECAR_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.srt', '.ass', '.ssa', '.vtt'}
MAX_PLANS = 200
_lock = threading.Lock()


def _state_path():
    return Path(metadata.state_dir()) / 'postprocess.json'


def load_plans():
    try:
        data = json.loads(_state_path().read_text(encoding='utf-8'))
        return data if isinstance(data, list) else []
    except (OSError, ValueError):
        return []


def _save_plans(plans):
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(plans[-MAX_PLANS:], ensure_ascii=False),
                        encoding='utf-8')
        os.replace(temp, path)
    except OSError:
        pass


def _filename_title(stem, code):
    """Title hint from a downloaded filename: strip code, brackets, junk."""
    import re
    text = stem or ''
    if code:
        text = re.sub(re.escape(code), ' ', text, flags=re.I)
        text = re.sub(re.escape(code.replace('-', '')), ' ', text, flags=re.I)
    text = re.sub(r'\[[^\]]*\]', ' ', text)
    text = re.sub(r'【[^】]*】', ' ', text)
    text = re.sub(r'(?i)\b(1080p|720p|2160p|4k|fhd|hd|uncensored|中文字幕|中字)\b',
                  ' ', text)
    return ' '.join(text.replace('_', ' ').split()).strip(' -·/')[:120]


def _folder_title(title):
    """``[<CODE>] <title>`` folder segment, title shrunk to fit 255 bytes."""
    return title


def build_plan(src_path, downloads_root, intent=None):
    """One plan dict for a finished video file, or None if unidentifiable.

    With *intent* (a backfill record), the destination is forced: the file
    goes flat into ``intent['target_dir']`` under a name rebuilt from the
    intent's actress/title with this file's real extension and part suffix
    (identical to ``intent['target_name']`` for a plain .mp4).
    """
    src_path = Path(src_path)
    code = library.extract_code(src_path.stem)
    if not code:
        return None
    meta = metadata.lookup(code)
    casts_jp = meta.get('casts_jp') or []
    casts_cn = meta.get('casts_cn') or []
    actress_jp = casts_jp[0] if casts_jp else None
    actress_cn = casts_cn[0] if casts_cn else None
    # User's naming standard wants the Chinese title: a downloaded file's own
    # name carries the site's Chinese title, so it wins over the metadata
    # (Japanese) title, which is only a fallback for bare-code filenames.
    title = _filename_title(src_path.stem, code) or meta.get('title')
    suffix = naming.part_suffix(src_path.stem)
    ext = src_path.suffix.lower()
    new_name = naming.build_name(code, actress_cn, actress_jp, title, ext, suffix)
    reason = ''
    if code.upper().startswith('FC2'):
        folder_title = _folder_title(title)
        target_rel = f'{library.TOP_JAV}/FC2/[{code}] {folder_title}'.rstrip()
    elif len(casts_jp) >= 2:
        target_rel = f'{library.TOP_JAV}/共演·合集/[{code}] {_folder_title(title)}'.rstrip()
    elif actress_jp:
        folder_name = actress_cn or actress_jp
        if not actress_cn:
            reason = '女优中文名缺失，目录暂用日文名'
        target_rel = f'{library.TOP_JAV}/{folder_name}/[{code}] {_folder_title(title)}'.rstrip()
    else:
        target_rel = None
        reason = '未取得女优信息，仅原地重命名'
    if target_rel and naming.blen(target_rel.rsplit('/', 1)[-1]) > 255:
        head, _, leaf = target_rel.rpartition('/')
        budget = 255 - naming.blen(f'[{code}] ')
        leaf_title = naming._truncate_title(leaf[len(code) + 3:], budget)
        target_rel = f'{head}/[{code}] {leaf_title}'.rstrip()
    try:
        src_rel = src_path.relative_to(Path(downloads_root)).as_posix()
    except ValueError:
        src_rel = src_path.name
    plan = {
        'id': uuid.uuid4().hex[:12],
        'ts': int(time.time()),
        'src_name': src_path.name,
        'src_rel': src_rel,
        'code': code,
        'actress_cn': actress_cn,
        'actress_jp': actress_jp,
        'casts': len(casts_jp),
        'title': title,
        'source': meta.get('source'),
        'new_name': new_name,
        'target_rel': target_rel,
        'status': 'pending',
        'reason': reason,
    }
    if intent:
        plan['actress_cn'] = intent.get('actress_cn') or actress_cn
        plan['actress_jp'] = intent.get('actress_jp') or actress_jp
        plan['title'] = intent.get('title') or title
        plan['target_rel'] = intent['target_dir']
        plan['new_name'] = naming.build_name(
            code, plan['actress_cn'], plan['actress_jp'], plan['title'],
            ext, suffix)
        plan['reason'] = ''
        plan['backfill'] = True
    return plan


def file_with_intent(src_path, downloads_root, intent):
    """Build a forced-target plan for one file and execute it immediately.

    Returns the final plan dict (status done/conflict/error), or None when
    no plan could be built.  Used by the backfill completion hook, which
    files confirmed downloads regardless of the file_mode setting.
    """
    plan = build_plan(src_path, downloads_root, intent=intent)
    if not plan:
        return None
    with _lock:
        plans = load_plans()
        plans.append(plan)
        _save_plans(plans)
    execute([plan['id']])
    for saved in load_plans():
        if saved['id'] == plan['id']:
            return saved
    return plan


def discard_plan(plan_id):
    """Remove one plan entirely (backfill fallback housekeeping)."""
    with _lock:
        plans = [p for p in load_plans() if p.get('id') != plan_id]
        _save_plans(plans)


def plan_for_completed_job(job, downloads_root):
    """Queue hook: build plans for a completed job's files; maybe auto-run.

    Reads settings.json fresh (same merge rules as server.load_settings).
    Fully self-contained: callers wrap this in try/except, and this function
    itself never raises into the queue.
    """
    try:
        settings = {'auto_rename': True, 'file_mode': 'preview'}
        try:
            saved = json.loads(
                (Path(metadata.state_dir()) / 'settings.json')
                .read_text(encoding='utf-8'))
            if isinstance(saved, dict):
                if type(saved.get('auto_rename')) is bool:
                    settings['auto_rename'] = saved['auto_rename']
                if saved.get('file_mode') in ('preview', 'auto'):
                    settings['file_mode'] = saved['file_mode']
        except (OSError, ValueError):
            pass
        if not settings['auto_rename']:
            return []
        code = library.extract_code(job.get('url', ''))
        if not code:
            return []
        root = Path(downloads_root)
        with _lock:
            plans = load_plans()
            known = {p['src_rel'] for p in plans}
            fresh = []
            for dirpath, _dirs, filenames in os.walk(root):
                for name in sorted(filenames):
                    path = Path(dirpath) / name
                    if path.suffix.lower() not in library.VIDEO_EXTS:
                        continue
                    if library.extract_code(path.stem) != code:
                        continue
                    rel = path.relative_to(root).as_posix()
                    if rel in known:
                        continue
                    plan = build_plan(path, root)
                    if plan:
                        fresh.append(plan)
            if fresh:
                plans.extend(fresh)
                _save_plans(plans)
        if fresh and settings['file_mode'] == 'auto':
            execute([p['id'] for p in fresh])
            synced = {p['id']: p for p in load_plans()}
            for plan in fresh:
                if plan['id'] in synced:
                    plan.update(synced[plan['id']])
        return fresh
    except Exception:
        return []


def execute(ids):
    """Move planned files (+ same-stem sidecars) into the library."""
    wanted = set(ids or [])
    results = []
    with _lock:
        plans = load_plans()
        by_id = {p['id']: p for p in plans}
        downloads = Path(library.downloads_root())
        library_root = Path(library.library_root())
        for plan_id in wanted:
            plan = by_id.get(plan_id)
            if not plan or plan['status'] != 'pending':
                continue
            try:
                results.append(_execute_one(plan, downloads, library_root))
            except Exception as exc:  # per-item isolation
                plan['status'] = 'error'
                plan['reason'] = f'{type(exc).__name__}: {exc}'[:200]
                results.append(plan)
        _save_plans(plans)
    return results


def _execute_one(plan, downloads, library_root):
    src = downloads / plan['src_rel']
    if not src.is_file():
        plan['status'] = 'error'
        plan['reason'] = '源文件不存在'
        return plan
    if plan['target_rel']:
        dest_dir = library_root / plan['target_rel']
    else:
        dest_dir = src.parent
    new_stem = Path(plan['new_name']).stem
    moves = [(src, dest_dir / plan['new_name'])]
    for sibling in src.parent.iterdir():
        if sibling == src or not sibling.is_file():
            continue
        if sibling.stem == src.stem and sibling.suffix.lower() in SIDECAR_EXTS:
            moves.append((sibling, dest_dir / (new_stem + sibling.suffix.lower())))
    for _old, new in moves:
        if new.exists():
            plan['status'] = 'conflict'
            plan['reason'] = f'目标已存在：{new.name}'
            return plan
    dest_dir.mkdir(parents=True, exist_ok=True)
    import shutil
    for old, new in moves:
        shutil.move(str(old), str(new))  # rename, or copy+delete across disks
    plan['status'] = 'done'
    plan['reason'] = ''
    return plan


def dismiss(ids):
    wanted = set(ids or [])
    with _lock:
        plans = load_plans()
        for plan in plans:
            if plan['id'] in wanted and plan['status'] != 'done':
                plan['status'] = 'dismissed'
        _save_plans(plans)
        return plans

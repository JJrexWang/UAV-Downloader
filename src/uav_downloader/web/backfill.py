"""Actress backfill （补充入库）: plan, confirmed enqueue, forced filing.

From a search result list (typically one actress's works), the plan step
classifies each item — already in the library, already queued, actress
unknown, or ready — and resolves where a download would be filed: the
actress's existing folder under ``01-日本JAV`` (real directory name,
rank prefix included) or a new ``01-日本JAV/<女优中文名>`` folder, under
the standard main name from naming.py.

Starting a backfill enqueues through the normal queue add path and records
an intent per job in ``<state>/backfill.json``.  When such a job completes,
the queue hook files the download straight into the intent's target —
regardless of the file_mode setting, because the user already confirmed
exactly this filing in the plan dialog.  Any failure leaves the file in
the downloads root and lets the normal preview-plan flow take over.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading

from . import actress as actress_svc
from . import library, metadata, naming
from .queue import validate_job

_lock = threading.Lock()
_ACTIVE = {'pending', 'running', 'cancelling'}


# ---------------------------------------------------------------------------
# Intent store
# ---------------------------------------------------------------------------

def _path():
    return Path(metadata.state_dir()) / 'backfill.json'


def load_intents():
    """{job_id: {code, target_dir, target_name, actress_cn, actress_jp, title}}."""
    try:
        data = json.loads(_path().read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_intents(intents):
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(intents, ensure_ascii=False), encoding='utf-8')
        os.replace(temp, path)
    except OSError:
        pass


def intent_for(job_id):
    if not job_id:
        return None
    return load_intents().get(job_id)


def _record_intents(mapping):
    if not mapping:
        return
    with _lock:
        intents = load_intents()
        intents.update(mapping)
        _save_intents(intents)


def _drop_intent(job_id):
    with _lock:
        intents = load_intents()
        if job_id in intents:
            del intents[job_id]
            _save_intents(intents)


# ---------------------------------------------------------------------------
# Plan
# ---------------------------------------------------------------------------

def _queued_marks(snapshot):
    codes, urls = set(), set()
    for job in (snapshot or {}).get('jobs', []):
        if (job or {}).get('status') not in _ACTIVE:
            continue
        url = job.get('url', '')
        if url:
            urls.add(url.rstrip('/'))
            code = library.extract_code(url)
            if code:
                codes.add(code)
    return codes, urls


def _find_actress_dir(actress_cn, actress_jp):
    """Existing 01-日本JAV subdir for this actress (real name), or None.

    Comparison tolerates traditional/simplified variants (the folder may
    use 八挂海 while the resolved name came from a 八掛海 hint); the
    returned path always carries the folder's real on-disk name.
    """
    top = Path(library.library_root()) / library.TOP_JAV
    try:
        names = sorted(os.listdir(top))
    except OSError:
        return None
    targets = {n for n in (actress_cn, actress_jp) if n}
    normalised = {actress_svc.normalize_name(n) for n in targets}
    for name in names:
        if not (top / name).is_dir():
            continue
        cleaned = library.clean_actress_name(name)
        if cleaned and (cleaned in targets
                        or actress_svc.normalize_name(cleaned) in normalised):
            return f'{library.TOP_JAV}/{name}'
    return None


def _resolve_item(item, hint, library_codes, queued_codes, queued_urls):
    url = item.get('url') or ''
    code = (library.extract_code(item.get('code') or '')
            or library.extract_code(url))
    site_title = (item.get('title') or '').strip()
    entry = {'code': code, 'url': url, 'site_title': site_title,
             'title': site_title, 'actress_jp': None, 'actress_cn': None,
             'target_dir': None, 'target_name': None, 'status': 'ready'}
    if code and code in library_codes:
        entry['status'] = 'in_library'
        return entry
    if (code and code in queued_codes) or (url and url.rstrip('/') in queued_urls):
        entry['status'] = 'in_queue'
        return entry
    meta = metadata.lookup(code) if code else dict(metadata.EMPTY)
    actress_jp = meta.get('actress_jp')
    actress_cn = meta.get('actress_cn')
    hint = (hint or '').strip()
    if hint and hint not in (actress_jp, actress_cn) and not actress_jp and not actress_cn:
        # Metadata has nothing; fall back to the caller-supplied name.
        if actress_svc.looks_japanese(hint):
            actress_jp = hint
            actress_cn = actress_svc.cn_name_for(hint)
        else:
            cn_exact, jp_exact = actress_svc.resolve_cn_entry(hint)
            if cn_exact:
                actress_cn, actress_jp = cn_exact, jp_exact
            else:
                actress_cn = hint
                actress_jp = actress_svc.resolve_jp_name(hint)
    entry['actress_jp'] = actress_jp
    entry['actress_cn'] = actress_cn
    entry['title'] = site_title or meta.get('title') or ''
    if not actress_jp and not actress_cn:
        entry['status'] = 'no_actress'
        return entry
    entry['target_dir'] = (_find_actress_dir(actress_cn, actress_jp)
                           or f'{library.TOP_JAV}/{actress_cn or actress_jp}')
    entry['target_name'] = naming.build_name(
        code, actress_cn, actress_jp, entry['title'], '.mp4')
    return entry


def plan(items, actress_hint, snapshot):
    """Classify candidate items and resolve filing targets; never enqueues."""
    library_codes = {w['code'] for w in library.scan_library() if w.get('code')}
    queued_codes, queued_urls = _queued_marks(snapshot)
    resolved = [_resolve_item(item, actress_hint, library_codes,
                              queued_codes, queued_urls)
                for item in items or []]
    return {'items': resolved,
            'ready_count': sum(1 for e in resolved if e['status'] == 'ready')}


# ---------------------------------------------------------------------------
# Start
# ---------------------------------------------------------------------------

def _text(item, key):
    value = (item or {}).get(key)
    return value.strip() if isinstance(value, str) else ''


def _confirmed_entry(item):
    """Plan entry built from the fields the user confirmed in the dialog.

    The confirmed actress and title are taken as-is, but the filing target
    is recomputed server-side — the client's target_dir/target_name are
    never trusted verbatim.
    """
    url = item.get('url') or ''
    code = (library.extract_code(item.get('code') or '')
            or library.extract_code(url))
    title = _text(item, 'title')
    actress_jp = _text(item, 'actress_jp') or None
    actress_cn = _text(item, 'actress_cn') or None
    target_name = naming.build_name(code, actress_cn, actress_jp, title, '.mp4')
    if not target_name:
        target_name = _text(item, 'target_name') or None
    return {'code': code, 'url': url, 'site_title': title,
            'title': title, 'actress_jp': actress_jp,
            'actress_cn': actress_cn,
            'target_dir': (_find_actress_dir(actress_cn, actress_jp)
                           or f'{library.TOP_JAV}/{actress_cn or actress_jp}'),
            'target_name': target_name, 'status': 'ready'}


def start(items, queue, actress_hint=None):
    """Enqueue the confirmed plan; record a filing intent per job.

    Items carrying the actress fields the user confirmed are filed exactly
    as confirmed (targets recomputed server-side); the rest are re-resolved
    through the plan path with *actress_hint*.  Either way every entry is
    re-checked against the current library and queue before enqueueing.
    """
    snapshot = queue.snapshot()
    library_codes = {w['code'] for w in library.scan_library() if w.get('code')}
    queued_codes, queued_urls = _queued_marks(snapshot)
    planned = []
    for item in items or []:
        if _text(item, 'actress_jp') or _text(item, 'actress_cn'):
            entry = _confirmed_entry(item)
            if entry['code'] and entry['code'] in library_codes:
                entry['status'] = 'in_library'
            elif ((entry['code'] and entry['code'] in queued_codes)
                  or (entry['url']
                      and entry['url'].rstrip('/') in queued_urls)):
                entry['status'] = 'in_queue'
        else:
            entry = _resolve_item(item, actress_hint, library_codes,
                                  queued_codes, queued_urls)
        planned.append(entry)
    to_add, skipped = [], []
    seen_codes, seen_urls = set(), set()
    for entry in planned:
        if entry['status'] != 'ready':
            skipped.append({'code': entry['code'], 'reason': entry['status']})
            continue
        if entry['code'] in seen_codes or entry['url'].rstrip('/') in seen_urls:
            skipped.append({'code': entry['code'], 'reason': 'in_queue'})
            continue
        try:
            validate_job({'url': entry['url']})
        except ValueError:
            skipped.append({'code': entry['code'], 'reason': 'invalid_url'})
            continue
        seen_codes.add(entry['code'])
        seen_urls.add(entry['url'].rstrip('/'))
        to_add.append(entry)
    added = 0
    if to_add:
        intents = {}
        # QueueManager.add accepts at most 100 jobs per call; enqueue in
        # chunks so a confirmed backfill with more ready items still works.
        for offset in range(0, len(to_add), 100):
            batch = to_add[offset:offset + 100]
            jobs = queue.add([{'url': entry['url']} for entry in batch])
            for entry, job in zip(batch, jobs):
                intents[job['id']] = {
                    'code': entry['code'],
                    'target_dir': entry['target_dir'],
                    'target_name': entry['target_name'],
                    'actress_cn': entry['actress_cn'],
                    'actress_jp': entry['actress_jp'],
                    'title': entry['title'],
                }
            added += len(jobs)
        _record_intents(intents)
    return {'added': added, 'skipped': skipped}


# ---------------------------------------------------------------------------
# Completion hook (called from queue._work; must never raise)
# ---------------------------------------------------------------------------

def handle_completed_job(job, downloads_root):
    """File a completed backfill job into its intent target.

    Returns True only when the file actually landed in the library; the
    intent is consumed then.  On any failure the intent is kept, the file
    stays in the downloads root, and False lets the caller fall back to
    the normal preview-plan flow.
    """
    try:
        intent = intent_for((job or {}).get('id'))
        if not intent:
            return False
        code = library.extract_code(job.get('url', '')) or intent.get('code')
        if not code:
            return False
        from . import postprocess
        root = Path(downloads_root)
        filed = False
        for dirpath, _dirs, filenames in os.walk(root):
            for name in sorted(filenames):
                path = Path(dirpath) / name
                if path.suffix.lower() not in library.VIDEO_EXTS:
                    continue
                if library.extract_code(path.stem) != code:
                    continue
                result = postprocess.file_with_intent(path, root, intent)
                if result and result.get('status') == 'done':
                    filed = True
                elif result:
                    # Not filed: drop the forced plan so the normal
                    # preview plan becomes the fallback for this file.
                    postprocess.discard_plan(result['id'])
        if filed:
            library.invalidate_cache()
            _drop_intent(job['id'])
        return filed
    except Exception:
        return False

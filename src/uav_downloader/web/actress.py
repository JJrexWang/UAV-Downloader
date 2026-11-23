"""Actress filmography gap check for the web UI （女优缺片）.

Flow: a library actress folder (Chinese name) or a typed name is resolved to
a Jable actress page, the page's full filmography is listed, and the works
the library does not own yet are returned as "missing" (each flagged when it
is already in the download queue).

Slug resolution never guesses a URL: Jable actress slugs are not derivable
from the name, so we search Jable for one of the actress's own videos, open
its detail page, and take the ``/actresses/<slug>/`` anchor whose link text
matches the actress name.  All network failures degrade to an ``error``
string — this module never raises.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import quote

from . import library, metadata

CACHE_SECONDS = 24 * 3600
MAX_PAGES = 10
_KANA_RE = re.compile(r'[぀-ヿ]')
_ACTRESS_HREF_RE = re.compile(r'/actresses/([a-z0-9_-]+)/?', re.I)
_lock = threading.Lock()
_reverse_cache = None


def _cache_path():
    return Path(metadata.state_dir()) / 'actress_cache.json'


# ---------------------------------------------------------------------------
# Name resolution
# ---------------------------------------------------------------------------

def _reverse_map():
    """CN name -> JP name, built from the bundled actress CSV."""
    global _reverse_cache
    if _reverse_cache is None:
        table = {}
        for jp_name, (cn_name, _conf) in metadata.actress_map().items():
            if cn_name and cn_name not in table:
                table[cn_name] = jp_name
        _reverse_cache = table
    return _reverse_cache


def looks_japanese(text):
    """True when *text* contains kana (a usable heuristic for JP names)."""
    return bool(text) and bool(_KANA_RE.search(text))


def resolve_jp_name(name_cn):
    """JP name for a Chinese actress name, or None.

    Reverse-looks-up the CSV map （中国名 -> 日文名）.  When the input is not
    in the map but itself looks Japanese (contains kana), it is treated as
    the JP name already.
    """
    name = (name_cn or '').strip()
    if not name:
        return None
    hit = _reverse_map().get(name)
    if hit:
        return hit
    if looks_japanese(name):
        return name
    return None


def cn_name_for(jp_name):
    """CN name for an exact JP name from the CSV, or None."""
    if not jp_name:
        return None
    hit = metadata.actress_map().get(jp_name.strip())
    return hit[0] if hit else None


# ---------------------------------------------------------------------------
# Library side
# ---------------------------------------------------------------------------

def library_actresses():
    """Actresses under 01-日本JAV with their owned codes, most works first."""
    grouped = {}
    for work in library.scan_library():
        if work.get('folder') == library.TOP_JAV and work.get('actress'):
            name = library.clean_actress_name(work['actress'])
            if not name:
                continue
            entry = grouped.setdefault(name, {'name_cn': name, 'codes': []})
            if work['code'] and work['code'] not in entry['codes']:
                entry['codes'].append(work['code'])
    actresses = []
    for entry in grouped.values():
        entry['codes'].sort()
        entry['count'] = len(entry['codes'])
        actresses.append(entry)
    actresses.sort(key=lambda a: (-a['count'], a['name_cn']))
    return actresses


# ---------------------------------------------------------------------------
# Jable side: slug resolution via a known video's detail page
# ---------------------------------------------------------------------------

def extract_actress_slug(html, names):
    """Slug from a Jable detail page whose actress anchor matches a name.

    *names* are candidate display names (JP name, CN folder name, typed
    name); an anchor matches when its text equals a candidate or contains
    one (e.g. the name plus a suffix).  Returns None when nothing matches —
    never guesses.
    """
    if not html:
        return None
    targets = [str(n).strip() for n in (names or []) if n and str(n).strip()]
    if not targets:
        return None
    pairs = []
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        for anchor in soup.find_all('a', href=True):
            match = _ACTRESS_HREF_RE.search(anchor.get('href') or '')
            if match:
                pairs.append((match.group(1), anchor.get_text(' ', strip=True)))
    except Exception:
        pairs = []
    if not pairs:
        pattern = re.compile(
            r'<a[^>]+href="[^"]*?/actresses/([a-z0-9_-]+)/?"[^>]*>(.*?)</a>',
            re.S | re.I)
        for match in pattern.finditer(html):
            text = re.sub(r'<[^>]+>', '', match.group(2)).strip()
            pairs.append((match.group(1), text))
    for slug, text in pairs:
        if len(text) < 2:
            continue
        if any(t == text or t in text for t in targets):
            return slug
    return None


def _detail_html(url):
    """Raw HTML of a Jable video detail page via the site's own fetchers."""
    try:
        from uav_downloader.sites import jabletv
        from uav_downloader.sites.base import fetch_with_mirrors

        def _validate(resp):
            return 'og:title' in resp.text

        with jabletv._make_scraper() as scraper:
            jabletv._apply_jable_lang(scraper)
            resp, _host, reason = fetch_with_mirrors(
                scraper, url, 'jable', _validate, timeout=20)
        if reason != 'ok' or resp is None:
            return None
        return resp.text
    except Exception:
        return None


def _search_urls(query, limit=3):
    """First *limit* result URLs of a Jable search, [] on any failure."""
    if not query:
        return []
    try:
        from uav_downloader.sites.jabletv import JableTVList
        listing = JableTVList('https://jable.tv/search/?q=' + quote(str(query), safe=''),
                              silence=True)
        if getattr(listing, 'islist', None) is None:
            return []
        return list(getattr(listing, 'links', None) or [])[:limit]
    except Exception:
        return []


def find_actress_slug(jp_name, sample_code=None, names=()):
    """Resolve a Jable actress slug, or None.

    Strategy, in order: (a) search Jable for *sample_code* (a code the
    library owns for this actress), open the first result's detail page and
    extract the actress anchor matching one of the candidate names;
    (b) search Jable for the name itself and try the first few detail pages
    the same way.
    """
    candidates = []
    for name in [jp_name, *(names or [])]:
        if name and name not in candidates:
            candidates.append(name)
    if not candidates:
        return None
    try:
        if sample_code:
            urls = _search_urls(sample_code, limit=1)
            if urls:
                slug = extract_actress_slug(_detail_html(urls[0]), candidates)
                if slug:
                    return slug
        query = jp_name or candidates[0]
        for url in _search_urls(query, limit=3):
            slug = extract_actress_slug(_detail_html(url), candidates)
            if slug:
                return slug
    except Exception:
        return None
    return None


# ---------------------------------------------------------------------------
# Filmography (cached per slug for 24h)
# ---------------------------------------------------------------------------

def _load_cache():
    try:
        data = json.loads(_cache_path().read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save_cache(cache):
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(cache, ensure_ascii=False), encoding='utf-8')
        os.replace(temp, path)
    except OSError:
        pass


def filmography(slug):
    """(works, cached) for a Jable actress slug.

    Works are ``[{code, title, url, thumbnail}]`` deduped by code, gathered
    from up to MAX_PAGES list pages.  Fresh (<24h) cache entries are served
    without network access.  Failures return ([], False).
    """
    slug = (slug or '').strip()
    if not slug:
        return [], False
    with _lock:
        entry = _load_cache().get(slug)
    if (isinstance(entry, dict) and isinstance(entry.get('works'), list)
            and time.time() - float(entry.get('ts') or 0) < CACHE_SECONDS):
        return [dict(w) for w in entry['works']], True
    works = []
    seen = set()

    def collect(listing):
        links = getattr(listing, 'links', None) or []
        descriptions = getattr(listing, 'linkDescriptions', None) or []
        try:
            thumbnails = listing.getThumbnails() or []
        except Exception:
            thumbnails = []
        added = 0
        for i, url in enumerate(links):
            code = library.extract_code(url)
            if not code or code in seen:
                continue
            seen.add(code)
            works.append({'code': code,
                          'title': descriptions[i] if i < len(descriptions) else '',
                          'url': url,
                          'thumbnail': thumbnails[i] if i < len(thumbnails) else ''})
            added += 1
        return added

    try:
        from uav_downloader.sites.jabletv import JableTVList
        listing = JableTVList(f'https://jable.tv/actresses/{slug}/', silence=True)
        if getattr(listing, 'islist', None) is not None:
            collect(listing)
            total_pages = min(int(getattr(listing, 'totalPages', 1) or 1), MAX_PAGES)
            sortby = getattr(listing, 'sortType', None)
            for index in range(1, total_pages):
                try:
                    listing.loadPageAtIndex(index, sortby)
                except Exception:
                    break
                if getattr(listing, 'islist', None) is None:
                    break
                if collect(listing) == 0:
                    break  # Page repeated or empty; further pages won't help.
    except Exception:
        works = []
    if works:
        with _lock:
            cache = _load_cache()
            cache[slug] = {'ts': time.time(), 'works': works}
            _save_cache(cache)
    return works, False


# ---------------------------------------------------------------------------
# Gap check
# ---------------------------------------------------------------------------

def _queue_marks(snapshot):
    """(normalised url set, code set) from a queue snapshot dict."""
    urls, codes = set(), set()
    for job in (snapshot or {}).get('jobs', []):
        url = (job or {}).get('url', '')
        if url:
            urls.add(url.rstrip('/') + '/')
            code = library.extract_code(url)
            if code:
                codes.add(code)
    return urls, codes


def gap(actress_input, snapshot=None):
    """Full gap check for one actress; always returns a result dict.

    Keys: actress_cn, actress_jp, slug, total, owned (codes), missing
    ([{code, title, url, thumbnail, in_queue}]), cached, error.
    """
    result = {'actress_cn': None, 'actress_jp': None, 'slug': None, 'total': 0,
              'owned': [], 'missing': [], 'cached': False, 'error': None}
    name = (actress_input or '').strip()
    if not name:
        result['error'] = '请输入女优名'
        return result
    try:
        by_name = {a['name_cn']: a for a in library_actresses()}
    except Exception:
        by_name = {}
    entry = by_name.get(name)
    folder_codes = list(entry['codes']) if entry else []
    jp_name = resolve_jp_name(name)
    if jp_name is None and name in metadata.actress_map():
        jp_name = name  # The user typed the JP name directly.
    actress_cn = name if entry else cn_name_for(jp_name)
    result['actress_cn'] = actress_cn
    result['actress_jp'] = jp_name
    sample_code = folder_codes[0] if folder_codes else None
    slug = find_actress_slug(jp_name, sample_code,
                             names=[n for n in (name, actress_cn) if n])
    if not slug:
        result['owned'] = folder_codes
        result['error'] = '未能在 Jable 找到该女优主页（可换日文名或繁体名重试）'
        return result
    result['slug'] = slug
    works, cached = filmography(slug)
    result['cached'] = cached
    if not works:
        result['owned'] = folder_codes
        result['error'] = '未能读取该女优的作品列表（站点不可达或被拦截，请稍后重试）'
        return result
    try:
        library_codes = {w['code'] for w in library.scan_library() if w.get('code')}
    except Exception:
        library_codes = set(folder_codes)
    queued_urls, queued_codes = _queue_marks(snapshot)
    owned, missing = [], []
    for work in works:
        if work['code'] in library_codes:
            owned.append(work['code'])
        else:
            missing.append({**work,
                            'in_queue': (work['url'].rstrip('/') + '/' in queued_urls
                                         or work['code'] in queued_codes)})
    result['total'] = len(works)
    result['owned'] = owned
    result['missing'] = missing
    if actress_cn is None:
        result['actress_cn'] = name
    return result

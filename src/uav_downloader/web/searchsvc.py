"""Site search adapters for the web UI.

Wraps the existing per-site search/list machinery (the same code the desktop
Browser uses) into one normalised result shape.  Site or network failures are
returned as an ``error`` string; this module never raises.
"""
from __future__ import annotations

import re
from urllib.parse import quote

_CODE_RE = re.compile(r'[A-Za-z]{2,6}-?\d{2,5}')
_CODE_PARTS = re.compile(r'([A-Za-z]{2,6})-?(\d{2,5})')
_SLUG_CODE = re.compile(r'([A-Za-z]+)-(\d+)')
SITES = ('jable', 'missav', 'supjav')
_MAX_PAGES = 10  # Hard cap on pages fetched per search (all sites).
_JABLE_PAGE_SIZE = 24  # JableTVList.totalPages is derived with 24 per page.


def _normalize_code(raw):
    match = _CODE_PARTS.fullmatch(raw or '')
    if not match:
        return (raw or '').upper()
    return f'{match.group(1).upper()}-{match.group(2)}'


def _slug(url):
    return (url or '').rstrip('/').rsplit('/', 1)[-1].split('?')[0]


def _code_from_slug(url):
    return _slug(url).upper()


def _missav_code(url):
    match = _SLUG_CODE.match(_slug(url))
    if match:
        return f'{match.group(1).upper()}-{match.group(2)}'
    return _slug(url).upper()


def _code_from_title(title):
    match = _CODE_RE.search(title or '')
    return _normalize_code(match.group(0)) if match else ''


_CODE_SUFFIX_RE = re.compile(r'([A-Za-z]{2,6}-\d{2,5})[A-Za-z]+\d*')


def _canonical_code(code):
    """Canonical code for the library-membership test in :func:`search`.

    Slug codes can carry a suffix the library extractor drops
    (``ABW-041SDC3`` -> ``ABW-041``); comparing canonical forms keeps the
    search annotation in agreement with backfill's plan.  Codes whose
    digits come last (``FC2PPV-1234567``) do not match the pattern and
    pass through unchanged.
    """
    match = _CODE_SUFFIX_RE.fullmatch(code or '')
    if match:
        return match.group(1).upper()
    return (code or '').upper()


def _search_jable(query):
    from uav_downloader.sites.jabletv import JableTVList
    # Path-style search URL: JableTVList parses the keyword out of the path
    # (url.split('/')[4]) and needs it to build page 2+ URLs; the '?q=' form
    # leaves searchKeyWord as '?q=...' and breaks pagination.
    listing = JableTVList('https://jable.tv/search/' + quote(query, safe='') + '/',
                          silence=True)
    if getattr(listing, 'islist', None) is None:
        raise RuntimeError('Jable 未返回列表（站点不可达或被拦截）')
    results = []
    seen = set()

    def collect():
        """Append the listing's current page; return (page size, added)."""
        links = getattr(listing, 'links', None) or []
        descriptions = getattr(listing, 'linkDescriptions', None) or []
        try:
            thumbnails = listing.getThumbnails() or []
        except Exception:
            thumbnails = []
        added = 0
        for i, url in enumerate(links):
            if not url or url in seen:
                continue
            seen.add(url)
            results.append({'url': url,
                            'title': descriptions[i] if i < len(descriptions) else '',
                            'thumbnail': thumbnails[i] if i < len(thumbnails) else '',
                            'duration': '',
                            'code': _code_from_slug(url)})
            added += 1
        return len(links), added

    page_size, _added = collect()
    total_pages = int(getattr(listing, 'totalPages', 1) or 1)
    planned = min(max(total_pages, 1), _MAX_PAGES)
    sortby = getattr(listing, 'sortType', None)
    index = 1
    while index < _MAX_PAGES:
        if index >= planned and page_size < _JABLE_PAGE_SIZE:
            # Past the reported page count only a completely full page
            # justifies probing further: totalLinks/totalPages come from
            # page markup that does not always match (the count then falls
            # back to page 1's size), so a reported "1 page" is not trusted
            # when page 1 came back full.  A short page is the last page.
            break
        try:
            listing.loadPageAtIndex(index, sortby)
        except Exception:
            break  # Later-page failure: keep the pages already collected.
        if getattr(listing, 'islist', None) is None:
            break
        page_size, added = collect()
        if added == 0:
            break  # Empty page, or a failed load replaying the previous one.
        index += 1
    total = max(len(results), getattr(listing, 'totalLinks', 0) or 0)
    return results, total


def _search_missav(query):
    from uav_downloader.sites.missav import SiteMissAV
    # The URL SiteMissAV.search builds for lang 'cn', fetched page by page
    # (search() itself only ever returns the first page).
    url = 'https://missav.ai/cn/search/' + quote(query, safe='')
    results = []
    seen = set()

    def collect(videos):
        added = 0
        for video in videos or []:
            video_url = video.get('url', '')
            if not video_url or video_url in seen:
                continue
            seen.add(video_url)
            results.append({'url': video_url,
                            'title': video.get('title', ''),
                            'thumbnail': video.get('thumbnail', ''),
                            'duration': video.get('duration', ''),
                            'code': _missav_code(video_url)})
            added += 1
        return added

    first = SiteMissAV.fetch_page(url)  # Page-1 failure keeps the old error.
    collect(first)
    if first:
        for page in range(2, _MAX_PAGES + 1):
            try:
                videos = SiteMissAV.fetch_page(SiteMissAV.page_url(url, page))
            except Exception:
                break  # Later-page failure: keep what we have.
            if not videos or collect(videos) == 0:
                break
    return results, len(results)


def _search_supjav(query):
    from uav_downloader.sites.supjav import SupJavBrowser
    # SupJavBrowser.search() is fetch_page(search_url(query)) — one page.
    base = SupJavBrowser.search_url(query)
    results = []
    seen = set()

    def collect(videos):
        added = 0
        for video in videos or []:
            video_url = video.get('url', '')
            if not video_url or video_url in seen:
                continue
            seen.add(video_url)
            results.append({'url': video_url,
                            'title': video.get('title', ''),
                            'thumbnail': video.get('thumbnail', ''),
                            'duration': video.get('duration', ''),
                            'code': _code_from_title(video.get('title', ''))})
            added += 1
        return added

    first = SupJavBrowser.fetch_page(base)  # Page-1 failure = old error.
    collect(first)
    if first:
        for page in range(2, _MAX_PAGES + 1):
            try:
                videos = SupJavBrowser.fetch_page(SupJavBrowser.page_url(base, page))
            except Exception:
                break  # Later-page failure: keep what we have.
            if not videos or collect(videos) == 0:
                break
    return results, len(results)


_SEARCHERS = {'jable': _search_jable, 'missav': _search_missav,
              'supjav': _search_supjav}


def search(site, query, queue_urls, library_codes):
    """Search *site* for *query*; annotate results with library/queue state."""
    site = (site or 'jable').strip().lower()
    if site not in _SEARCHERS:
        return {'results': [], 'total': 0, 'error': f'不支持的站点：{site}'}
    queued = {(url or '').rstrip('/') + '/' for url in (queue_urls or [])}
    known = library_codes or set()
    try:
        raw, total = _SEARCHERS[site](query)
    except Exception as exc:  # Site/network failure: report, never raise.
        detail = str(exc).strip()[:120] or type(exc).__name__
        return {'results': [], 'total': 0, 'error': f'{site} 搜索失败：{detail}'}
    results = []
    for item in raw:
        url = item.get('url', '')
        if not url:
            continue
        code = item.get('code', '')
        results.append({'code': code,
                        'title': item.get('title', ''),
                        'url': url,
                        'site': site,
                        'thumbnail': item.get('thumbnail', ''),
                        'duration': item.get('duration', ''),
                        'in_library': bool(code) and _canonical_code(code) in known,
                        'in_queue': url.rstrip('/') + '/' in queued})
    return {'results': results, 'total': total, 'error': None}

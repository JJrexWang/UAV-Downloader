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


def _search_jable(query):
    from uav_downloader.sites.jabletv import JableTVList
    listing = JableTVList('https://jable.tv/search/?q=' + quote(query, safe=''),
                          silence=True)
    if getattr(listing, 'islist', None) is None:
        raise RuntimeError('Jable 未返回列表（站点不可达或被拦截）')
    links = getattr(listing, 'links', None) or []
    descriptions = getattr(listing, 'linkDescriptions', None) or []
    try:
        thumbnails = listing.getThumbnails() or []
    except Exception:
        thumbnails = []
    results = [{'url': url,
                'title': descriptions[i] if i < len(descriptions) else '',
                'thumbnail': thumbnails[i] if i < len(thumbnails) else '',
                'duration': '',
                'code': _code_from_slug(url)}
               for i, url in enumerate(links)]
    total = getattr(listing, 'totalLinks', 0) or len(results)
    return results, total


def _search_missav(query):
    from uav_downloader.sites.missav import SiteMissAV
    videos = SiteMissAV.search(query, 'cn') or []
    results = [{'url': video.get('url', ''),
                'title': video.get('title', ''),
                'thumbnail': video.get('thumbnail', ''),
                'duration': video.get('duration', ''),
                'code': _missav_code(video.get('url', ''))}
               for video in videos]
    return results, len(results)


def _search_supjav(query):
    from uav_downloader.sites.supjav import SupJavBrowser
    videos = SupJavBrowser.search(query) or []
    results = [{'url': video.get('url', ''),
                'title': video.get('title', ''),
                'thumbnail': video.get('thumbnail', ''),
                'duration': video.get('duration', ''),
                'code': _code_from_title(video.get('title', ''))}
               for video in videos]
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
                        'in_library': bool(code) and code in known,
                        'in_queue': url.rstrip('/') + '/' in queued})
    return {'results': results, 'total': total, 'error': None}

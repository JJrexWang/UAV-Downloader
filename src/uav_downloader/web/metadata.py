"""番号 metadata lookup: jav321 first, avbase second.

Parsing patterns are ported from the user's proven xxxmovie-rename-preview
scrapers (scrape_jav321.py / scrape_avbase.py):

- jav321: ``https://www.jav321.com/video/<prefix><5-digit number><suffix>``
  (lowercase); title from ``<h3>...<small>``, cast from the ``出演者 : ...``
  field up to ``メーカー :``.
- avbase: ``https://www.avbase.net/works/<CODE>``; title/casts from the
  ``__NEXT_DATA__`` JSON blob (``props.pageProps.work``).

Actress Chinese names resolve through ``data/actress_cn.csv`` (exact JP name
match).  CSV rows carry a confidence column: ``low`` rows are
transliterations, surfaced via ``actress_cn_low`` so callers can grade them
down.  Successful hits are cached in ``<state>/metadata_cache.json``.
Every network/parse failure degrades to ``None`` fields — never raises.
"""
from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import re
import threading
import urllib.error
import urllib.request

_UA = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
_TIMEOUT = 12
_lock = threading.Lock()
_map_cache = None
_hit_cache = None

EMPTY = {'actress_jp': None, 'actress_cn': None, 'actress_cn_low': False,
         'casts_jp': [], 'casts_cn': [], 'title': None, 'source': None}


def state_dir():
    return os.environ.get('UAV_WEB_STATE_DIR', '/state')


def _cache_path():
    return Path(state_dir()) / 'metadata_cache.json'


def actress_map():
    """JP name -> (CN name, confidence) from the bundled CSV (688 rows)."""
    global _map_cache
    if _map_cache is None:
        table = {}
        path = Path(__file__).parent / 'data' / 'actress_cn.csv'
        try:
            with open(path, encoding='utf-8-sig', newline='') as stream:
                for row in csv.reader(stream):
                    if len(row) >= 3 and row[0] and row[0] != '日文名':
                        table[row[0].strip()] = (row[1].strip(), row[2].strip().lower())
        except OSError:
            table = {}
        _map_cache = table
    return _map_cache


def actress_cn_for(jp_name):
    """(cn, low_confidence) for an exact JP name, else (None, False)."""
    if not jp_name:
        return None, False
    hit = actress_map().get(jp_name.strip())
    if not hit:
        return None, False
    return hit[0], hit[1] == 'low'


def _load_hits():
    global _hit_cache
    if _hit_cache is None:
        try:
            data = json.loads(_cache_path().read_text(encoding='utf-8'))
            _hit_cache = data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            _hit_cache = {}
    return _hit_cache


def _save_hits():
    try:
        path = _cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix('.tmp')
        temp.write_text(json.dumps(_hit_cache, ensure_ascii=False), encoding='utf-8')
        os.replace(temp, path)
    except OSError:
        pass


def _fetch(url):
    request = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        return response.read().decode('utf-8', 'ignore')


def _clean_title(title, casts):
    """DMM-style titles often trail the actress names; strip exact tails."""
    text = (title or '').strip()
    changed = True
    while changed:
        changed = False
        for name in casts:
            if name and text.endswith(name):
                text = text[:-len(name)].rstrip(' 　').strip()
                changed = True
    return text


def _jav321_url_code(code):
    match = re.fullmatch(r'([A-Z]+)-(\d+)([A-Z]*)', code.upper())
    if not match:
        return None
    return (match.group(1) + f'{int(match.group(2)):05d}' + match.group(3)).lower()


def parse_jav321(html):
    """(title, casts) from a jav321 video page, or None."""
    if not html:
        return None
    h3 = re.search(r'<h3>(.*?)<small>', html, re.S)
    if not h3:
        return None
    title = re.sub(r'<[^>]+>', '', h3.group(1)).strip()
    casts = []
    import html as _html
    text = _html.unescape(re.sub(r'<[^>]+>', ' ', html))
    cast_match = re.search(r'出演者\s*:\s*(.*?)メーカー\s*:', text, re.S)
    if cast_match:
        raw = ' '.join(cast_match.group(1).split())
        casts = [c for c in re.split(r'[\s,、]+', raw)
                 if c and '&' not in c and ';' not in c]
    if not title:
        return None
    return _clean_title(title, casts), casts


def parse_avbase(html):
    """(title, casts) from an avbase work page's __NEXT_DATA__, or None."""
    if not html:
        return None
    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        html, re.S)
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
        work = data['props']['pageProps'].get('work') or {}
        if not work.get('work_id'):
            return None
        casts = [c['actor']['name'] for c in work.get('casts', []) if c.get('actor')]
        title = work.get('title', '')
    except (ValueError, KeyError, TypeError, AttributeError):
        return None
    if not title:
        return None
    return _clean_title(title, casts), casts


def _try_jav321(code):
    url_code = _jav321_url_code(code)
    if not url_code:
        return None
    try:
        parsed = parse_jav321(_fetch(f'https://www.jav321.com/video/{url_code}'))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return ('jav321', parsed) if parsed else None


def _try_avbase(code):
    try:
        parsed = parse_avbase(_fetch(f'https://www.avbase.net/works/{code}'))
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return ('avbase', parsed) if parsed else None


def cached_lookup(code):
    """Cached metadata for *code*, or None — never touches the network."""
    code = (code or '').strip().upper()
    if not code:
        return None
    with _lock:
        cached = _load_hits().get(code)
    return dict(cached) if cached else None


def lookup(code):
    """Metadata for *code*; missing fields are None, never raises."""
    code = (code or '').strip().upper()
    if not code:
        return dict(EMPTY)
    with _lock:
        cached = _load_hits().get(code)
    if cached:
        return dict(cached)
    found = _try_jav321(code) or _try_avbase(code)
    if not found:
        return dict(EMPTY)
    source, (title, casts) = found
    resolved = [actress_cn_for(name) for name in casts]
    casts_cn = [cn for cn, _low in resolved]
    result = {
        'actress_jp': casts[0] if casts else None,
        'actress_cn': casts_cn[0] if casts_cn else None,
        'actress_cn_low': bool(resolved and resolved[0][1] and resolved[0][0]),
        'casts_jp': casts,
        'casts_cn': casts_cn,
        'title': title,
        'source': source,
    }
    with _lock:
        _load_hits()[code] = result
        _save_hits()
    return dict(result)

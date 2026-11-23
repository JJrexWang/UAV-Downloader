"""The user's fixed naming standard for organised video files.

Main name: ``番号-女优中文名（日文名）-中文片名`` — e.g.
``SNOS-283-楓富愛（楓ふうあ）-雨天出現在自助洗衣店….mp4``.

Rules (ported from the proven xxxmovie-rename-preview tooling):
- full filename <= 255 bytes (UTF-8); only the title is ever shortened;
- generated punctuation is half-width, except the full-width parentheses
  around the Japanese actress name, which are part of the standard itself;
- multi-part suffixes (-cd1 / -CD1 / part1 ...) survive at the end of the
  stem, together with the version tails (UC/CH/SUB/C/U) the old tooling kept.
"""
from __future__ import annotations

import re

MAX_BYTES = 255

_FW2HW = {}
for _i in range(0xFF01, 0xFF5F):
    _FW2HW[chr(_i)] = chr(_i - 0xFEE0)
_FW2HW.update({
    '、': ',', '。': '.', '・': ',', '·': ',', '「': "'", '」': "'",
    '『': "'", '』': "'", '“': "'", '”': "'", '‘': "'", '’': "'",
    '《': "'", '》': "'", '〈': "'", '〉': "'", '：': '-', '；': ';',
    '？': '', '！': '!', '～': '~', '—': '-', '―': '-', '–': '-',
    '…': '...', '‥': '..', '　': ' ', '【': '[', '】': ']',
    '｟': '(', '｠': ')', '＼': '-', '／': '-',
})
_ILLEGAL = set('\\/:*?"<>|')


def to_hw(text):
    """Full-width -> half-width normalisation; filesystem-illegal chars dropped."""
    out = []
    for ch in text or '':
        for c in _FW2HW.get(ch, ch):
            if c in _ILLEGAL:
                c = '-' if c in ':/' else ''
            if not c or ord(c) < 0x20 or ord(c) == 0x7F:
                continue
            out.append(c)
    return ''.join(out)


def blen(text):
    return len((text or '').encode('utf-8'))


def _truncate_title(title, budget_bytes):
    if budget_bytes <= 0:
        return ''
    text = title
    while text and blen(text) > budget_bytes:
        text = text[:-1]
    return text.rstrip(' .,;!~-')


_PART_TAIL = re.compile(
    r'(?:[-_ ]?(?:cd|part|pt|disc|disk|vol)\s*[-_ ]?(\d{1,2}|[a-d])'
    r'|[-_]([0-9]{1,2}|[a-d]))$', re.I)
_VER_TAIL = re.compile(r'[-_ ]?(uc|ch|sub|c|u|pl|ps)$', re.I)


def part_suffix(stem):
    """Preserved multi-part/version tail of an original stem, e.g. ``-CD1``.

    The whole matched tail is kept (``-cd1`` -> ``-CD1``, ``part1`` ->
    ``-PART1``), normalised to upper case without inner separators.
    """
    tail = ''
    match = _PART_TAIL.search(stem or '')
    rest = stem[:match.start()] if match else (stem or '')
    if match:
        text = re.sub(r'[-_ ]+', '', match.group(0)).upper()
        if text:
            tail = '-' + text
    ver = _VER_TAIL.search(rest)
    if ver:
        tail = '-' + ver.group(1).upper() + tail
    return tail


def actress_segment(actress_cn, actress_jp):
    """``中文名（日文名）`` — full-width parens are part of the standard."""
    cn = to_hw(re.sub(r'[()（）]', '', actress_cn or '')).strip()
    jp = to_hw(re.sub(r'[()（）]', '', actress_jp or '')).strip()
    if cn and jp and cn != jp:
        return f'{cn}（{jp}）'
    return cn or jp


def build_stem(code, actress_cn, actress_jp, title, suffix=''):
    """Compose a stem within the 255-byte cap (extension accounted by caller).

    Only the title is shortened: first its spaces are dropped, then it is
    truncated to the remaining byte budget.  Code, actress segment and the
    preserved suffix are never touched.
    """
    parts = [code]
    segment = actress_segment(actress_cn, actress_jp)
    if segment:
        parts.append(segment)
    clean_title = ' '.join(to_hw(title or '').split()).strip()
    stem = '-'.join(parts)
    if clean_title:
        stem += '-' + clean_title
    stem += suffix
    if blen(stem) <= MAX_BYTES:
        return stem
    squeezed = clean_title.replace(' ', '')
    stem = '-'.join(parts) + ('-' + squeezed if squeezed else '') + suffix
    if blen(stem) <= MAX_BYTES:
        return stem
    base = '-'.join(parts) + suffix
    budget = MAX_BYTES - blen(base) - 1  # one byte for the '-' before the title
    if budget < 0:
        return base
    trimmed = _truncate_title(squeezed, budget)
    return '-'.join(parts) + ('-' + trimmed if trimmed else '') + suffix


def build_name(code, actress_cn, actress_jp, title, ext, suffix=''):
    """Full filename (stem + ext) within the 255-byte cap."""
    stem = build_stem(code, actress_cn, actress_jp, title, suffix)
    while stem and blen(stem + ext) > MAX_BYTES:
        stem = stem[:-1]
    return stem + ext

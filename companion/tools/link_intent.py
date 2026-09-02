"""链接 / 读网页意图：有 URL 时偏置去调 MCP fetch。"""

from __future__ import annotations

import re

_URL_RE = re.compile(
    r"https?://[^\s<>\"'）\]】>]+",
    re.I,
)
# 尾部常见中文/标点粘连
_TRAIL_TRIM = re.compile(r"[，。！？；：、）】〉》\"'`]+$")


def extract_urls(text: str, *, limit: int = 5) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for m in _URL_RE.finditer(text or ""):
        url = _TRAIL_TRIM.sub("", m.group(0)).rstrip(".,;:!?)")
        if not url or url in seen:
            continue
        seen.add(url)
        found.append(url)
        if len(found) >= limit:
            break
    return found


def has_http_url(text: str) -> bool:
    return bool(extract_urls(text, limit=1))


def is_link_read_intent(text: str) -> bool:
    """有链接，或明确要打开/看看网页。"""
    raw = text or ""
    if has_http_url(raw):
        return True
    lower = raw.lower()
    cues = ("打开链接", "看下这个链接", "解析链接", "网页什么", "这个网站", "帮我看看这个")
    return any(c in raw or c in lower for c in cues)

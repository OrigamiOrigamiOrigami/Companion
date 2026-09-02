"""卡文本清洗：防注入短语 + 长度截断。"""

from __future__ import annotations

import re

_INJECTION = [
    re.compile(r"(?i)ignore\s+(all\s+)?previous\s+instructions"),
    re.compile(r"(?i)system\s*prompt"),
    re.compile(r"(?i)you\s+are\s+now\s+"),
]


def sanitize(text: str, max_bytes: int = 12000) -> str:
    cleaned = text or ""
    for pat in _INJECTION:
        cleaned = pat.sub("[filtered]", cleaned)
    raw = cleaned.encode("utf-8")
    if len(raw) > max_bytes:
        cleaned = raw[:max_bytes].decode("utf-8", errors="ignore")
    return cleaned

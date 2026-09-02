from __future__ import annotations

import json
import logging
import os
import re
import time
from typing import Any

logger = logging.getLogger("astrbot")

_NICK_RE = re.compile(r"(?:叫我|你可以叫我|喊我|称呼我)[：: ]?([^\s，。！!？?]{1,8})")
_AVOID_NAME_RE = re.compile(r"(?:别叫我|不要叫我|别喊我)[：: ]?([^\s，。！!？?]{1,8})")


def extract_anchors(text: str) -> list[tuple[str, str]]:
    """高置信偏好/称呼 → (key, value)。"""
    text = (text or "").strip()
    if not text:
        return []
    out: list[tuple[str, str]] = []
    for prefix in ("我喜欢", "我爱"):
        if prefix in text:
            val = text.split(prefix, 1)[1].strip(" 。！!？?，,")
            if 0 < len(val) <= 16:
                out.append(("likes", val[:16]))
            break
    for prefix in ("我讨厌", "我不爱", "不喜欢"):
        if prefix in text:
            val = text.split(prefix, 1)[1].strip(" 。！!？?，,")
            if 0 < len(val) <= 16:
                out.append(("dislikes", val[:16]))
            break
    m = _NICK_RE.search(text)
    if m:
        out.append(("nickname", m.group(1)[:8]))
    m = _AVOID_NAME_RE.search(text)
    if m:
        out.append(("avoid_name", m.group(1)[:8]))
    return out

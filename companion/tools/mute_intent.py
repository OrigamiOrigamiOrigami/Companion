from __future__ import annotations

import re

_MUTE_KW = (
    "禁言",
    "口球",
    "闭嘴",
    "塞口球",
    "mute",
    "ban他",
    "ban她",
    "ban掉",
    "封嘴",
    "消音",
)

_UNMUTE_KW = (
    "解除禁言",
    "取消禁言",
    "解禁",
    "放出来",
    "unmute",
    "解开禁言",
)

_DURATION_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(小时|分钟|分|秒)",
    re.I,
)


def is_mute_intent(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if is_unmute_intent(t):
        return True
    return any(k in t for k in _MUTE_KW)


def is_unmute_intent(text: str) -> bool:
    t = (text or "").strip().lower()
    return any(k in t for k in _UNMUTE_KW)


def parse_mute_duration_seconds(text: str, *, default: float = 60.0) -> float:
    """从话里抽禁言时长；没有则用 default。"""
    t = (text or "").strip()
    if not t:
        return float(default)
    if "半小时" in t or "半个小时" in t:
        return 30 * 60
    if "一小时" in t or "1小时" in t:
        return 3600
    m = _DURATION_RE.search(t)
    if m:
        n = float(m.group(1))
        unit = m.group(2)
        if unit == "小时":
            return n * 3600
        if unit in ("分钟", "分"):
            return n * 60
        return n
    # 「禁言一下」类：短默认
    if any(k in t for k in ("一下", "一会儿", "一会", "片刻")):
        return min(float(default), 60.0)
    return float(default)

"""在线感：打字延迟、深夜时段。"""

from __future__ import annotations

import random
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def now_local(tz_name: str = "Asia/Shanghai") -> datetime:
    try:
        return datetime.now(ZoneInfo(tz_name))
    except Exception:
        return datetime.now().astimezone()


def is_night_hours(cfg: dict[str, Any] | None = None, *, hour: int | None = None) -> bool:
    """默认凌晨 2:00–6:00（左闭右开）。"""
    presence = (cfg or {}).get("presence") or {}
    window = presence.get("night_hours") or [2, 6]
    start = int(window[0]) if len(window) >= 1 else 2
    end = int(window[1]) if len(window) >= 2 else 6
    h = int(hour) if hour is not None else now_local().hour
    if start <= end:
        return start <= h < end
    # 跨午夜
    return h >= start or h < end


def night_afk_roll(cfg: dict[str, Any] | None = None) -> bool:
    """深夜软唤醒时是否走挂机短句（硬 @ 一般仍走完整回复）。"""
    presence = (cfg or {}).get("presence") or {}
    if not is_night_hours(cfg):
        return False
    prob = float(presence.get("night_afk_prob", 0.35))
    return random.random() < max(0.0, min(1.0, prob))


def typing_delay_ms(
    bubbles: list[str],
    cfg: dict[str, Any] | None = None,
    *,
    night: bool | None = None,
) -> int:
    """按回复长度估算「看消息+打字」延迟（毫秒）。"""
    express = (cfg or {}).get("express") or {}
    raw = express.get("typing_delay_ms") or [1500, 3500]
    lo = int(raw[0]) if len(raw) >= 1 else 1500
    hi = int(raw[1]) if len(raw) >= 2 else 3500
    if lo > hi:
        lo, hi = hi, lo
    per_char = int(express.get("typing_per_char_ms") or 40)
    max_ms = int(express.get("typing_delay_max_ms") or 5500)
    text_len = sum(len(b or "") for b in (bubbles or []))
    base = random.uniform(float(lo), float(hi))
    delay = base + text_len * per_char
    if night is None:
        night = is_night_hours(cfg)
    if night:
        delay *= float(((cfg or {}).get("presence") or {}).get("night_delay_mult") or 1.35)
    return int(max(0, min(max_ms, delay)))


def night_prompt_hint() -> str:
    return (
        "【时段】现在是深夜/凌晨。语气可以更软、更困、更短；"
        "偶尔提一句想去网海里漂一会儿也可以，但对方硬喊你时仍要认真回。"
        "不要用白天那种拉满元气的长串刷屏。"
    )

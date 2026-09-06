"""群续聊 keep_going：确认词与窗口状态（纯规则，无 LLM）。"""

from __future__ import annotations

from typing import Any, Iterable

from .types import InnerState

DEFAULT_ACK_WORDS: tuple[str, ...] = (
    "嗯",
    "嗯嗯",
    "好",
    "好的",
    "好哦",
    "行",
    "ok",
    "OK",
    "收到",
    "懂了",
    "知道了",
    "1",
    "哈哈哈",
    "哈",
    "草",
    "dd",
)

# 这些 Decide reason 表示「唤醒开口」，发送成功后开新窗并清零已续次数
WAKE_OPEN_REASONS: frozenset[str] = frozenset(
    {
        "hard_mention",
        "soft_mention",
        "name_address",
        "night_afk",
    }
)


def is_keep_going_ack(text: str, words: Iterable[str] | None = None) -> bool:
    """整句 trim 后精确匹配（大小写不敏感）；空串视为确认（不续）。"""
    t = (text or "").strip()
    if not t:
        return True
    bag = tuple(words) if words is not None else DEFAULT_ACK_WORDS
    lower_bag = {w.casefold() for w in bag if w}
    return t.casefold() in lower_bag


def keep_going_cfg(config: dict[str, Any]) -> dict[str, Any]:
    g = config.get("group") or {}
    triggers = g.get("speech_triggers") or {}
    raw_words = g.get("keep_going_ack_words")
    if isinstance(raw_words, list) and raw_words:
        words: tuple[str, ...] = tuple(str(w) for w in raw_words if str(w).strip())
    else:
        words = DEFAULT_ACK_WORDS
    try:
        window_sec = max(5, int(g.get("keep_going_window_sec") or 60))
    except (TypeError, ValueError):
        window_sec = 60
    try:
        max_n = max(0, int(g.get("keep_going_max") or 1))
    except (TypeError, ValueError):
        max_n = 1
    return {
        "enabled": bool(triggers.get("keep_going", True)),
        "window_sec": window_sec,
        "max": max_n,
        "allow_tools": bool(g.get("keep_going_allow_tools", False)),
        "ack_words": words,
    }


def window_open(state: InnerState, *, now: float) -> bool:
    return float(state.conversation_window_until or 0) > now


def can_keep_going(state: InnerState, *, now: float, max_n: int) -> bool:
    if max_n <= 0:
        return False
    if not window_open(state, now=now):
        return False
    return int(state.keep_going_used or 0) < max_n


def open_window(state: InnerState, *, now: float, window_sec: int) -> None:
    state.conversation_window_until = now + float(window_sec)
    state.keep_going_used = 0


def after_keep_going_sent(
    state: InnerState,
    *,
    now: float,
    window_sec: int,
    max_n: int,
) -> None:
    state.keep_going_used = int(state.keep_going_used or 0) + 1
    if state.keep_going_used < max_n:
        state.conversation_window_until = now + float(window_sec)
    else:
        state.conversation_window_until = 0.0


def apply_after_outbound(
    state: InnerState,
    *,
    decision_reason: str,
    is_private: bool,
    now: float,
    window_sec: int,
    max_n: int,
) -> None:
    """群聊实际发出后：唤醒开窗；续聊则计数并按上限决定是否刷新窗。"""
    if is_private:
        return
    if decision_reason in WAKE_OPEN_REASONS:
        open_window(state, now=now, window_sec=window_sec)
        return
    if decision_reason == "keep_going":
        after_keep_going_sent(state, now=now, window_sec=window_sec, max_n=max_n)

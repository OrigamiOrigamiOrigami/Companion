"""回复 + @唤起 + 指令前缀 → 让位给其它插件，不跑 companion LLM。"""

from __future__ import annotations

import re
from typing import Any, Iterable


_AT_RUN = re.compile(r"^(?:@\S+\s*)+")


def strip_addressing(text: str, wake_words: Iterable[str] | None = None) -> str:
    """去掉句首 @某人 与唤醒词/称呼，留下可能的指令正文。"""
    t = (text or "").strip()
    if not t:
        return ""
    t = _AT_RUN.sub("", t).strip()
    words = [w for w in (wake_words or []) if w]
    for w in sorted(words, key=len, reverse=True):
        if not t.startswith(w):
            continue
        rest = t[len(w) :]
        if not rest:
            return ""
        if rest[0] in "，,。.!！？?、：:；; \t@":
            t = rest.lstrip("，,。.!！？?、：:；; \t")
            t = _AT_RUN.sub("", t).strip()
            break
        # 「飞行雪绒加速」粘连：唤醒词后直接跟汉字指令
        if "\u4e00" <= rest[0] <= "\u9fff" or rest[0].isalpha():
            t = rest.lstrip()
            break
    return t.strip()


def looks_like_reply_command(text: str, keywords: Iterable[str] | None) -> bool:
    """剩余正文是否以让位指令词开头（含「加速 8」）。"""
    body = (text or "").strip()
    if not body:
        return False
    keys = [str(k).strip() for k in (keywords or []) if str(k).strip()]
    if not keys:
        return False
    lower = body.lower()
    for k in sorted(keys, key=len, reverse=True):
        kl = k.lower()
        if lower == kl:
            return True
        if lower.startswith(kl + " "):
            return True
        # 无空格参数：加速8（少见，仍认）
        if lower.startswith(kl) and len(body) > len(k):
            nxt = body[len(k)]
            if nxt.isdigit() or nxt in ".-":
                return True
    return False


def should_silence_reply_at_command(
    *,
    is_reply: bool,
    woken: bool,
    text: str,
    wake_words: Iterable[str] | None,
    config: dict[str, Any],
) -> bool:
    decide_cfg = config.get("decide") or {}
    if not bool(decide_cfg.get("silence_reply_at_commands", True)):
        return False
    if not is_reply or not woken:
        return False
    residual = strip_addressing(text, wake_words)
    keywords = decide_cfg.get("reply_at_command_keywords") or []
    return looks_like_reply_command(residual, keywords)

from __future__ import annotations

import re

_COMIC_ID_RE = re.compile(r"(?:jm|JM)?(\d{5,})")
# QQ @：@昵称(123456) / @123456；勿把 QQ 当本子 ID
_QQ_MENTION_RE = re.compile(r"@[^()\s]{0,64}\(\d{5,}\)|\@\d{5,}")
_JM_KW = ("jm", "禁漫", "本子", "jmcomic")
_SEARCH_KW = ("搜", "搜索", "找", "tag", "标签")


def _strip_qq_mentions(text: str) -> str:
    return _QQ_MENTION_RE.sub(" ", text or "")


def extract_comic_id(text: str) -> str | None:
    """从话里抽本子 ID；忽略 @昵称(QQ) 里的数字。"""
    cleaned = _strip_qq_mentions(text or "")
    m = _COMIC_ID_RE.search(cleaned)
    return m.group(1) if m else None


def _has_jm_keywords(text: str) -> bool:
    lower = (text or "").lower()
    return any(k in lower for k in _JM_KW)


def is_jm_context(text: str) -> bool:
    """有禁漫语境才算；禁言/提醒里的长数字不算。"""
    from .mute_intent import is_mute_intent
    from .reminder_intent import is_reminder_intent

    raw = text or ""
    if is_mute_intent(raw) or is_reminder_intent(raw):
        return _has_jm_keywords(raw)
    if extract_comic_id(raw):
        return True
    return _has_jm_keywords(raw)


def is_jm_search_intent(text: str) -> bool:
    raw = text or ""
    if not is_jm_context(raw):
        return False
    return any(k in raw for k in _SEARCH_KW)


def is_jm_download_intent(text: str) -> bool:
    from .mute_intent import is_mute_intent
    from .reminder_intent import is_reminder_intent

    raw = text or ""
    if is_mute_intent(raw) or is_reminder_intent(raw):
        return False
    return extract_comic_id(raw) is not None

from __future__ import annotations

import re
import time
from typing import Optional

from astrbot.api.all import At
from astrbot.api.event import AstrMessageEvent

from .types import Perception
from .media import extract_media

_REST = ("晚安", "睡了", "别吵", "勿扰", "休息了")
# NBSP / 窄空格等 → 普通空格，避免拉丁专名被切开
_SPACE_ODD = re.compile(r"[\u00a0\u2000-\u200b\u202f\u205f\u3000]+")


def perceive(
    event: AstrMessageEvent,
    *,
    trigger: str,
    wake_words: list[str],
    rest_keywords: Optional[list[str]] = None,
) -> Perception:
    text = _normalize_text(_text(event))
    gid = _group_id(event)
    uid = str(event.get_sender_id())
    sender_name = _sender_name(event)
    is_private = not bool(gid)
    hard = trigger == "hard_mention" or _hard_at(event)
    soft = (not hard) and any(w and w in text for w in (wake_words or []))
    name_addressed = (not hard) and _name_addressed(text, wake_words or [])
    rest = any(w in text for w in (rest_keywords or list(_REST)))
    channel = "private" if is_private else f"group:{gid}"
    media = extract_media(event)
    return Perception(
        trigger=trigger,
        user_id=uid,
        group_id=gid,
        channel=channel,
        text=text,
        sender_name=sender_name,
        is_private=is_private,
        hard_mentioned=hard,
        soft_mentioned=soft or name_addressed,
        name_addressed=name_addressed,
        rest_keyword=rest,
        image_count=media.image_count,
        face_count=media.face_count,
        reply_image_count=media.reply_image_count,
        record_count=media.record_count,
        media_note=media.describe(),
        raw={"ts": time.time()},
    )


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    return _SPACE_ODD.sub(" ", text).strip()


def _name_addressed(text: str, wake_words: list[str]) -> bool:
    """句首唤醒词点名（可跟标点/空格），视为当面叫人。"""
    t = (text or "").lstrip()
    if not t:
        return False
    for w in sorted((x for x in wake_words if x), key=len, reverse=True):
        if not t.startswith(w):
            continue
        rest = t[len(w) :]
        if not rest:
            return True
        # 「小爱」「小爱，」「小爱你觉得」都算点名；避免误伤「小爱好玩的店」中嵌套——仅句首
        if rest[0] in "，,。.!！？?、：:；; \t":
            return True
        # 紧跟汉字/字母继续问话
        if "\u4e00" <= rest[0] <= "\u9fff" or rest[0].isalpha():
            return True
    return False


def _sender_name(event: AstrMessageEvent) -> str:
    """群聊优先用群名片（card），否则 QQ 昵称。"""
    try:
        msg = getattr(event, "message_obj", None)
        raw = getattr(msg, "raw_message", None) if msg else None
        sender = _raw_sender(raw)
        if sender:
            card = str(sender.get("card") or "").strip()
            if card:
                return card[:32]
            nick = str(sender.get("nickname") or "").strip()
            if nick:
                return nick[:32]
    except Exception:
        pass
    try:
        if hasattr(event, "get_sender_name"):
            name = (event.get_sender_name() or "").strip()
            if name:
                return name[:32]
    except Exception:
        pass
    return ""


def _raw_sender(raw: object) -> dict:
    if raw is None:
        return {}
    try:
        if isinstance(raw, dict):
            s = raw.get("sender") or {}
            return s if isinstance(s, dict) else {}
        if hasattr(raw, "get"):
            s = raw.get("sender")  # type: ignore[attr-defined]
            if isinstance(s, dict):
                return s
        s = getattr(raw, "sender", None)
        if isinstance(s, dict):
            return s
    except Exception:
        pass
    return {}


def _text(event: AstrMessageEvent) -> str:
    try:
        if getattr(event, "message_str", None):
            return event.message_str.strip()
        if hasattr(event, "get_message_str"):
            return (event.get_message_str() or "").strip()
    except Exception:
        pass
    return ""


def _group_id(event: AstrMessageEvent) -> Optional[str]:
    try:
        if hasattr(event, "get_group_id"):
            gid = event.get_group_id()
            return str(gid) if gid else None
        msg = getattr(event, "message_obj", None)
        gid = getattr(msg, "group_id", None) if msg else None
        return str(gid) if gid else None
    except Exception:
        return None


def _hard_at(event: AstrMessageEvent) -> bool:
    try:
        self_id = getattr(event.message_obj, "self_id", None)
        for msg in event.get_messages() or []:
            if self_id and isinstance(msg, At) and str(getattr(msg, "qq", "")) == str(self_id):
                return True
    except Exception:
        pass
    return False

from __future__ import annotations

import logging
from typing import Any

from astrbot.api.all import At, Reply
from astrbot.api.event import AstrMessageEvent
from astrbot.core.config import AstrBotConfig
from astrbot.core.star.filter.custom_filter import CustomFilter

from ..harness.poke import is_poke_to_bot

logger = logging.getLogger("astrbot")


def _is_private(event: AstrMessageEvent) -> bool:
    try:
        if hasattr(event, "get_group_id"):
            return not bool(event.get_group_id())
        msg = getattr(event, "message_obj", None)
        return not bool(getattr(msg, "group_id", None)) if msg else False
    except Exception:
        return False


def _plain_text(event: AstrMessageEvent) -> str:
    try:
        if getattr(event, "message_str", None):
            return event.message_str.strip()
        if hasattr(event, "get_message_str"):
            return (event.get_message_str() or "").strip()
    except Exception:
        pass
    return ""


def _has_hard_at(event: AstrMessageEvent) -> bool:
    try:
        self_id = getattr(event.message_obj, "self_id", None)
        for msg in event.get_messages() or []:
            if (
                self_id
                and isinstance(msg, At)
                and str(getattr(msg, "qq", "")) == str(self_id)
            ):
                return True
    except Exception:
        pass
    return False


class AtFilter(CustomFilter):
    def __init__(self, main: Any):
        self.main = main

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        try:
            if _has_hard_at(event):
                return True
            messages = event.get_messages() or []
            for msg in messages:
                if isinstance(msg, Reply):
                    return False
            return False
        except Exception as e:
            logger.error("companion At 过滤器: %s", e)
            return False


class PokeFilter(CustomFilter):
    """Bot 被戳一戳（QQ notice poke）。"""

    def __init__(self, main: Any):
        self.main = main

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        try:
            return is_poke_to_bot(event)
        except Exception as e:
            logger.error("companion 戳一戳过滤器: %s", e)
            return False


class PrivateFilter(CustomFilter):
    def __init__(self, main: Any):
        self.main = main

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        try:
            if is_poke_to_bot(event):
                return False
            return _is_private(event)
        except Exception as e:
            logger.error("companion 私聊过滤器: %s", e)
            return False


class GroupObserveFilter(CustomFilter):
    """群消息旁听：硬 @ 走 AtFilter；其余群消息均入库观察，不要求唤醒词。"""

    def __init__(self, main: Any):
        self.main = main

    def filter(self, event: AstrMessageEvent, cfg: AstrBotConfig) -> bool:
        try:
            if _is_private(event):
                return False
            if _has_hard_at(event):
                return False
            return bool(_plain_text(event))
        except Exception as e:
            logger.error("companion 群观察过滤器: %s", e)
            return False

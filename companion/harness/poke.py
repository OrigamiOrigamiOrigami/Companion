from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass

from astrbot.api.event import AstrMessageEvent

from .poke_plan import (
    POKE_MODE_ANTIPOKE,
    POKE_MODE_LLM,
    POKE_MODE_SPEECH,
    POKE_MODE_SPEECH_POKE,
    PokePlan,
    normalize_poke_weights,
    pick_poke_mode,
    pick_poke_reply,
    pick_poke_sticker_intent,
    plan_poke_reaction,
)

logger = logging.getLogger("astrbot")

__all__ = [
    "POKE_MODE_ANTIPOKE",
    "POKE_MODE_LLM",
    "POKE_MODE_SPEECH",
    "POKE_MODE_SPEECH_POKE",
    "PokeInfo",
    "PokePlan",
    "is_poke_to_bot",
    "normalize_poke_weights",
    "parse_poke",
    "pick_poke_mode",
    "pick_poke_reply",
    "pick_poke_sticker_intent",
    "plan_poke_reaction",
    "send_poke_to_user",
    "send_poke_with_pause",
    "send_pokes_with_pause",
]


@dataclass
class PokeInfo:
    sender_id: str
    target_id: str
    group_id: str | None
    to_self: bool


def _poke_component():
    try:
        from astrbot.core.message.components import Poke

        return Poke
    except ImportError:
        return None


def _self_id(event: AstrMessageEvent) -> str:
    try:
        sid = event.get_self_id()
        if sid:
            return str(sid)
    except Exception:
        pass
    msg = getattr(event, "message_obj", None)
    sid = getattr(msg, "self_id", None) if msg else None
    return str(sid) if sid else ""


def parse_poke(event: AstrMessageEvent) -> PokeInfo | None:
    """解析戳一戳：仅当消息链含 Poke 段或 raw notice 为 poke 时返回。"""
    Poke = _poke_component()
    target_id = ""
    if Poke is not None:
        for msg in event.get_messages() or []:
            if isinstance(msg, Poke):
                target_id = str(getattr(msg, "qq", "") or "")
                break
    raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
    if isinstance(raw, dict) and raw.get("sub_type") == "poke":
        target_id = target_id or str(raw.get("target_id") or "")
    if not target_id:
        return None
    sender_id = str(event.get_sender_id() or "")
    gid = _group_id(event)
    self_id = _self_id(event)
    return PokeInfo(
        sender_id=sender_id,
        target_id=target_id,
        group_id=gid,
        to_self=bool(self_id and target_id == self_id),
    )


def is_poke_to_bot(event: AstrMessageEvent) -> bool:
    info = parse_poke(event)
    return bool(info and info.to_self)


def _group_id(event: AstrMessageEvent) -> str | None:
    try:
        if hasattr(event, "get_group_id"):
            gid = event.get_group_id()
            return str(gid) if gid else None
        msg = getattr(event, "message_obj", None)
        gid = getattr(msg, "group_id", None) if msg else None
        return str(gid) if gid else None
    except Exception:
        return None


async def send_poke_to_user(
    event: AstrMessageEvent,
    *,
    user_id: str,
    group_id: str | None = None,
) -> bool:
    """向用户发送 QQ 戳一戳（仅 aiocqhttp / OneBot）。"""
    if not user_id:
        return False
    try:
        if event.get_platform_name() != "aiocqhttp":
            return False
    except Exception:
        return False
    bot = getattr(event, "bot", None)
    if bot is None:
        return False
    try:
        uid = int(user_id)
        if group_id:
            await bot.call_action("group_poke", group_id=int(group_id), user_id=uid)
        else:
            await bot.call_action("friend_poke", user_id=uid)
        logger.info("companion 戳回 用户=%s 群=%s", user_id, group_id or "-")
        return True
    except Exception as e:
        logger.warning("companion 戳回失败 用户=%s: %s", user_id, e)
        return False


async def send_poke_with_pause(
    event: AstrMessageEvent,
    *,
    user_id: str,
    group_id: str | None = None,
    delay_ms: tuple[int, int] = (400, 1200),
) -> bool:
    lo, hi = delay_ms
    if lo > 0 or hi > 0:
        if lo > hi:
            lo, hi = hi, lo
        await asyncio.sleep(random.uniform(lo, hi) / 1000.0)
    return await send_poke_to_user(event, user_id=user_id, group_id=group_id)


async def send_pokes_with_pause(
    event: AstrMessageEvent,
    *,
    user_id: str,
    group_id: str | None = None,
    times: int = 1,
    delay_ms: tuple[int, int] = (400, 1200),
) -> int:
    """连戳 times 次；返回成功次数。"""
    n = max(0, int(times))
    ok = 0
    for _ in range(n):
        if await send_poke_with_pause(
            event, user_id=user_id, group_id=group_id, delay_ms=delay_ms
        ):
            ok += 1
    return ok

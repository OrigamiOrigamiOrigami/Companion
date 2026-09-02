from __future__ import annotations

import logging
from typing import Any

from ...canned import pick_tool_ok
from ..ack import ToolExecResult, parse_tool_ack, tool_failed


logger = logging.getLogger("astrbot")

# metadata.yaml 里的 name 字段
PLUGIN_NAMES = {
    "music": "astrbot_plugin_music",
    "image_search": "image_search",
    "jmcomic": "jmcomic",
    "setu": "setu",
}


def resolve_plugin(star_name: str) -> Any | None:
    try:
        from astrbot.core.star.star import star_map
    except ImportError:
        return None

    for md in star_map.values():
        if md.name != star_name:
            continue
        if not md.activated:
            logger.debug("companion 适配器：插件未激活 %s", star_name)
            return None
        inst = md.star_cls
        if inst is None:
            return None
        return inst
    return None


def command_result_text(result: Any, *, ok: str | None = None) -> ToolExecResult:
    """把 AstrBot CommandResult 收成给 LLM 看的短文本 + 是否已 event.send。"""
    if ok is None:
        ok = pick_tool_ok()
    if result is None:
        return ToolExecResult(text=ok, plugin_sent=False, plugin_raw="（插件返回 None）")
    try:
        from astrbot.api.all import CommandResult
    except ImportError:
        CommandResult = None  # type: ignore

    if CommandResult is not None and isinstance(result, CommandResult):
        if hasattr(result, "get_plain_text"):
            plain = (result.get_plain_text() or "").strip()
            if plain:
                return ToolExecResult(text=plain[:2000], plugin_sent=False, plugin_raw=plain[:2000])
        chain = getattr(result, "chain", None) or []
        if chain:
            parts: list[str] = []
            for seg in chain:
                text = getattr(seg, "text", None)
                if text:
                    parts.append(str(text))
            if parts:
                body = "\n".join(parts)[:2000]
                return ToolExecResult(text=body, plugin_sent=False, plugin_raw=body)
        # 空 chain = 插件已自行 event.send（如 setu 发图）
        return ToolExecResult(
            text=ok,
            plugin_sent=True,
            plugin_raw="（空 chain：插件已通过 event.send 发出，无文本回执）",
        )
    if isinstance(result, str):
        body = result[:2000]
        return ToolExecResult(text=body, plugin_sent=not tool_failed(body), plugin_raw=body)
    return ToolExecResult(text=ok, plugin_sent=False, plugin_raw=str(result)[:2000])

from __future__ import annotations

from ..voice.intent import is_song_tool_intent, is_voice_force_intent
from .types import Decision, InnerState, Perception, ToolPlan


def plan_tool_order(
    perception: Perception,
    state: InnerState,
    decision: Decision,
    config: dict,
) -> ToolPlan:
    """工具面默认全开；是否调用由模型理解。"""
    if not decision.allow_tools:
        return ToolPlan(order="chat", reason="tools_disabled")

    tools_cfg = config.get("tools") or {}
    if not tools_cfg.get("enabled", True):
        return ToolPlan(order="chat", reason="tools_off")

    text_raw = perception.text or ""
    if is_voice_force_intent(text_raw) and not is_song_tool_intent(text_raw):
        return ToolPlan(order="chat", reason="voice_speak_no_tools")

    return ToolPlan(
        order="chat",
        reason="model_decides",
        hint="工具已开放，按对方意图决定是否调用。",
    )

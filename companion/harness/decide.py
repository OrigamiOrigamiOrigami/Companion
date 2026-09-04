from __future__ import annotations

from typing import Any

from .presence import night_afk_roll
from .types import Decision, InnerState, Perception


def decide(
    perception: Perception,
    state: InnerState,
    config: dict[str, Any],
    *,
    group_enabled: bool = True,
) -> Decision:
    """
    规则优先的开口决策。

    唤起：硬 @ / 私聊 / soft_mention（含句首唤醒词）。
    ``speech_triggers.keep_going``（续聊）本阶段故意 no-op——无唤醒词不接话，
    避免模型把「懂了」接成续聊；见 CONTEXT.md。
    """
    if perception.rest_keyword and not perception.hard_mentioned:
        return Decision("SILENCE", "rest_gate")
    if (not perception.is_private) and (not group_enabled):
        return Decision("SILENCE", "group_disabled")
    if perception.hard_mentioned or perception.trigger == "hard_mention":
        return Decision("FULL", "hard_mention", allow_tools=True)
    if perception.is_private or perception.trigger == "private":
        return Decision("FULL", "private", allow_tools=True)

    triggers = (config.get("group") or {}).get("speech_triggers") or {}
    # keep_going: reserved / no-op（不读 triggers.keep_going）
    if perception.soft_mentioned and triggers.get("soft_mention", True):
        hard_always = bool(((config.get("presence") or {}).get("night_hard_always_llm", True)))
        treated_hard = perception.hard_mentioned or perception.name_addressed
        if (not hard_always or not treated_hard) and night_afk_roll(config):
            return Decision("SHORT", "night_afk", allow_tools=False)
        reason = "name_address" if perception.name_addressed else "soft_mention"
        return Decision("FULL", reason, allow_tools=True)

    prior = (config.get("group") or {}).get("silence_prior", "mid")
    return Decision("SILENCE", f"default_silence:{prior}")

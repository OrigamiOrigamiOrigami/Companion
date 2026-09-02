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
    if perception.rest_keyword and not perception.hard_mentioned:
        return Decision("SILENCE", "rest_gate")
    if (not perception.is_private) and (not group_enabled):
        return Decision("SILENCE", "group_disabled")
    if perception.hard_mentioned or perception.trigger == "hard_mention":
        return Decision("FULL", "hard_mention", allow_tools=True)
    if perception.is_private or perception.trigger == "private":
        return Decision("FULL", "private", allow_tools=True)
    triggers = (config.get("group") or {}).get("speech_triggers") or {}
    if perception.soft_mentioned and triggers.get("soft_mention", True):
        hard_always = bool(((config.get("presence") or {}).get("night_hard_always_llm", True)))
        treated_hard = perception.hard_mentioned or perception.name_addressed
        if (not hard_always or not treated_hard) and night_afk_roll(config):
            return Decision("SHORT", "night_afk", allow_tools=False)
        reason = "name_address" if perception.name_addressed else "soft_mention"
        return Decision("FULL", reason, allow_tools=True)
    prior = (config.get("group") or {}).get("silence_prior", "mid")
    return Decision("SILENCE", f"default_silence:{prior}")

from __future__ import annotations

from typing import Any

from .parser_links import looks_like_parser_share
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

    私聊里若像 astrbot_plugin_parser 会解析的分享链接，默认 SILENCE，
    把舞台让给解析插件（``decide.silence_parser_links``）。
    """
    if perception.rest_keyword and not perception.hard_mentioned:
        return Decision("SILENCE", "rest_gate")
    if (not perception.is_private) and (not group_enabled):
        return Decision("SILENCE", "group_disabled")
    if perception.hard_mentioned or perception.trigger == "hard_mention":
        return Decision("FULL", "hard_mention", allow_tools=True)

    decide_cfg = config.get("decide") or {}
    private_like = perception.is_private or perception.trigger == "private"
    if (
        private_like
        and bool(decide_cfg.get("silence_parser_links", True))
        and looks_like_parser_share(perception.text)
    ):
        return Decision("SILENCE", "parser_link")

    if private_like:
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

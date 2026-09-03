from __future__ import annotations

import re

from ..canned import PREFACE_EXAMPLES
from ..tools.jm_intent import is_jm_download_intent
from ..tools.link_intent import is_link_read_intent
from ..tools.mention_intent import is_mention_intent
from ..tools.mute_intent import is_mute_intent, is_unmute_intent
from ..tools.reminder_intent import is_reminder_intent
from ..tools.setu_intent import is_setu_intent
from ..voice.intent import is_song_tool_intent, is_voice_force_intent
from .types import Decision, InnerState, Perception, ToolPlan

_JM_KW = ("jm", "禁漫", "本子", "jmcomic")
_SEARCH_KW = ("搜", "查", "搜索", "下载", "识图", "找图", "点歌", "放歌", "播放")

# 所有工具统一三步；前置短句只表示「已开工」，结果等 ACK
_TOOL_CHAIN = (
    "【节奏·三步】① 调工具时可同轮带 1 句极短前置（如 "
    + PREFACE_EXAMPLES
    + "「好，正在下载」），只说已开始，禁止宣称已发出/已办妥；"
    "② 等工具真实 ACK；③ 再根据 ACK 口语收尾。ok=false 如实说失败。"
)


def plan_tool_order(
    perception: Perception,
    state: InnerState,
    decision: Decision,
    config: dict,
) -> ToolPlan:
    """决定本回合：走工具三步链 / 纯聊天。"""
    if not decision.allow_tools:
        return ToolPlan(order="chat", reason="tools_disabled")

    tools_cfg = config.get("tools") or {}
    if not tools_cfg.get("enabled", True):
        return ToolPlan(order="chat", reason="tools_off")

    text_raw = perception.text or ""
    # 「用语音说xxx」默认禁工具，避免把要念的句子当成歌名/搜旧话题
    if is_voice_force_intent(text_raw) and not is_song_tool_intent(text_raw):
        return ToolPlan(order="chat", reason="voice_speak_no_tools")

    text = text_raw.lower()
    if not text and not perception.has_image:
        return ToolPlan(order="chat", reason="no_clear_intent")

    # 禁言/提醒优先于「长数字=本子 ID」的慢路径，避免 @QQ 误进 jmcomic/setu
    if is_reminder_intent(perception.text or ""):
        return ToolPlan(
            order="tool_first",
            reason="reminder",
            hint=(
                _TOOL_CHAIN
                + "本回合先调 schedule_reminder；ACK 后再确认「记下了、大概多久后喊你」。"
                "只处理提醒，勿调发图/下载。"
            ),
        )

    if is_mute_intent(perception.text or ""):
        if is_unmute_intent(perception.text or ""):
            return ToolPlan(
                order="tool_first",
                reason="mute",
                hint=_TOOL_CHAIN + "先调 unmute_group_member。只处理解禁，勿调发图/下载。",
            )
        return ToolPlan(
            order="tool_first",
            reason="mute",
            hint=_TOOL_CHAIN + "先调 mute_group_member。只处理禁言，勿调 setu/jmcomic。",
        )

    if is_mention_intent(perception.text or ""):
        return ToolPlan(
            order="tool_first",
            reason="mention",
            hint=(
                _TOOL_CHAIN
                + "只调一次 mention_group_member；ACK 后收尾勿夸大次数。勿调发图/下载。"
            ),
        )

    # 慢媒体：更鼓励带「正在下载/找图」前置，避免长等待像卡住
    if _slow_tool_intent(text, perception):
        return ToolPlan(
            order="text_first",
            reason="slow_media_or_download",
            hint=(
                _TOOL_CHAIN
                + "下载/发图较慢：① 务必同轮带一句「好，正在下/找」再调工具；"
                "③ 只根据 ACK 报结果。勿重复调同一工具。"
            ),
        )

    if _fast_tool_intent(text, perception):
        return ToolPlan(
            order="tool_first",
            reason="lookup_or_search",
            hint=_TOOL_CHAIN + "本回合只做对方要的那件事，勿重复调同一工具。",
        )

    return ToolPlan(
        order="chat",
        reason="default_chat",
        hint="【节奏】纯聊天不用工具。需要帮忙时走三步：" + _TOOL_CHAIN,
    )


def _slow_tool_intent(text: str, perception: Perception) -> bool:
    # 「表情包/贴纸」走角色 sticker 字段，不是 setu
    if _is_persona_sticker_ask(perception.text or ""):
        return False
    if is_setu_intent(perception.text or ""):
        return True
    if is_jm_download_intent(perception.text or ""):
        return True
    if perception.has_image and any(k in text for k in ("识图", "搜图", "来源", "哪张")):
        return True
    return False


def _fast_tool_intent(text: str, perception: Perception) -> bool:
    if _is_persona_sticker_ask(perception.text or ""):
        return False
    if is_reminder_intent(perception.text or ""):
        return True
    if is_mute_intent(perception.text or ""):
        return True
    if any(k in text for k in _SEARCH_KW):
        return True
    if is_link_read_intent(perception.text or ""):
        return True
    if perception.has_image:
        return True
    if re.search(r"\d{5,}", text) and any(k in text for k in _JM_KW):
        return True
    return False


def _is_persona_sticker_ask(text: str) -> bool:
    t = text or ""
    return any(k in t for k in ("表情包", "贴纸", "发表情", "发个表情", "来个表情"))

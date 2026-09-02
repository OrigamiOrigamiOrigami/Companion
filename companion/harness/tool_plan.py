from __future__ import annotations

import re

from ..tools.jm_intent import is_jm_download_intent
from ..tools.link_intent import has_http_url, is_link_read_intent
from ..tools.mention_intent import is_mention_intent
from ..tools.mute_intent import is_mute_intent, is_unmute_intent
from ..tools.reminder_intent import is_reminder_intent
from ..tools.setu_intent import is_setu_intent
from ..canned import PREFACE_EXAMPLES
from ..voice.intent import is_song_tool_intent, is_voice_force_intent
from .types import Decision, InnerState, Perception, ToolPlan

_JM_KW = ("jm", "禁漫", "本子", "jmcomic")
_SEARCH_KW = ("搜", "查", "搜索", "下载", "识图", "找图", "点歌", "放歌", "播放")


def plan_tool_order(
    perception: Perception,
    state: InnerState,
    decision: Decision,
    config: dict,
) -> ToolPlan:
    """决定本回合：先说话再工具 / 先工具再说话 / 纯聊天。"""
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
        hint = (
            "【节奏·提醒】先调 schedule_reminder；ACK ok=true 即已排程成功，"
            "用口语确认「记下了、大概多久后喊你」（可带事由）。"
            "提醒类请忽略 delivered——它只表示图/文件是否发到聊天。"
            "收尾必须有可见短句，不要只写 emotion/sticker 控制行。"
            "本回合只处理提醒，勿调发图/下载类工具。"
        )
        return ToolPlan(order="tool_first", reason="reminder", hint=hint)

    if is_mute_intent(perception.text or ""):
        if is_unmute_intent(perception.text or ""):
            hint = (
                "【节奏·解禁】先调 unmute_group_member（目标从 @/回复/参数推断）；"
                "ACK ok=true 口语确认已解禁。忽略 delivered。"
                "收尾须有可见短句。本回合只处理解禁，勿调发图/下载。"
            )
        else:
            hint = (
                "【节奏·禁言】先调 mute_group_member（@ 或回复锁定目标，带时长）；"
                "ACK ok=true 口语确认禁言成功；ok=false 如实说没权限/失败。"
                "忽略 delivered。收尾须有可见短句，勿只写控制行。"
                "本回合只处理禁言，勿调 setu/jmcomic 等发图下载。"
            )
        return ToolPlan(order="tool_first", reason="mute", hint=hint)

    if is_mention_intent(perception.text or ""):
        hint = (
            "【节奏·点名@】只调一次 mention_group_member（name 填外号/名片）；"
            "即使用户说「@十下」也只调 1 次。"
            "ACK delivered=true 才算真发出；若写跳过/未再发送，说明没再发，"
            "收尾禁止夸大次数。忽略无关闲聊。本回合勿调发图/下载。"
        )
        return ToolPlan(order="tool_first", reason="mention", hint=hint)

    slow = _slow_tool_intent(text, perception)
    fast = _fast_tool_intent(text, perception)

    if slow and tools_cfg.get("preface_on_slow", True):
        hint = (
            "【节奏·先话后做】这条适合先发 1 句极短口语（如 "
            + PREFACE_EXAMPLES
            + "），"
            "并在**同一轮**与 tool_calls 一起输出——短句会先发给用户，再执行工具。"
            "工具 ACK：ok=true 仅表示命令成功；delivered=true 才表示图/文件已到聊天。"
            "delivered=false 勿说「发给你了」；ok=false 如实讲没弄成。勿重复调同一工具。"
        )
        return ToolPlan(order="text_first", reason="slow_media_or_download", hint=hint)

    if fast:
        hint = (
            "【节奏·先做后话】可先调用工具；收到 ACK 后：delivered=true 再确认已发出，"
            "delivered=false 勿断言已发，ok=false 如实收尾。"
            "提醒/取消类以 ok=true 为准，口语确认即可。"
            "收尾须有可见短句，勿只输出控制字段。"
        )
        return ToolPlan(order="tool_first", reason="lookup_or_search", hint=hint)

    # 默认纯聊天：不要一开口就调工具
    return ToolPlan(
        order="chat",
        reason="default_chat",
        hint=(
            "【节奏】纯聊天则不用工具。"
            "需要帮忙时：发图/下载类先说一句再调工具；查资料类可直接调工具后收尾。"
            "同一轮可同时输出短句+tool_calls。"
        ),
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

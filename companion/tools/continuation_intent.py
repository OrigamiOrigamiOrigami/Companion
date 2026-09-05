from __future__ import annotations

import re

# QQ @：@昵称(123456) / @123456
_QQ_MENTION_RE = re.compile(r"@[^()\s]{0,64}\(\d{5,}\)|\@\d{5,}")

# 「再来一个 / 换一个」类接续；不含「还没好吗」（那是催进度）
_ANOTHER_ONE = (
    "再来一个",
    "再来一本",
    "再来一张",
    "再来张",
    "再来点",
    "换一个",
    "换一本",
    "换一张",
    "还要一个",
    "还要一本",
    "还要一张",
    "下一个",
    "再来份",
)


def _strip_mentions(text: str) -> str:
    return _QQ_MENTION_RE.sub(" ", text or "").strip()


def is_another_one_intent(text: str) -> bool:
    """短接续：再来一个 / 换一个等，依赖上文任务而非本条关键词。"""
    raw = _strip_mentions(text or "")
    if not raw:
        return False
    return any(p in raw for p in _ANOTHER_ONE)


def media_family_from_tools(tools: list[str] | None) -> str | None:
    """从本回合工具名推断媒体族（jmcomic / setu）。"""
    for name in tools or []:
        low = (name or "").lower()
        if low.startswith("jmcomic_"):
            return "jmcomic"
        if low.startswith("setu_"):
            return "setu"
    return None


def continuation_tool_hint(family: str | None) -> str:
    """接续回合注入 tool_plan.hint；无粘性则空。"""
    if family == "jmcomic":
        return (
            "本条是『再来/换一个』且上文在下本子："
            "必须立刻 jmcomic_search（真实标签）再 jmcomic_download；"
            "禁止只闲聊或只发表情包。"
        )
    if family == "setu":
        return (
            "本条是『再来/换一个』且上文在发涩图："
            "必须立刻调 setu_send_image；禁止只闲聊或只发表情包。"
        )
    return ""

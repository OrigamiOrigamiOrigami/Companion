from __future__ import annotations

import re

_REMIND_KW = (
    "闹钟",
    "提醒我",
    "提醒一下",
    "喊我",
    "叫我",
    "到点",
    "计时",
    "分钟后",
    "分钟之后",
    "小时后",
    "小时之后",
    "过一会",
    "过一会儿",
    "稍后提醒",
    "定时",
)

_CANCEL_KW = ("取消提醒", "取消闹钟", "别提醒了", "不用提醒了", "取消计时")

_DURATION_RE = re.compile(
    r"(?:(\d+(?:\.\d+)?)\s*小时)?\s*(?:(\d+(?:\.\d+)?)\s*分(?:钟)?)?\s*(?:(\d+(?:\.\d+)?)\s*秒)?|"
    r"(\d+(?:\.\d+)?)\s*(小时|分钟|分|秒)",
    re.I,
)


def is_reminder_intent(text: str) -> bool:
    t = text or ""
    if any(k in t for k in _CANCEL_KW):
        return True
    if any(k in t for k in _REMIND_KW):
        return True
    # 「帮我设个 20 分钟」类
    if re.search(r"\d+\s*(分钟|分|小时|秒)", t) and any(
        k in t for k in ("帮我", "设", "定", "记", "喊", "叫", "提醒", "闹钟", "到点")
    ):
        return True
    return False


def is_cancel_reminder_intent(text: str) -> bool:
    return any(k in (text or "") for k in _CANCEL_KW)


def parse_delay_seconds(text: str) -> float | None:
    """从用户话里抽出延迟秒数；解析失败返回 None。"""
    t = (text or "").strip()
    if not t:
        return None
    # X小时Y分钟Z秒（至少命中一段带数字的）
    m = re.search(
        r"(?:(\d+(?:\.\d+)?)\s*小时)?(?:\s*(\d+(?:\.\d+)?)\s*分(?:钟)?)?(?:\s*(\d+(?:\.\d+)?)\s*秒)?",
        t,
    )
    if m and any(m.group(i) for i in (1, 2, 3)):
        hours = float(m.group(1) or 0)
        mins = float(m.group(2) or 0)
        secs = float(m.group(3) or 0)
        total = hours * 3600 + mins * 60 + secs
        if total > 0:
            return total
    m2 = re.search(r"(\d+(?:\.\d+)?)\s*(小时|分钟|分|秒)", t)
    if m2:
        n = float(m2.group(1))
        unit = m2.group(2)
        if unit == "小时":
            return n * 3600
        if unit in ("分钟", "分"):
            return n * 60
        return n
    return None


def extract_reminder_note(text: str) -> str:
    """粗提取提醒事由（去掉时间片后的剩余）。"""
    t = (text or "").strip()
    t = re.sub(
        r"\d+(?:\.\d+)?\s*小时(?:\s*\d+(?:\.\d+)?\s*分(?:钟)?)?(?:\s*\d+(?:\.\d+)?\s*秒)?",
        " ",
        t,
    )
    t = re.sub(r"\d+(?:\.\d+)?\s*分(?:钟)?(?:\s*\d+(?:\.\d+)?\s*秒)?", " ", t)
    t = re.sub(r"\d+(?:\.\d+)?\s*秒", " ", t)
    for k in (
        "帮我设定",
        "帮我设个",
        "帮我设",
        "设定",
        "设个",
        "设一个",
        "闹钟",
        "提醒我",
        "提醒一下",
        "到点了",
        "到点",
        "计时",
        "艾特我",
        "@我",
        "小爱",
    ):
        t = t.replace(k, " ")
    t = re.sub(r"\s+", " ", t).strip(" ，,。.!！？?~～")
    return t[:120]

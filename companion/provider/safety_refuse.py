from __future__ import annotations

"""识别上游模型/网关的内容安全拒答，避免写入记忆污染下一轮上下文。"""

import re
from typing import Any


# 常见国内模型安全拒答模板（子串命中即可）
_REFUSAL_MARKERS = (
    "当前输入涉及敏感信息",
    "让我们换个话题，看看有什么新的内容可以讨论",
    "这个问题我暂时无法回答，让我们换个话题",
    "我无法回答这个问题，让我们换个话题",
    "抱歉，我不能继续这个话题",
    "换个话题再聊聊吧",
)

_PAIR_RULES = (
    ("敏感信息", "换个话题"),
    ("无法回答", "换个话题"),
    ("不能回答", "换个话题"),
    ("涉及敏感", "换个话题"),
)


def is_upstream_safety_refusal(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    compact = re.sub(r"\s+", "", t)
    for m in _REFUSAL_MARKERS:
        if m in t or m in compact:
            return True
    for a, b in _PAIR_RULES:
        if a in t and b in t and len(t) < 120:
            return True
    return False


def scrub_memory_item(item: dict[str, Any] | None) -> dict[str, Any] | None:
    """写入前清洗：整段是拒答则丢弃；仅 reply 是拒答则抹掉 reply。"""
    if not item:
        return None
    out = dict(item)
    text = str(out.get("text") or out.get("summary") or "")
    reply = str(out.get("reply") or "")
    if is_upstream_safety_refusal(text):
        return None
    if reply and is_upstream_safety_refusal(reply):
        out["reply"] = ""
    return out


def strip_refusal_from_joined(text: str) -> str:
    """把多段用 / 拼起来的 reply 里拒答段去掉。"""
    raw = (text or "").strip()
    if not raw:
        return ""
    parts = [p.strip() for p in re.split(r"\s*/\s*", raw) if p.strip()]
    if len(parts) <= 1:
        return "" if is_upstream_safety_refusal(raw) else raw
    kept = [p for p in parts if not is_upstream_safety_refusal(p)]
    return " / ".join(kept)

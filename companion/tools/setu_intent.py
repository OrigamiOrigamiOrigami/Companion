from __future__ import annotations

import re
from typing import Any

SETU_KEYWORDS = ("涩涩", "涩图", "好康", "来点图", "来张图", "插画", "色图")
SETU_REQUEST_PREFIXES = ("来点", "来张", "整点", "发点", "给我来")

_SETU_STRIP = (
    "来点涩涩",
    "来点好康的",
    "来点好康",
    "来点图",
    "来张图",
    "涩涩涩",
    "涩涩",
    "涩图",
    "好康的",
    "好康",
    "色图",
    "插画",
    *SETU_REQUEST_PREFIXES,
)


def is_setu_intent(text: str) -> bool:
    """用户是否在要插画（含「来点XX」标签式请求）。"""
    raw = (text or "").strip()
    if not raw:
        return False
    lower = raw.lower()
    if any(k in lower for k in SETU_KEYWORDS):
        return True
    tail = raw
    for prefix in SETU_REQUEST_PREFIXES:
        if tail.startswith(prefix):
            rest = tail[len(prefix) :].strip()
            if rest and rest not in ("图", "涩涩", "好康的", "好康", "涩图", "色图"):
                return True
    return False


def parse_llm_setu_tags(tags: str | list[str] | None) -> list[str]:
    """模型 tool_calls 传入的 tags，原样拆分，不做语义改写。"""
    if tags is None:
        return []
    if isinstance(tags, list):
        return [str(t).strip() for t in tags if str(t).strip()]
    raw = str(tags).strip()
    if not raw:
        return []
    out: list[str] = []
    for m in re.finditer(r'"([^"]+)"|\'([^\']+)\'', raw):
        tag = (m.group(1) or m.group(2) or "").strip()
        if tag:
            out.append(tag)
        raw = raw.replace(m.group(0), " ")
    out.extend(t for t in raw.replace('"', " ").split() if t.strip())
    return out[:8]


def extract_setu_tags(msg: str, plugin: Any | None = None) -> list[str]:
    """关键词兜底：仅当模型未传 tags 时，从用户原话抠标签（兼容 setu 插件 / 简单分词）。"""
    text = (msg or "").strip()
    if not text:
        return []

    if plugin is not None and hasattr(plugin, "_extract_tags"):
        direct = plugin._extract_tags(text)
        if direct:
            return list(direct)[:8]

    for phrase in sorted(_SETU_STRIP, key=len, reverse=True):
        if phrase in text:
            text = text.replace(phrase, " ")

    text = re.sub(r"[，,。！!？?~～]", " ", text)
    tags: list[str] = []
    for m in re.finditer(r'"([^"]+)"|\'([^\']+)\'', text):
        tag = (m.group(1) or m.group(2) or "").strip()
        if tag:
            tags.append(tag)
        text = text.replace(m.group(0), " ")
    tags.extend(t for t in text.split() if t)
    return tags[:8]

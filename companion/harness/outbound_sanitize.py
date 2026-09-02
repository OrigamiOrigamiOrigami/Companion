from __future__ import annotations

import json
import logging
import re

from ..provider.openai_compat import sanitize_visible_text

logger = logging.getLogger("astrbot")

_STICKER_WANTED_RE = re.compile(r"sticker_wanted\s*[:=]\s*(true|false|yes|no|1|0)", re.I)
_STICKER_INTENT_RE = re.compile(r"sticker_intent\s*[:=]\s*([a-z_]+)", re.I)
_EMOTION_RE = re.compile(r"emotion\s*[:=]\s*([a-z_]+)", re.I)
_POKE_WANTED_RE = re.compile(r"poke_wanted\s*[:=]\s*(true|false|yes|no|1|0)", re.I)
_JSON_ACK_RE = re.compile(r'^\s*\{\s*"ok"\s*:', re.I)
_META_LINE_RE = re.compile(
    r"^(tool_calls?|function_call|arguments)\s*[:=]",
    re.I,
)

# QQ 气泡不渲染 Markdown：先拆 **bold** / `code`，再视情况剥肢体旁白
_MD_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
_MD_BOLD_U_RE = re.compile(r"__(.+?)__")
_MD_CODE_RE = re.compile(r"`([^`]+)`")
_MD_HEADING_RE = re.compile(r"^#{1,6}\s+", re.M)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
# 单星号肢体旁白：*笑* / *歪头*；不匹配已处理过的 **
_ASTERISK_ACTION_RE = re.compile(r"(?<!\*)\*([^*\n]{1,40})\*(?!\*)")


def strip_markdown_noise(text: str) -> str:
    """去掉 QQ 里只会原样显示的 Markdown 记号。"""
    out = text or ""
    out = _MD_BOLD_RE.sub(r"\1", out)
    out = _MD_BOLD_U_RE.sub(r"\1", out)
    out = _MD_CODE_RE.sub(r"\1", out)
    out = _MD_LINK_RE.sub(r"\1", out)
    out = _MD_HEADING_RE.sub("", out)
    return out


def sanitize_outbound_text(text: str, *, strip_asterisk_actions: bool = False) -> str:
    """发送前单条文本最后一道清洗。"""
    if not text:
        return ""
    out = sanitize_visible_text(text)
    out = strip_markdown_noise(out)
    if strip_asterisk_actions:
        out = _ASTERISK_ACTION_RE.sub("", out)
    out = _STICKER_WANTED_RE.sub("", out)
    out = _STICKER_INTENT_RE.sub("", out)
    out = _EMOTION_RE.sub("", out)
    out = _POKE_WANTED_RE.sub("", out)
    # 保留换行：多句气泡别压成一行
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = re.sub(r"[ \t]{2,}", " ", out).strip(" |;,.，。\n")
    if _JSON_ACK_RE.match(out):
        try:
            data = json.loads(out)
            if isinstance(data, dict) and data.get("summary"):
                out = str(data["summary"]).strip()
        except json.JSONDecodeError:
            logger.debug("companion 出站：丢弃泄漏的 json 确认包")
            return ""
    if _META_LINE_RE.match(out):
        return ""
    if out.startswith("{") and '"tool"' in out and '"ok"' in out:
        return ""
    return out.strip()


_PLACEHOLDER_BUBBLES = frozenset({"……", "...", "…", "。。。", "。。", "．", "."})


def finalize_outbound_bubbles(
    bubbles: list[str],
    *,
    max_bubbles: int = 3,
    max_chars: int = 500,
    fallback: str = "……咦，刚才好像卡住了。",
    skip: list[str] | None = None,
    strip_asterisk_actions: bool = False,
) -> list[str]:
    """发送前确认：去泄漏、去空、去重、限长限条数。

    超长时优先合并进更少气泡，而不是硬截断到一半。
    本回合已有 preface（skip）时，允许正文为空，避免再补一句「……」。
    """
    skip_norm = {_norm_bubble(x) for x in (skip or []) if x}
    cleaned: list[str] = []
    for raw in bubbles or []:
        text = sanitize_outbound_text(raw, strip_asterisk_actions=strip_asterisk_actions)
        if not text or text in _PLACEHOLDER_BUBBLES:
            continue
        key = _norm_bubble(text)
        if key in skip_norm:
            continue
        if cleaned and _norm_bubble(cleaned[-1]) == key:
            continue
        cleaned.append(text)
        skip_norm.add(key)

    if not cleaned:
        # 前言已说过话：不要再塞占位省略号
        if skip_norm:
            return []
        fb = sanitize_outbound_text(fallback, strip_asterisk_actions=strip_asterisk_actions) or ""
        return [fb[:max_chars]] if fb else []

    # 超过条数：把尾部并进最后一条（尽量说完）
    if len(cleaned) > max_bubbles:
        head = cleaned[: max_bubbles - 1]
        tail = "\n".join(cleaned[max_bubbles - 1 :])
        cleaned = [*head, tail]

    # 单条仍超长：软截断到完整句附近
    out: list[str] = []
    for text in cleaned:
        if len(text) > max_chars:
            text = _soft_trim(text, max_chars)
        out.append(text)
    return out


def _soft_trim(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars].rstrip()
    for sep in ("。", "！", "？", "…", "~", "～", "\n"):
        idx = cut.rfind(sep)
        if idx >= max(20, max_chars // 3):
            return cut[: idx + 1]
    return cut.rstrip("，,、；; ") + "…"


def _norm_bubble(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip())

"""出站 @： At + Plain + MessageChain。

LLM 群聊写法：
  @[qq:123456789]
  @[123456789]
  @昵称(123456789)
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("astrbot")

# @[qq:UID] / @[UID] / @昵称(UID)
_AT_MARK_RE = re.compile(
    r"@\[(?:qq[:：]\s*)?(\d{5,12})\]"
    r"|@([^\s@\[\]()]{1,32})\((\d{5,12})\)",
    re.IGNORECASE,
)


def strip_at_markers(text: str) -> str:
    """TTS / 记忆摘要：去掉标记，保留可读称呼。"""

    def _repl(m: re.Match[str]) -> str:
        if m.group(1):
            return ""
        name = (m.group(2) or "").strip()
        return f"@{name}" if name else ""

    out = _AT_MARK_RE.sub(_repl, text or "")
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def split_at_segments(text: str) -> list[tuple[str, str]]:
    """拆成 [('at'|'plain', value), ...]。"""
    raw = text or ""
    if not raw:
        return []
    out: list[tuple[str, str]] = []
    pos = 0
    for m in _AT_MARK_RE.finditer(raw):
        if m.start() > pos:
            out.append(("plain", raw[pos : m.start()]))
        qq = (m.group(1) or m.group(3) or "").strip()
        if qq:
            out.append(("at", qq))
        pos = m.end()
    if pos < len(raw):
        out.append(("plain", raw[pos:]))
    if not out:
        out.append(("plain", raw))
    return out


def append_at(chain: list[Any], qq: str | int, *, At: Any, Plain: Any) -> None:
    """与提醒计时器相同：At(qq) + 空格。"""
    try:
        chain.append(At(qq=int(qq)))
    except Exception:
        chain.append(At(qq=str(qq)))
    chain.append(Plain(" "))


def build_at_text_chain(
    text: str,
    *,
    leading_qq: str | int | None = None,
    At: Any,
    Plain: Any,
) -> list[Any]:
    """拼 MessageChain 组件列表。

    - leading_qq：提醒那种「先 @ 再正文」
    - 正文里的 @[qq:…] / @昵称(QQ) 也会拆成真 At
    """
    chain: list[Any] = []
    if leading_qq not in (None, ""):
        append_at(chain, leading_qq, At=At, Plain=Plain)

    segs = split_at_segments(text or "")
    has_inline = any(k == "at" for k, _ in segs)
    if not has_inline:
        body = (text or "").strip()
        if body:
            chain.append(Plain(body))
        return chain

    for kind, val in segs:
        if kind == "at":
            append_at(chain, val, At=At, Plain=Plain)
            continue
        chunk = val
        if chunk.startswith(" ") and chain and isinstance(chain[-1], Plain):
            chunk = chunk.lstrip(" ")
        if chunk:
            chain.append(Plain(chunk))

    while chain and isinstance(chain[-1], Plain):
        t = str(getattr(chain[-1], "text", "") or "")
        if t.strip():
            if t != t.rstrip(" "):
                chain[-1] = Plain(t.rstrip(" "))
            break
        chain.pop()
    return chain


async def send_bubble_with_ats(event: Any, text: str) -> None:
    """发送一条气泡；有 @ 标记时与提醒同一套 MessageChain。"""
    from astrbot.api.all import CommandResult

    if not _AT_MARK_RE.search(text or ""):
        await event.send(CommandResult().message(text))
        return

    try:
        from astrbot.api.message_components import At, Plain
        from astrbot.core.message.message_event_result import MessageChain
    except ImportError:
        await event.send(CommandResult().message(strip_at_markers(text) or text))
        return

    chain = build_at_text_chain(text, At=At, Plain=Plain)
    if not chain:
        await event.send(CommandResult().message(strip_at_markers(text) or "……"))
        return

    await event.send(MessageChain(chain))
    qqs = [v for k, v in split_at_segments(text) if k == "at"]
    logger.info("companion 出站@ qq=%s", ",".join(qqs))

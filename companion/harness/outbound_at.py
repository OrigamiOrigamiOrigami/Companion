"""出站 @：与提醒同一套 At + Plain + MessageChain。

可解析写法：
  @[qq:123456789] / @[123456789]
  @昵称(123456789)
  @同志猪 / @群名片   ← 按群友卡昵称·外号解析成真 At
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("astrbot")

# @[qq:UID] / @[UID] / @昵称(UID)
_AT_EXPLICIT_RE = re.compile(
    r"@\[(?:qq[:：]\s*)?(\d{5,12})\]"
    r"|@([^\s@\[\]()]{1,32})\((\d{5,12})\)",
    re.IGNORECASE,
)


def _name_at_pattern(names: list[str]) -> re.Pattern[str] | None:
    """按长度优先匹配 @昵称（最长优先，避免短名误伤）。"""
    cleaned = sorted(
        {n.strip() for n in names if n and len(n.strip()) >= 2},
        key=len,
        reverse=True,
    )
    if not cleaned:
        return None
    alts = "|".join(re.escape(n) for n in cleaned)
    # 不要求空格：@同志猪出来 → 命中「同志猪」
    return re.compile(rf"@({alts})")


def strip_at_markers(text: str, *, name_to_qq: dict[str, str] | None = None) -> str:
    """TTS / 记忆摘要：去掉标记，保留可读称呼。"""

    def _repl_explicit(m: re.Match[str]) -> str:
        if m.group(1):
            return ""
        name = (m.group(2) or "").strip()
        return f"@{name}" if name else ""

    out = _AT_EXPLICIT_RE.sub(_repl_explicit, text or "")
    pat = _name_at_pattern(list((name_to_qq or {}).keys()))
    if pat:

        def _repl_name(m: re.Match[str]) -> str:
            return f"@{m.group(1)}"

        out = pat.sub(_repl_name, out)
    return re.sub(r"[ \t]{2,}", " ", out).strip()


def split_at_segments(
    text: str,
    *,
    name_to_qq: dict[str, str] | None = None,
) -> list[tuple[str, str]]:
    """拆成 [('at'|'plain', value), ...]；at 的 value 为 QQ 号。"""
    raw = text or ""
    if not raw:
        return []

    hits: list[tuple[int, int, str]] = []  # start, end, qq

    for m in _AT_EXPLICIT_RE.finditer(raw):
        qq = (m.group(1) or m.group(3) or "").strip()
        if qq:
            hits.append((m.start(), m.end(), qq))

    pat = _name_at_pattern(list((name_to_qq or {}).keys()))
    if pat and name_to_qq:
        for m in pat.finditer(raw):
            name = m.group(1)
            qq = name_to_qq.get(name) or ""
            if not qq:
                continue
            # 与显式标记重叠则跳过
            if any(not (m.end() <= s or m.start() >= e) for s, e, _ in hits):
                continue
            hits.append((m.start(), m.end(), qq))

    hits.sort(key=lambda x: x[0])
    # 去重叠：保留先出现的
    merged: list[tuple[int, int, str]] = []
    for h in hits:
        if merged and h[0] < merged[-1][1]:
            continue
        merged.append(h)

    if not merged:
        return [("plain", raw)]

    out: list[tuple[str, str]] = []
    pos = 0
    for start, end, qq in merged:
        if start > pos:
            out.append(("plain", raw[pos:start]))
        out.append(("at", qq))
        pos = end
    if pos < len(raw):
        out.append(("plain", raw[pos:]))
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
    name_to_qq: dict[str, str] | None = None,
    reply_id: str | int | None = None,
    At: Any,
    Plain: Any,
    Reply: Any | None = None,
) -> list[Any]:
    """拼 MessageChain 组件列表。"""
    chain: list[Any] = []
    if reply_id not in (None, "") and Reply is not None:
        try:
            chain.append(Reply(id=int(reply_id)))
        except Exception:
            chain.append(Reply(id=str(reply_id)))
    if leading_qq not in (None, ""):
        append_at(chain, leading_qq, At=At, Plain=Plain)

    segs = split_at_segments(text or "", name_to_qq=name_to_qq)
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


def has_resolvable_at(text: str, *, name_to_qq: dict[str, str] | None = None) -> bool:
    segs = split_at_segments(text or "", name_to_qq=name_to_qq)
    return any(k == "at" for k, _ in segs)


async def send_bubble_with_ats(
    event: Any,
    text: str,
    *,
    name_to_qq: dict[str, str] | None = None,
    reply_id: str | int | None = None,
) -> None:
    """发送一条气泡；可选引用原消息；能解析到 QQ 时走真 At。"""
    from astrbot.api.all import CommandResult

    need_chain = bool(reply_id) or has_resolvable_at(text, name_to_qq=name_to_qq)
    if not need_chain:
        await event.send(CommandResult().message(text))
        return

    try:
        from astrbot.api.message_components import At, Plain, Reply
        from astrbot.core.message.message_event_result import MessageChain
    except ImportError:
        await event.send(
            CommandResult().message(strip_at_markers(text, name_to_qq=name_to_qq) or text)
        )
        return

    chain = build_at_text_chain(
        text,
        name_to_qq=name_to_qq,
        reply_id=reply_id,
        At=At,
        Plain=Plain,
        Reply=Reply,
    )
    if not chain:
        await event.send(
            CommandResult().message(strip_at_markers(text, name_to_qq=name_to_qq) or "……")
        )
        return

    await event.send(MessageChain(chain))
    qqs = [v for k, v in split_at_segments(text, name_to_qq=name_to_qq) if k == "at"]
    if qqs:
        logger.info("companion 出站@ qq=%s", ",".join(qqs))
    if reply_id not in (None, ""):
        logger.info("companion 出站引用 message_id=%s", reply_id)

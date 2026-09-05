from __future__ import annotations

import logging
from typing import Any

from astrbot.api.event import AstrMessageEvent

from ...canned import (
    TOOL_ASCII2D_OK,
    TOOL_GOOGLE_OK,
    TOOL_IMAGE_SEARCH_OK,
    TOOL_JM_NEED_ID,
    TOOL_JM_PREVIEW_OK,
    TOOL_JM_SEARCH_BAD_KW,
    TOOL_JM_SEARCH_EMPTY,
    TOOL_JM_SEARCH_NEED_KW,
    TOOL_JM_SEARCH_OK,
    TOOL_MISSING,
    TOOL_SETU_OK,
)
from ..ack import ToolExecResult
from ..setu_intent import extract_setu_tags, parse_llm_setu_tags
from .registry import PLUGIN_NAMES, command_result_text, resolve_plugin

logger = logging.getLogger("astrbot")

# 站内无此 tag / 无意义占位，禁止当 keyword
_JM_USELESS_KEYWORDS = frozenset(
    {
        "随机",
        "隨便",
        "随便",
        "任意",
        "任意一本",
        "来一本",
        "来本",
        "换一个",
        "换一本",
        "再来",
        "推荐",
        "random",
        "any",
        "recommend",
    }
)


async def image_search_saucenao(event: AstrMessageEvent, context: Any) -> ToolExecResult:
    plugin = resolve_plugin(PLUGIN_NAMES["image_search"])
    if plugin is None:
        return ToolExecResult(text=TOOL_MISSING, effective={"engine": "saucenao"})
    result = await plugin.search_image(event, context)
    out = command_result_text(result, ok=TOOL_IMAGE_SEARCH_OK)
    out.effective = {"engine": "saucenao", "uses_attached_image": True}
    return out


async def image_search_ascii2d(event: AstrMessageEvent, context: Any) -> ToolExecResult:
    plugin = resolve_plugin(PLUGIN_NAMES["image_search"])
    if plugin is None:
        return ToolExecResult(text=TOOL_MISSING, effective={"engine": "ascii2d"})
    result = await plugin.ascii2d_search_image(event, context)
    out = command_result_text(result, ok=TOOL_ASCII2D_OK)
    out.effective = {"engine": "ascii2d", "uses_attached_image": True}
    return out


async def image_search_google(event: AstrMessageEvent, context: Any) -> ToolExecResult:
    plugin = resolve_plugin(PLUGIN_NAMES["image_search"])
    if plugin is None:
        return ToolExecResult(text=TOOL_MISSING, effective={"engine": "google"})
    result = await plugin.google_search_image(event, context)
    out = command_result_text(result, ok=TOOL_GOOGLE_OK)
    out.effective = {"engine": "google", "uses_attached_image": True}
    return out


async def jmcomic_search(
    event: AstrMessageEvent,
    context: Any,
    mode: str,
    keyword: str,
    page: int = 1,
) -> ToolExecResult:
    plugin = resolve_plugin(PLUGIN_NAMES["jmcomic"])
    llm_mode = (mode or "title").strip().lower()
    llm_keyword = (keyword or "").strip()
    llm_page = int(page or 1)
    if plugin is None:
        return ToolExecResult(
            text=TOOL_MISSING,
            effective={"mode": llm_mode, "keyword": llm_keyword, "page": llm_page},
        )
    mode = llm_mode if llm_mode in ("tag", "title") else "title"
    page = max(1, llm_page)
    keyword = llm_keyword
    if not keyword:
        return ToolExecResult(
            text=TOOL_JM_SEARCH_NEED_KW,
            effective={"mode": mode, "keyword": "", "page": page},
        )
    kw_key = keyword.lower().replace(" ", "")
    if keyword in _JM_USELESS_KEYWORDS or kw_key in _JM_USELESS_KEYWORDS:
        return ToolExecResult(
            text=TOOL_JM_SEARCH_BAD_KW.format(keyword=keyword),
            effective={"mode": mode, "keyword": keyword, "page": page, "rejected": True},
        )
    result = await plugin.search_comics(mode, keyword, page, event)
    out = command_result_text(result, ok=TOOL_JM_SEARCH_OK)
    out.effective = {"mode": mode, "keyword": keyword, "page": page}
    plain = (out.text or out.plugin_raw or "").strip()
    if "未找到结果" in plain or "未找到" in plain:
        # 空结果算失败，促使模型换词再搜，而不是直接口语收尾
        out = ToolExecResult(
            text=TOOL_JM_SEARCH_EMPTY if "未找到结果" in plain else plain,
            plugin_sent=False,
            plugin_raw=plain,
            effective=out.effective,
        )
    return out


async def jmcomic_download(event: AstrMessageEvent, context: Any, comic_id: str) -> ToolExecResult:
    plugin = resolve_plugin(PLUGIN_NAMES["jmcomic"])
    llm_comic_id = (comic_id or "").strip().lstrip("#")
    if plugin is None:
        return ToolExecResult(
            text=TOOL_MISSING,
            effective={"comic_id": llm_comic_id, "llm_comic_id": llm_comic_id},
        )
    comic_id = llm_comic_id
    if not comic_id:
        from ..jm_intent import extract_comic_id

        msg = getattr(event, "message_str", None) or ""
        comic_id = extract_comic_id(msg) or ""
    if not comic_id:
        return ToolExecResult(
            text=TOOL_JM_NEED_ID,
            effective={"comic_id": "", "llm_comic_id": llm_comic_id},
        )
    # wait=True：等 PDF 上传成败落地再 ACK，再让人设收尾（勿靠 skill 教「别说发了」）
    result = await plugin.download_comic(comic_id, event, wait=True)
    out = command_result_text(
        result,
        ok=TOOL_JM_PREVIEW_OK.format(comic_id=comic_id),
    )
    out.effective = {"comic_id": comic_id, "llm_comic_id": llm_comic_id}
    return out


async def setu_send_image(
    event: AstrMessageEvent,
    context: Any,
    tags: str | None = None,
    companion_tool_ctx: dict[str, Any] | None = None,
) -> ToolExecResult:
    """发涩图。

    tags 语义：
    - 模型显式传 ``""`` → 随机，**不再**从用户原话抠词
    - 模型省略 tags（None）→ 才允许 keyword_fallback
    - 模型传具体标签 → 原样使用
    """
    plugin = resolve_plugin(PLUGIN_NAMES["setu"])
    msg = getattr(event, "message_str", None) or ""
    if plugin is None:
        return ToolExecResult(
            text=TOOL_MISSING,
            effective={"llm_tags": tags, "tags": [], "tag_source": "none"},
        )

    if tags is None:
        tag_list = extract_setu_tags(msg, plugin)
        tag_source = "keyword_fallback" if tag_list else "random"
        llm_tags_raw = ""
    else:
        llm_tags_raw = str(tags).strip()
        tag_list = parse_llm_setu_tags(llm_tags_raw)
        # 显式空串 = 随机；非空但解析后为空也当随机（勿回落原话）
        tag_source = "llm" if tag_list else "random"

    is_r18 = "涩涩涩" in msg
    result = await plugin._fetch_and_send(event, tag_list, is_r18=is_r18)
    detail = f"（标签：{', '.join(tag_list)}）" if tag_list else "（随机）"
    out = command_result_text(result, ok=TOOL_SETU_OK.format(detail=detail))
    out.effective = {
        "llm_tags": llm_tags_raw,
        "tags": tag_list,
        "tag_source": tag_source,
        "is_r18": is_r18,
    }
    return out


_reminder_scheduler: Any | None = None


def bind_reminder_scheduler(scheduler: Any | None) -> None:
    global _reminder_scheduler
    _reminder_scheduler = scheduler


def _group_id(event: AstrMessageEvent) -> str | None:
    try:
        if hasattr(event, "get_group_id"):
            gid = event.get_group_id()
            return str(gid) if gid else None
    except Exception:
        pass
    return None


def _session(event: AstrMessageEvent) -> str:
    return str(
        getattr(event, "unified_msg_origin", None)
        or getattr(event, "session", "")
        or ""
    )


def _platform_name(event: AstrMessageEvent) -> str:
    try:
        return str(event.get_platform_name() or "aiocqhttp")
    except Exception:
        return "aiocqhttp"


def _sender_name(event: AstrMessageEvent) -> str:
    try:
        if hasattr(event, "get_sender_name"):
            return (event.get_sender_name() or "")[:32]
    except Exception:
        pass
    return ""


async def schedule_reminder(
    event: AstrMessageEvent,
    context: Any,
    delay_minutes: float = 0,
    delay_seconds: float = 0,
    note: str = "",
    poke: bool = True,
) -> ToolExecResult:
    from ..reminder_intent import extract_reminder_note, parse_delay_seconds

    sched = _reminder_scheduler
    msg = getattr(event, "message_str", None) or ""
    mins = float(delay_minutes or 0)
    secs = float(delay_seconds or 0)
    if secs <= 0 and mins > 0:
        secs = mins * 60
    if secs <= 0:
        parsed = parse_delay_seconds(msg)
        if parsed:
            secs = parsed
    note_s = (note or "").strip() or extract_reminder_note(msg)
    effective = {
        "delay_seconds": secs,
        "note": note_s,
        "poke": bool(poke),
    }
    if sched is None or not getattr(sched, "enabled", True):
        return ToolExecResult(
            text="执行失败：提醒功能暂时不可用",
            effective=effective,
        )
    if secs <= 0:
        return ToolExecResult(
            text="执行失败：没听清要多久，请说明几分钟后再提醒",
            effective=effective,
        )
    session = _session(event)
    if not session:
        return ToolExecResult(
            text="执行失败：会话信息缺失，无法排程",
            effective=effective,
        )
    job = sched.schedule(
        delay_sec=secs,
        user_id=str(event.get_sender_id()),
        session=session,
        note=note_s,
        group_id=_group_id(event),
        platform=_platform_name(event),
        poke=bool(poke),
        sender_name=_sender_name(event),
    )
    wait_min = max(1, int(round(secs / 60))) if secs >= 45 else 0
    if wait_min:
        human = f"大约 {wait_min} 分钟后"
    else:
        human = f"大约 {int(secs)} 秒后"
    text = f"记下了~{human}喊你"
    if note_s:
        text += f"（事由：{note_s}）"
    effective.update(
        {
            "job_id": job.id,
            "due_ts": job.due_ts,
            "delay_seconds": secs,
        }
    )
    return ToolExecResult(text=text, effective=effective)


async def cancel_reminder(
    event: AstrMessageEvent,
    context: Any,
) -> ToolExecResult:
    sched = _reminder_scheduler
    if sched is None:
        return ToolExecResult(text="执行失败：提醒功能暂时不可用")
    n = sched.store.cancel_user(str(event.get_sender_id()), _group_id(event))
    if n <= 0:
        return ToolExecResult(
            text="你这边没有待触发的提醒诶",
            effective={"cancelled": 0},
        )
    return ToolExecResult(
        text=f"好啦，已取消 {n} 条提醒~",
        effective={"cancelled": n},
    )


def _mentions(event: AstrMessageEvent) -> list[str]:
    out: list[str] = []
    try:
        from astrbot.api.all import At

        for part in event.get_messages() or []:
            if isinstance(part, At):
                qq = str(getattr(part, "qq", "") or "").strip()
                if qq and qq not in out:
                    out.append(qq)
    except Exception:
        pass
    return out


def _reply_sender_id(event: AstrMessageEvent) -> str:
    try:
        from astrbot.api.all import Reply

        for part in event.get_messages() or []:
            if isinstance(part, Reply):
                for key in ("sender_id", "qq", "user_id"):
                    val = getattr(part, key, None)
                    if val:
                        return str(val)
                chain = getattr(part, "chain", None) or []
                for sub in chain:
                    for key in ("sender_id", "qq", "user_id"):
                        val = getattr(sub, key, None)
                        if val:
                            return str(val)
    except Exception:
        pass
    raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
    if isinstance(raw, dict):
        reply = raw.get("reply") or {}
        if isinstance(reply, dict):
            for key in ("sender", "user_id", "qq"):
                val = reply.get(key)
                if isinstance(val, dict):
                    uid = val.get("user_id") or val.get("id")
                    if uid:
                        return str(uid)
                elif val:
                    return str(val)
    return ""


def _self_id(event: AstrMessageEvent) -> str:
    try:
        sid = event.get_self_id()
        if sid:
            return str(sid)
    except Exception:
        pass
    msg = getattr(event, "message_obj", None)
    sid = getattr(msg, "self_id", None) if msg else None
    return str(sid) if sid else ""


_member_cards: Any | None = None


def bind_member_cards(store: Any | None) -> None:
    global _member_cards
    _member_cards = store


def _resolve_mention_target(
    event: AstrMessageEvent,
    *,
    user_id: str = "",
    name: str = "",
) -> tuple[str, str]:
    """返回 (qq, display_hint)。"""
    from ..mention_intent import extract_mention_name

    uid = str(user_id or "").strip()
    if uid.isdigit() and len(uid) >= 5:
        return uid, uid

    # 消息里已有 @ 组件 / 回复
    for m in _mentions(event):
        if m and m != _self_id(event):
            return m, m
    reply_uid = _reply_sender_id(event)
    if reply_uid and reply_uid != _self_id(event):
        return reply_uid, reply_uid

    want = (name or "").strip() or extract_mention_name(
        getattr(event, "message_str", None) or ""
    )
    if not want:
        return "", ""

    gid = _group_id(event)
    store = _member_cards
    if gid and store is not None and hasattr(store, "build_at_name_index"):
        try:
            index = store.build_at_name_index(str(gid))
        except Exception as e:
            logger.warning("companion @名索引失败: %s", e)
            index = {}
        # 精确
        if want in index:
            return index[want], want
        # 大小写不敏感（外号多为中文，仍兼容）
        low = {k.lower(): v for k, v in index.items()}
        if want.lower() in low:
            return low[want.lower()], want
        # 包含：外号是名片子串或反
        for k, v in sorted(index.items(), key=lambda kv: -len(kv[0])):
            if want in k or k in want:
                return v, k

    # 纯数字当 QQ
    if want.isdigit() and len(want) >= 5:
        return want, want
    return "", want


async def mention_group_member(
    event: AstrMessageEvent,
    context: Any,
    user_id: str = "",
    name: str = "",
) -> ToolExecResult:
    """群聊发出真正的 At；正文 @外号 仅作降级。"""
    from ...harness.outbound_at import append_at

    gid = _group_id(event)
    target, hint = _resolve_mention_target(event, user_id=user_id, name=name)
    effective = {
        "user_id": target,
        "name": (name or hint or "").strip(),
        "group_id": gid or "",
    }
    if not gid:
        return ToolExecResult(text="执行失败：只能在群里@别人哦", effective=effective)
    if not target:
        tip = f"（{hint}）" if hint else ""
        return ToolExecResult(
            text=f"执行失败：没认出要@的人{tip}，可以说外号或带 QQ",
            effective=effective,
        )
    if target == _self_id(event):
        return ToolExecResult(text="执行失败：我@我自己？才不要~", effective=effective)

    try:
        from astrbot.api.message_components import At, Plain
        from astrbot.core.message.message_event_result import MessageChain
    except ImportError:
        return ToolExecResult(text="执行失败：消息组件不可用", effective=effective)

    chain: list[Any] = []
    append_at(chain, target, At=At, Plain=Plain)
    try:
        await event.send(MessageChain(chain))
    except Exception as e:
        logger.warning("companion mention 发送失败 qq=%s: %s", target, e)
        return ToolExecResult(
            text=f"执行失败：@没发出去 {e}",
            effective=effective,
        )

    label = (hint or name or target).strip() or target
    logger.info("companion 工具@ qq=%s name=%s", target, label)
    return ToolExecResult(
        text=f"好啦，已经真@了 {label}（{target}）~（本回合仅此 1 次）",
        plugin_sent=True,
        effective=effective,
    )

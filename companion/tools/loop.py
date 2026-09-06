from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ..provider.router import ProviderRouter
from .ack import parse_tool_ack, tool_failed, build_tool_ack
from .bridge import ToolBridge
from .bridge import SINGLE_SHOT_TOOLS

logger = logging.getLogger("astrbot")

# 单意图管理类：跑完即收尾，禁止下一轮乱调 setu/jmcomic
_TERMINAL_INTENT_TOOLS = frozenset(
    {
        "schedule_reminder",
        "cancel_reminder",
        "mention_group_member",
        "llm_set_group_ban",
        "llm_set_group_whole_ban",
        "llm_set_group_card",
        "llm_set_group_special_title",
    }
)

# 瞬时失败可短重试的媒体类工具（不含 search：空结果/无效词应换参，勿同参重试）
_MEDIA_RETRY_TOOLS = frozenset(
    {
        "setu_send_image",
        "jmcomic_download",
        "image_search_saucenao",
        "image_search_ascii2d",
        "image_search_google",
    }
)

# failover 后收窄：去掉重媒体，保留管理/轻工具
_FAILOVER_DROP_PREFIXES = ("setu_", "jmcomic_", "image_search_")


def filter_tools_for_plan(
    tools: list[dict[str, Any]] | None,
    tool_plan: Any | None,
) -> list[dict[str, Any]]:
    """本回合可见工具。默认不闸门，全量交给模型；仅 voice 念白等由上层禁工具。"""
    if not tools:
        return []
    return list(tools)


class ToolLoopRunner:
    """Express 内 Tool Loop：LLM → tool_calls → 执行 → 再 LLM。"""

    def __init__(
        self,
        context: Any,
        config: dict[str, Any],
        provider: ProviderRouter,
        bridge: ToolBridge,
    ):
        self.context = context
        self.config = config
        self.provider = provider
        self.bridge = bridge
        self.tools_cfg = config.get("tools") or {}

    async def run(
        self,
        messages: list[dict[str, Any]],
        *,
        event: Any,
        card: Any,
        on_preface: Callable[[str], Awaitable[None]] | None = None,
        tool_plan: Any | None = None,
    ) -> tuple[str, list[str], list[dict[str, Any]]]:
        """链路：① 选工具（可同轮发「正在…」前置）→ ② 等真实 ACK → ③ 收尾口语。"""
        self.provider.begin_turn()
        tools = filter_tools_for_plan(self.bridge.openai_tools(card=card), tool_plan)
        if not tools:
            # 保留多模态 content（list）；勿 stringify 成 JSON 字符串，否则模型完全看不到图
            text = await self.provider.chat(messages)
            return text, [], [{"mode": "direct_no_tools", "raw_response": text}]

        max_rounds = int(self.tools_cfg.get("max_rounds") or 3)
        parallel_max = max(1, int(self.tools_cfg.get("parallel_max") or 2))
        shrink_on_failover = bool(self.tools_cfg.get("failover_shrink_tools", True))

        working = [dict(m) for m in messages]
        used: list[str] = []
        trace: list[dict[str, Any]] = []
        turn_tool_cache: dict[str, str] = {}

        for round_idx in range(max_rounds):
            data, provider_role, model = await self._llm(working, tools=tools)
            if shrink_on_failover and self.provider.consume_failover():
                before = len(tools or [])
                tools = _shrink_tools_after_failover(tools)
                logger.info(
                    "companion 供应商已回退，工具面收缩 %s→%s",
                    before,
                    len(tools or []),
                )
            choice = (data.get("choices") or [{}])[0]
            message = choice.get("message") or {}
            tool_calls = message.get("tool_calls") or []
            round_entry: dict[str, Any] = {
                "mode": "tool_loop",
                "round": round_idx,
                "provider": provider_role,
                "model": model,
                "assistant_message": dict(message),
                "tool_calls": [],
            }

            if not tool_calls:
                content = _extract_message_text(message)
                round_entry["raw_response"] = content
                trace.append(round_entry)
                if content:
                    return content, used, trace
                if used:
                    partial = ack_aware_outro(trace)
                    round_entry["raw_response"] = partial
                    round_entry["partial"] = True
                    return partial, used, trace
                raise RuntimeError("empty response after tool loop")

            # ① 前置：同轮短句只表示「已开始」，立刻发出；结果话留给 ③
            preface = _extract_message_text(message)
            if preface and on_preface:
                round_entry["preface_sent"] = preface
                await on_preface(preface)

            working.append(message)
            # 每个 tool_call_id 都必须有回执；单次工具只真实执行一次
            real_runs = 0
            for tc in tool_calls:
                fn = tc.get("function") or {}
                name = (fn.get("name") or "").strip()
                if not name:
                    continue
                raw_args = fn.get("arguments") or "{}"
                args: dict[str, Any] | None
                args_error = ""
                try:
                    parsed = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
                    if not isinstance(parsed, dict):
                        args = None
                        args_error = f"参数不是 JSON 对象（得到 {type(parsed).__name__}）"
                    else:
                        args = parsed
                except json.JSONDecodeError as e:
                    args = None
                    args_error = f"参数 JSON 无法解析: {e}"

                skipped_dup = name in SINGLE_SHOT_TOOLS and name in turn_tool_cache
                over_parallel = (
                    not skipped_dup
                    and name not in SINGLE_SHOT_TOOLS
                    and real_runs >= parallel_max
                )
                if args is None:
                    result = build_tool_ack(
                        name,
                        (
                            f"{args_error}。请修正 arguments 为合法 JSON 对象后重试；"
                            "本次未执行。"
                        ),
                        ok=False,
                        delivered=False,
                    )
                    logger.info("companion 工具参数无效 名称=%s err=%s", name, args_error)
                elif over_parallel:
                    result = build_tool_ack(
                        name,
                        f"未执行：本轮并行额度已满（最多 {parallel_max} 个），本次未发送。",
                        ok=True,
                        delivered=False,
                    )
                    logger.info("companion 工具跳过（并行上限）名称=%s", name)
                else:
                    result = await self._execute_tool(
                        name,
                        args,
                        event=event,
                        turn_tool_cache=turn_tool_cache,
                    )
                    if not skipped_dup and not (
                        parse_tool_ack(result) or {}
                    ).get("skipped_duplicate"):
                        real_runs += 1

                used.append(name)
                entry: dict[str, Any] = {
                    "name": name,
                    "tool_call_id": tc.get("id") or name,
                    "raw_arguments": raw_args
                    if isinstance(raw_args, str)
                    else json.dumps(raw_args, ensure_ascii=False),
                    "arguments": args if args is not None else {},
                    "result": result,
                }
                if args_error:
                    entry["args_error"] = args_error
                ack = None
                try:
                    ack = parse_tool_ack(result)
                except Exception:
                    pass
                if ack:
                    entry["ack"] = ack
                if skipped_dup or (ack or {}).get("skipped_duplicate") or over_parallel:
                    entry["skipped_duplicate"] = True
                round_entry["tool_calls"].append(entry)
                working.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.get("id") or name,
                        "content": result,
                    }
                )
            trace.append(round_entry)

            # search 语义失败：提示下一轮换参再调，避免直接空聊收尾
            if _jm_search_needs_retry(round_entry) and round_idx + 1 < max_rounds:
                working.append(
                    {
                        "role": "system",
                        "content": (
                            "jmcomic_search 未成功：请立刻用具体标签再调 jmcomic_search"
                            "（如全彩、中文），禁止再用「随机/随便」；有结果后再 download。"
                            "不要只口语收尾。"
                        ),
                    }
                )
            elif _jm_search_ready_to_download(round_entry) and round_idx + 1 < max_rounds:
                working.append(
                    {
                        "role": "system",
                        "content": (
                            "jmcomic_search 已有结果列表：请立刻从中选一个 ID 调 jmcomic_download，"
                            "不要只口语/发表情收尾。对方要的是本子文件。"
                        ),
                    }
                )

            if any(n in _TERMINAL_INTENT_TOOLS for n in used):
                working.append(
                    {
                        "role": "system",
                        "content": (
                            "工具已返回 ACK（第二步完成）。请只根据 ACK 做人设收尾（第三步）；"
                            "勿再调工具。若前面已说过「正在…」，这里只报结果，勿重复开工句。"
                            "只看 ok：ok=true 就是成功，必须按 summary 如实说已做成；"
                            "禁止因 delivered=false 编造失败、没权限、没禁上。"
                            "ok=false 如实说明；ACK 写跳过/未再发送则不要夸大次数。"
                            "必须输出一句可见口语；不要只写 emotion/sticker/poke 控制行。"
                        ),
                    }
                )
                break

            persona = bool(self.tools_cfg.get("persona_outro", True))
            if persona and round_idx + 1 >= max_rounds:
                working.append(
                    {
                        "role": "system",
                        "content": (
                            "工具已返回 ACK。请只根据 ACK 做人设收尾；勿再调工具。"
                            "若前面已说过「正在…」，这里只报结果，勿重复开工句。"
                            "ok=false 简短说明失败；ACK 写跳过/未再发送则不要说又做成了一次。"
                            "必须输出一句可见口语；不要只写 emotion/sticker/poke 控制行。"
                        ),
                    }
                )

        try:
            data, provider_role, model = await self._llm(working, tools=None)
        except Exception as e:
            if used:
                partial = ack_aware_outro(trace)
                trace.append(
                    {
                        "mode": "tool_loop_partial",
                        "error": str(e),
                        "raw_response": partial,
                    }
                )
                logger.warning(
                    "companion 工具链收尾 LLM 失败，已短路: %s 工具=%s",
                    e,
                    used,
                )
                return partial, used, trace
            raise

        message = ((data.get("choices") or [{}])[0]).get("message") or {}
        content = _extract_message_text(message)
        trace.append(
            {
                "mode": "tool_loop_final",
                "provider": provider_role,
                "model": model,
                "assistant_message": dict(message),
                "raw_response": content,
            }
        )
        if not content:
            if used:
                partial = ack_aware_outro(trace)
                trace[-1]["raw_response"] = partial
                trace[-1]["partial"] = True
                return partial, used, trace
            raise RuntimeError("tool loop ended without text")
        return content, used, trace

    async def _llm(
        self,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None,
    ) -> tuple[dict[str, Any], str, str]:
        return await self.provider.chat_completions_raw(
            messages=messages,
            tools=tools,
            tool_choice="auto" if tools else "none",
        )

    async def _execute_tool(
        self,
        name: str,
        args: dict[str, Any],
        *,
        event: Any,
        turn_tool_cache: dict[str, str],
    ) -> str:
        if name in SINGLE_SHOT_TOOLS and name in turn_tool_cache:
            # 不可复读成功 ACK，否则模型会以为又做成了一次
            skip = build_tool_ack(
                name,
                "跳过：本回合该工具已执行过，本次未再发送。勿声称又成功了一次。",
                ok=True,
                delivered=False,
            )
            # 标记给日志
            try:
                data = json.loads(skip)
                data["skipped_duplicate"] = True
                skip = json.dumps(data, ensure_ascii=False)
            except Exception:
                pass
            logger.info("companion 工具跳过重复调用 名称=%s", name)
            self.bridge.record_invocation(
                {
                    "tool": name,
                    "llm_request": dict(args or {}),
                    "effective": {},
                    "plugin_raw": "",
                    "plugin_sent": False,
                    "ack": parse_tool_ack(skip) or {},
                    "response": skip,
                    "skipped_duplicate": True,
                }
            )
            return skip

        result = await self.bridge.execute(name, args, event=event)
        retries = int(
            self.tools_cfg.get("media_retry")
            if self.tools_cfg.get("media_retry") is not None
            else 1
        )
        delay = float(self.tools_cfg.get("media_retry_delay_sec") or 1.5)
        # 超时未确认：后台可能仍在跑，禁止立刻同参重试（易重复发）
        # 语义失败（无效标签等）也不重试同参
        if (
            name in _MEDIA_RETRY_TOOLS
            and retries > 0
            and _tool_result_failed(result)
            and not _ack_is_timeout(result)
            and not _ack_is_semantic_reject(result)
        ):
            for attempt in range(1, retries + 1):
                logger.warning(
                    "companion 媒体工具失败将重试 名称=%s 第%s/%s次",
                    name,
                    attempt,
                    retries,
                )
                await asyncio.sleep(max(0.2, delay))
                result = await self.bridge.execute(name, args, event=event)
                if not _tool_result_failed(result):
                    break

        if name in SINGLE_SHOT_TOOLS and not _tool_result_failed(result):
            turn_tool_cache[name] = result
        return result


def ack_aware_outro(trace: list[dict[str, Any]]) -> str:
    """工具已跑但收尾 LLM 空/挂：按 ACK 决定口语，避免与已发前言/图矛盾。"""
    delivered = False
    ok = False
    failed = False
    summary = ""
    fail_summary = ""
    for entry in reversed(trace):
        for tc in entry.get("tool_calls") or []:
            ack = tc.get("ack") or {}
            if ack.get("delivered"):
                delivered = True
            if ack.get("ok"):
                ok = True
                if not summary:
                    summary = str(ack.get("summary") or "").strip()
            elif ack:
                failed = True
                if not fail_summary:
                    fail_summary = str(ack.get("summary") or "").strip()
    if delivered:
        return ""
    if ok:
        return summary or "好啦~"
    if failed:
        line = fail_summary or "唔，这次没办成……"
        return line[:80]
    return "唔，这次好像没回上……"


def _partial_outro(trace: list[dict[str, Any]]) -> str:
    """兼容旧名。"""
    return ack_aware_outro(trace)


def _shrink_tools_after_failover(
    tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    if not tools:
        return []
    out: list[dict[str, Any]] = []
    for t in tools:
        name = str((t.get("function") or {}).get("name") or "")
        if any(name.startswith(p) for p in _FAILOVER_DROP_PREFIXES):
            continue
        out.append(t)
    return out


def _extract_message_text(message: dict[str, Any]) -> str:
    from ..provider.openai_compat import _content_to_text

    return _content_to_text(message.get("content")).strip()


def _stringify_messages(messages: list[dict[str, Any]]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for m in messages:
        role = str(m.get("role") or "user")
        content = m.get("content")
        if content is None:
            content = ""
        elif not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        out.append({"role": role, "content": content})
    return out


def _tool_result_failed(text: str) -> bool:
    return tool_failed(text)


def _ack_is_timeout(text: str) -> bool:
    raw = text or ""
    if "执行超时" in raw or "结果未确认" in raw:
        return True
    ack = parse_tool_ack(raw) or {}
    summary = str(ack.get("summary") or "")
    detail = str(ack.get("detail") or "")
    return "执行超时" in summary or "执行超时" in detail or "结果未确认" in summary


def _ack_is_semantic_reject(text: str) -> bool:
    raw = text or ""
    markers = ("不是有效标签", "未找到结果", "请换具体")
    if any(m in raw for m in markers):
        return True
    ack = parse_tool_ack(raw) or {}
    blob = f"{ack.get('summary') or ''}{ack.get('detail') or ''}"
    return any(m in blob for m in markers)


def _jm_search_needs_retry(round_entry: dict[str, Any]) -> bool:
    for tc in round_entry.get("tool_calls") or []:
        if (tc.get("name") or "") != "jmcomic_search":
            continue
        ack = tc.get("ack") or {}
        if ack.get("ok"):
            continue
        blob = f"{ack.get('summary') or ''}{ack.get('detail') or ''}{tc.get('result') or ''}"
        if _ack_is_semantic_reject(blob):
            return True
    return False


def _jm_search_ready_to_download(round_entry: dict[str, Any]) -> bool:
    """本轮 search 成功且回执里已有 JM ID → 应继续 download。"""
    import re

    for tc in round_entry.get("tool_calls") or []:
        if (tc.get("name") or "") != "jmcomic_search":
            continue
        ack = tc.get("ack") or {}
        if not ack.get("ok"):
            continue
        blob = f"{ack.get('detail') or ''}{tc.get('result') or ''}"
        if re.search(r"JM\d{4,}|\b\d{5,}\b", blob):
            return True
    return False

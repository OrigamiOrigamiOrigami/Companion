from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from ..provider.router import ProviderRouter
from .ack import parse_tool_ack, tool_failed
from .bridge import ToolBridge
from .bridge import SINGLE_SHOT_TOOLS

logger = logging.getLogger("astrbot")

# 单意图管理类：跑完即收尾，禁止下一轮乱调 setu/jmcomic
_TERMINAL_INTENT_TOOLS = frozenset(
    {
        "mute_group_member",
        "unmute_group_member",
        "schedule_reminder",
        "cancel_reminder",
    }
)

# tool_plan.reason → 本回合只暴露这些工具
_INTENT_TOOL_ALLOW: dict[str, frozenset[str]] = {
    "mute": frozenset({"mute_group_member", "unmute_group_member"}),
    "reminder": frozenset({"schedule_reminder", "cancel_reminder"}),
}


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
        tools = self.bridge.openai_tools(card=card)
        reason = getattr(tool_plan, "reason", None) if tool_plan else None
        allow = _INTENT_TOOL_ALLOW.get(str(reason or ""))
        if allow and tools:
            tools = [t for t in tools if (t.get("function") or {}).get("name") in allow]
        if not tools:
            text = await self.provider.chat(_stringify_messages(messages))
            return text, [], [{"mode": "direct_no_tools", "raw_response": text}]

        max_rounds = int(self.tools_cfg.get("max_rounds") or 3)
        parallel_max = max(1, int(self.tools_cfg.get("parallel_max") or 2))

        working = [dict(m) for m in messages]
        used: list[str] = []
        trace: list[dict[str, Any]] = []
        turn_tool_cache: dict[str, str] = {}

        for round_idx in range(max_rounds):
            data, provider_role, model = await self._llm(working, tools=tools)
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
                raise RuntimeError("empty response after tool loop")

            preface = _extract_message_text(message)
            if preface and on_preface:
                round_entry["preface_sent"] = preface
                await on_preface(preface)

            working.append(message)
            batch = tool_calls[:parallel_max]
            for tc in batch:
                fn = tc.get("function") or {}
                name = (fn.get("name") or "").strip()
                if not name:
                    continue
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
                except json.JSONDecodeError:
                    args = {}
                skipped_dup = name in SINGLE_SHOT_TOOLS and name in turn_tool_cache
                result = await self._execute_tool(
                    name,
                    args,
                    event=event,
                    turn_tool_cache=turn_tool_cache,
                )
                used.append(name)
                entry: dict[str, Any] = {
                    "name": name,
                    "tool_call_id": tc.get("id") or name,
                    "raw_arguments": raw_args if isinstance(raw_args, str) else json.dumps(raw_args, ensure_ascii=False),
                    "arguments": args,
                    "result": result,
                }
                ack = None
                try:
                    ack = parse_tool_ack(result)
                except Exception:
                    pass
                if ack:
                    entry["ack"] = ack
                if skipped_dup:
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

            # 禁言/提醒等已执行：立刻进人设收尾，勿再挂工具（防 mute 失败后乱调 setu）
            if any(n in _TERMINAL_INTENT_TOOLS for n in used):
                working.append(
                    {
                        "role": "system",
                        "content": (
                            "本回合管理类工具已执行完毕。请根据 ACK 用人设口语收尾；"
                            "勿再调用任何工具。ok=false 如实说明原因。"
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
                            "工具已执行完毕。请根据 ACK 收尾："
                            "发图/下载/点歌：delivered=true 才可确认已到聊天；"
                            "delivered=false 勿说「发给你了」。"
                            "提醒/取消提醒：ok=true 即已办妥，口语确认即可，勿因 delivered=false 犹豫。"
                            "ok=false 用人设简短道歉。勿重复调工具。"
                            "必须输出一句可见口语；不要只写 emotion/sticker/poke 控制行。"
                        ),
                    }
                )

        try:
            data, provider_role, model = await self._llm(working, tools=None)
        except Exception as e:
            if used:
                partial = _partial_outro(trace)
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
                partial = _partial_outro(trace)
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
            cached = turn_tool_cache[name]
            logger.info("companion 工具跳过重复调用 名称=%s", name)
            self.bridge.record_invocation(
                {
                    "tool": name,
                    "llm_request": dict(args or {}),
                    "effective": {},
                    "plugin_raw": "",
                    "plugin_sent": False,
                    "ack": parse_tool_ack(cached) or {},
                    "response": cached,
                    "skipped_duplicate": True,
                }
            )
            return cached
        result = await self.bridge.execute(name, args, event=event)
        if name in SINGLE_SHOT_TOOLS and not _tool_result_failed(result):
            turn_tool_cache[name] = result
        return result


def _partial_outro(trace: list[dict[str, Any]]) -> str:
    """工具已跑但收尾 LLM 挂掉：按 ACK 决定要不要再发话，避免与已发前言/图矛盾。"""
    delivered = False
    ok = False
    summary = ""
    for entry in reversed(trace):
        for tc in entry.get("tool_calls") or []:
            ack = tc.get("ack") or {}
            if ack.get("delivered"):
                delivered = True
            if ack.get("ok"):
                ok = True
                if not summary:
                    summary = str(ack.get("summary") or "").strip()
    if delivered:
        return ""
    if ok:
        return summary or "好啦~"
    return ""


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

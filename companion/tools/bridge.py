from __future__ import annotations

import asyncio
import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any

from ..platform.astrbot_adapter import get_llm_tool_manager
from .ack import ToolExecResult, build_tool_ack, parse_tool_ack

logger = logging.getLogger("astrbot")

try:
    from mcp.types import TextContent
except ImportError:
    TextContent = None  # type: ignore[misc, assignment]

_MCP_IDLE_LOGGED = False
_MCP_READY_LOGGED = False
_MCP_SYNC_LOGGED = False

_SLOW_TOOL_PREFIXES = ("setu_", "image_search_", "jmcomic_")
# 会直接发到聊天里的工具：同一轮对话只执行一次，避免 LLM 重复调用
SINGLE_SHOT_TOOLS = frozenset(
    {
        "setu_send_image",
        "jmcomic_download",
        "image_search_saucenao",
        "image_search_ascii2d",
        "image_search_google",
        "schedule_reminder",
        "cancel_reminder",
        "mute_group_member",
        "unmute_group_member",
        "mention_group_member",
    }
)


@dataclass
class ToolSpec:
    name: str
    description: str
    origin: str
    source_label: str
    parameters: dict[str, Any]
    func_tool: Any


class ToolBridge:
    """跨插件 Tool Bridge：AstrBot llm_tool ∪ MCP，经 allow/deny 过滤后供 Express 调用。"""

    def __init__(self, context: Any, config: dict[str, Any]):
        self.context = context
        self.config = config or {}
        self.tools_cfg = self.config.get("tools") or {}
        self._turn_specs: list[ToolSpec] | None = None
        self._turn_invocations: list[dict[str, Any]] = []
        self._companion_tool_ctx: dict[str, Any] = {}

    def begin_turn(self, card: Any | None = None) -> None:
        """新一轮用户消息开始时清缓存，避免同轮重复扫 ToolManager。"""
        self._turn_specs = None
        self._turn_invocations = []
        self._companion_tool_ctx = self._tool_ctx_from_card(card)

    @staticmethod
    def _tool_ctx_from_card(card: Any | None) -> dict[str, Any]:
        if card is None:
            return {}
        ext = getattr(card, "companion_ext", None) or {}
        character_tag = str(
            ext.get("setu_tag") or getattr(card, "display_name", "") or getattr(card, "id", "")
        ).strip()
        return {
            "character_tag": character_tag,
            "wake_words": list(getattr(card, "wake_words", None) or []),
            "aliases": list(getattr(card, "aliases", None) or []),
        }

    def drain_invocations(self) -> list[dict[str, Any]]:
        """取出本回合已记录的工具调用（供回合日志）。"""
        items = list(self._turn_invocations)
        self._turn_invocations = []
        return items

    def record_invocation(self, record: dict[str, Any]) -> None:
        self._turn_invocations.append(record)

    def enabled(self) -> bool:
        return bool(self.tools_cfg.get("enabled", True))

    def list_tools(self, *, card: Any | None = None) -> list[ToolSpec]:
        return self._collect_specs(card=card)

    def mcp_status(self) -> dict[str, Any]:
        manager = get_llm_tool_manager(self.context)
        if manager is None:
            return {"connected": [], "tools": [], "enabled": self.tools_cfg.get("mcp_enabled", True)}
        clients = list(getattr(manager, "mcp_client_dict", {}) or {})
        tools = [
            {
                "name": getattr(f, "name", ""),
                "server": getattr(f, "mcp_server_name", ""),
                "active": getattr(f, "active", True),
            }
            for f in getattr(manager, "func_list", []) or []
            if getattr(f, "origin", "") == "mcp"
        ]
        visible = [s.name for s in self._collect_specs() if s.origin == "mcp"]
        return {
            "connected": clients,
            "tools": tools,
            "visible": visible,
            "enabled": bool(self.tools_cfg.get("mcp_enabled", True)),
        }

    def openai_tools(self, *, card: Any | None = None) -> list[dict[str, Any]]:
        specs = self._collect_specs(card=card)
        out: list[dict[str, Any]] = []
        for spec in specs:
            fn: dict[str, Any] = {
                "name": spec.name,
                "description": spec.description or spec.name,
            }
            params = _normalize_parameters(spec.parameters)
            fn["parameters"] = params
            out.append({"type": "function", "function": fn})
        return out

    def tool_summary(self, *, card: Any | None = None, limit: int = 12) -> str:
        specs = self._collect_specs(card=card)
        if not specs:
            return ""
        names = [f"{s.name}({s.source_label})" for s in specs[:limit]]
        extra = len(specs) - limit
        tail = f" 等共 {len(specs)} 个" if extra > 0 else ""
        return "可用工具：" + "、".join(names) + tail

    async def execute(
        self,
        name: str,
        args: dict[str, Any],
        *,
        event: Any = None,
        timeout_sec: int | None = None,
    ) -> str:
        spec_map = {s.name: s for s in self._collect_specs()}
        spec = spec_map.get(name)
        if spec is None:
            ack = build_tool_ack(name, f"工具 {name} 不可用或未注册", ok=False)
            self._log_invocation(
                name,
                llm_request=dict(args or {}),
                plugin_raw="",
                ack_json=ack,
            )
            return ack

        timeout = self._resolve_timeout(name, timeout_sec)
        try:
            result = await asyncio.wait_for(
                self._invoke(spec.func_tool, args, event=event),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("companion 工具超时 名称=%s 已等=%ss", name, timeout)
            msg = f"工具 {name} 执行超时（{timeout}s），结果未确认"
            ack = build_tool_ack(name, msg, ok=False, delivered=False)
            self._log_invocation(
                name,
                llm_request=dict(args or {}),
                plugin_raw=msg,
                ack_json=ack,
            )
            return ack
        except Exception as e:
            logger.warning("companion 工具失败 名称=%s 错误=%s", name, e, exc_info=True)
            msg = f"工具 {name} 执行失败: {e}"[:500]
            ack = build_tool_ack(name, msg, ok=False)
            self._log_invocation(
                name,
                llm_request=dict(args or {}),
                plugin_raw=msg,
                ack_json=ack,
            )
            return ack

        if isinstance(result, ToolExecResult):
            ack = build_tool_ack(name, result)
            self._log_invocation(
                name,
                llm_request=dict(args or {}),
                exec_result=result,
                ack_json=ack,
            )
            return ack
        raw = _format_tool_result(result, origin=spec.origin)
        ack = build_tool_ack(name, raw)
        self._log_invocation(
            name,
            llm_request=dict(args or {}),
            plugin_raw=raw,
            ack_json=ack,
        )
        return ack

    def _log_invocation(
        self,
        tool: str,
        *,
        llm_request: dict[str, Any],
        ack_json: str,
        exec_result: ToolExecResult | None = None,
        plugin_raw: str = "",
    ) -> None:
        ack = parse_tool_ack(ack_json) or {}
        record: dict[str, Any] = {
            "tool": tool,
            "llm_request": llm_request,
            "effective": dict((exec_result.effective if exec_result else {}) or {}),
            "plugin_raw": (exec_result.plugin_raw if exec_result else plugin_raw) or "",
            "plugin_sent": bool(exec_result.plugin_sent) if exec_result else False,
            "ack": ack,
            "response": ack_json,
        }
        self.record_invocation(record)
        eff = record["effective"]
        logger.info(
            "companion 工具调用 名称=%s 请求=%s 实际=%s ok=%s delivered=%s",
            tool,
            llm_request,
            eff or llm_request,
            ack.get("ok"),
            ack.get("delivered"),
        )

    def _collect_specs(self, card: Any | None = None) -> list[ToolSpec]:
        if self._turn_specs is not None:
            return self._turn_specs
        specs = self._collect_specs_uncached(card)
        self._turn_specs = specs
        return specs

    def _collect_specs_uncached(self, card: Any | None = None) -> list[ToolSpec]:
        global _MCP_IDLE_LOGGED, _MCP_READY_LOGGED, _MCP_SYNC_LOGGED
        if not self.enabled():
            return []

        manager = get_llm_tool_manager(self.context)
        if manager is None:
            return []

        mcp_enabled = bool(self.tools_cfg.get("mcp_enabled", True))
        allow, deny = self._policy(card)
        specs: list[ToolSpec] = []
        mcp_clients = getattr(manager, "mcp_client_dict", None) or {}

        for func in getattr(manager, "func_list", []) or []:
            if not getattr(func, "active", True):
                continue
            origin = getattr(func, "origin", "local") or "local"
            if origin == "mcp":
                if not mcp_enabled:
                    continue
            name = getattr(func, "name", "") or ""
            if not name:
                continue
            if name in deny:
                continue
            if allow is not None and name not in allow:
                continue

            handler = getattr(func, "handler", None)
            execute = getattr(func, "execute", None)
            if not handler and not callable(execute):
                logger.debug("companion 跳过空壳工具 名称=%s 来源=%s", name, origin)
                continue
            # 部分 MCP 包装 origin 未标 mcp，但只有 execute
            if origin != "mcp" and not handler and callable(execute):
                origin = "mcp"

            if origin == "mcp":
                server = getattr(func, "mcp_server_name", "") or "mcp"
                label = f"mcp:{server}"
            else:
                mod = getattr(func, "handler_module_path", "") or "plugin"
                plugin = mod.split(".")[0] if mod else "plugin"
                if mod.startswith("companion.") or "companion.tools.adapters" in mod:
                    label = "adapter:companion"
                elif name.startswith(("image_search_", "jmcomic_", "setu_")):
                    label = f"adapter:{name.split('_', 1)[0]}"
                else:
                    label = f"plugin:{plugin}"

            specs.append(
                ToolSpec(
                    name=name,
                    description=(getattr(func, "description", "") or "").strip(),
                    origin=origin,
                    source_label=label,
                    parameters=getattr(func, "parameters", None) or {"type": "object", "properties": {}},
                    func_tool=func,
                )
            )

        mcp_specs = [s for s in specs if s.origin == "mcp"]
        if mcp_enabled and mcp_specs and not _MCP_READY_LOGGED:
            _MCP_READY_LOGGED = True
            servers = sorted({s.source_label for s in mcp_specs})
            logger.info(
                "companion tools: MCP 可见 %d 个 (%s)",
                len(mcp_specs),
                ", ".join(servers),
            )
        elif mcp_enabled and not mcp_specs and mcp_clients and not _MCP_READY_LOGGED:
            if not _MCP_SYNC_LOGGED:
                _MCP_SYNC_LOGGED = True
                logger.info(
                    "companion tools: MCP 客户端已连接 %s，工具同步中…",
                    ", ".join(sorted(mcp_clients.keys())),
                )
            else:
                logger.debug(
                    "companion tools: MCP 同步中 (%s)，本轮已提示过",
                    ", ".join(sorted(mcp_clients.keys())),
                )
        elif (
            mcp_enabled
            and not mcp_specs
            and not mcp_clients
            and not _MCP_IDLE_LOGGED
        ):
            _MCP_IDLE_LOGGED = True
            logger.info("companion tools: MCP 尚未连接（异步初始化中或未配置 mcp_server.json）")

        specs.sort(key=lambda s: s.name)
        return specs

    def _policy(self, card: Any | None) -> tuple[set[str] | None, set[str]]:
        deny = set(self.tools_cfg.get("denylist") or [])
        card_policy = {}
        if card is not None:
            card_policy = (getattr(card, "companion_ext", None) or {}).get("tool_policy") or {}
        for n in card_policy.get("deny") or []:
            deny.add(str(n))

        mode = (self.tools_cfg.get("default_mode") or "open_with_deny").strip()
        allow_raw = list(self.tools_cfg.get("allowlist") or [])
        if card_policy.get("prefer"):
            allow_raw = list(card_policy.get("prefer") or []) + allow_raw

        if mode == "allowlist_only" or allow_raw:
            allow = {str(n) for n in allow_raw if n}
            return allow, deny
        return None, deny

    def _resolve_timeout(self, name: str, override: int | None) -> int:
        if override is not None:
            return max(1, int(override))
        overrides = self.tools_cfg.get("timeout_overrides") or {}
        if name in overrides:
            return max(1, int(overrides[name]))
        if _is_slow_tool(name):
            return max(1, int(self.tools_cfg.get("slow_timeout_sec") or 120))
        return max(1, int(self.tools_cfg.get("timeout_sec") or 30))

    async def _invoke(self, func_tool: Any, args: dict[str, Any], *, event: Any) -> Any:
        origin = getattr(func_tool, "origin", "local") or "local"
        handler = getattr(func_tool, "handler", None)
        execute = getattr(func_tool, "execute", None)

        # MCP（或仅有 execute 的包装）：走 execute，不要误判成 local
        if origin == "mcp" or (handler is None and callable(execute)):
            if not callable(execute):
                raise RuntimeError("tool has no execute")
            result = execute(**(args or {}))
            if asyncio.iscoroutine(result):
                return await result
            return result

        if not handler:
            raise RuntimeError("tool has no handler")

        kwargs = dict(args or {})
        try:
            sig = inspect.signature(handler)
            if "event" in sig.parameters and event is not None:
                kwargs["event"] = event
            if "context" in sig.parameters and self.context is not None:
                kwargs["context"] = self.context
            if "companion_tool_ctx" in sig.parameters:
                kwargs["companion_tool_ctx"] = dict(self._companion_tool_ctx or {})
            # 只传 handler 声明的参数，避免 LLM 乱塞 query 等多余字段
            allowed = set(sig.parameters.keys())
            kwargs = {k: v for k, v in kwargs.items() if k in allowed}
        except (TypeError, ValueError):
            pass

        result = handler(**kwargs)
        if asyncio.iscoroutine(result):
            return await result
        return result


def _is_slow_tool(name: str) -> bool:
    return name.startswith(_SLOW_TOOL_PREFIXES)


def _normalize_parameters(params: dict[str, Any] | None) -> dict[str, Any]:
    data = dict(params or {})
    if data.get("type") != "object":
        data["type"] = "object"
    if "properties" not in data:
        data["properties"] = {}
    return data


def _format_tool_result(result: Any, *, origin: str = "local") -> str:
    if result is None:
        return "（工具已执行，无文本结果）"
    if isinstance(result, str):
        return result[:4000]
    if origin == "mcp":
        text = _format_mcp_result(result)
        if text:
            return text[:4000]
    try:
        if hasattr(result, "model_dump"):
            return json.dumps(result.model_dump(), ensure_ascii=False)[:4000]
    except Exception:
        pass
    try:
        return json.dumps(result, ensure_ascii=False, default=str)[:4000]
    except Exception:
        return str(result)[:4000]


def _format_mcp_result(result: Any) -> str:
    content = getattr(result, "content", None)
    if not content:
        return ""
    parts: list[str] = []
    for block in content:
        if TextContent is not None and isinstance(block, TextContent):
            if block.text:
                parts.append(str(block.text))
            continue
        text = getattr(block, "text", None)
        if text:
            parts.append(str(text))
    if parts:
        return "\n".join(parts)
    if getattr(result, "structuredContent", None) is not None:
        try:
            return json.dumps(result.structuredContent, ensure_ascii=False)
        except Exception:
            pass
    return ""

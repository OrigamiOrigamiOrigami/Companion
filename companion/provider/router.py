from __future__ import annotations

import logging
import os
from typing import Any

from .openai_compat import chat_completions, chat_completions_raw, is_rate_limit_error

logger = logging.getLogger("astrbot")


class ProviderRouter:
    """多供应商：按 active 优先，失败后沿 profiles 链回退；可选 AstrBot 全局。"""

    def __init__(self, context: Any, config: dict[str, Any]):
        self.context = context
        self.config = config or {}
        self.providers_cfg = self.config.get("providers") or {}
        # 本回合是否已走过备供应商（供工具面收缩）
        self.turn_used_failover = False

    def begin_turn(self) -> None:
        self.turn_used_failover = False

    def consume_failover(self) -> bool:
        """若本回合用过备供应商则返回 True 并清除标记（供当轮收缩工具）。"""
        if not self.turn_used_failover:
            return False
        self.turn_used_failover = False
        return True

    def list_profiles(self) -> list[dict[str, Any]]:
        """返回供应商摘要（不含完整 key）。"""
        active = self.active_id()
        out: list[dict[str, Any]] = []
        for pid, block in self._profiles().items():
            creds = self._resolve_block(block, role=pid)
            out.append(
                {
                    "id": pid,
                    "label": str(block.get("label") or pid),
                    "model": (creds or {}).get("model") or block.get("model") or "",
                    "base_url": (creds or {}).get("base_url") or block.get("base_url") or "",
                    "ready": creds is not None,
                    "active": pid == active,
                }
            )
        return out

    def active_id(self) -> str:
        raw = str(self.providers_cfg.get("active") or "primary").strip()
        profiles = self._profiles()
        if raw in profiles:
            return raw
        # 别名
        aliases = {
            "主": "primary",
            "备用": "fallback",
            "claude": "claude",
            "minimax": "primary",
            "daodun": "claude",
            "道盾": "claude",
        }
        if aliases.get(raw) in profiles:
            return aliases[raw]
        if aliases.get(raw.lower()) in profiles:
            return aliases[raw.lower()]
        if "primary" in profiles:
            return "primary"
        return next(iter(profiles), "primary")

    def set_active(self, profile_id: str) -> str:
        """切换当前供应商；返回确认文案。失败抛 ValueError。"""
        pid = self._normalize_profile_id(profile_id)
        profiles = self._profiles()
        if pid not in profiles:
            ids = "、".join(profiles.keys()) or "（无）"
            raise ValueError(f"没有供应商「{profile_id}」。可用：{ids}")
        self.providers_cfg["active"] = pid
        self.config["providers"] = self.providers_cfg
        creds = self._resolve_block(profiles[pid], role=pid)
        label = profiles[pid].get("label") or pid
        if not creds:
            return (
                f"已切到 {pid}（{label}），但密钥/地址还不齐，"
                f"请在面板填 API Key 或设环境变量。"
            )
        return f"已切到 {pid} · {creds['model']} · {creds['base_url']}"

    def _normalize_profile_id(self, raw: str) -> str:
        s = (raw or "").strip()
        aliases = {
            "主": "primary",
            "主模型": "primary",
            "primary": "primary",
            "edgefn": "primary",
            "minimax": "primary",
            "m3": "primary",
            "备用": "fallback",
            "fallback": "fallback",
            "claude": "claude",
            "sonnet": "claude",
            "daodun": "claude",
            "道盾": "claude",
        }
        low = s.lower()
        if s in aliases:
            return aliases[s]
        if low in aliases:
            return aliases[low]
        return s

    def _profiles(self) -> dict[str, dict[str, Any]]:
        raw = self.providers_cfg.get("profiles")
        if isinstance(raw, dict) and raw:
            return {str(k): dict(v or {}) for k, v in raw.items() if isinstance(v, dict)}
        # 兼容仅有 primary/fallback 的旧配置
        out: dict[str, dict[str, Any]] = {}
        primary = self.providers_cfg.get("primary")
        if isinstance(primary, dict):
            out["primary"] = dict(primary)
        fallback = self.providers_cfg.get("fallback")
        if isinstance(fallback, dict) and (
            (fallback.get("base_url") or "").strip()
            or (fallback.get("model") or "").strip()
        ):
            out["fallback"] = dict(fallback)
        return out

    def _chain(self) -> list[tuple[str, dict[str, str]]]:
        """(profile_id, resolved_creds) 按试用顺序。"""
        profiles = self._profiles()
        active = self.active_id()
        order: list[str] = []
        explicit = self.providers_cfg.get("fallback_order")
        if isinstance(explicit, list) and explicit:
            order = [str(x) for x in explicit]
        else:
            order = [active] + [k for k in profiles if k != active]

        seen: set[str] = set()
        chain: list[tuple[str, dict[str, str]]] = []
        for pid in order:
            if pid in seen or pid not in profiles:
                continue
            seen.add(pid)
            creds = self._resolve_block(profiles[pid], role=pid)
            if creds:
                chain.append((pid, creds))
        return chain

    async def chat(self, messages: list[dict[str, Any]]) -> str:
        timeout = int(self.providers_cfg.get("timeout_sec") or 60)
        retries = int(self.providers_cfg.get("retries") or 3)
        errors: list[str] = []
        chain = self._chain()
        if not chain:
            raise RuntimeError(self._missing_hint_any())

        for i, (pid, creds) in enumerate(chain):
            try:
                text = await chat_completions(
                    base_url=creds["base_url"],
                    api_key=creds["api_key"],
                    model=creds["model"],
                    messages=messages,
                    timeout_sec=timeout,
                    retries=retries if i == 0 else 1,
                )
                if text or (
                    i == 0 and not self.providers_cfg.get("fallback_on_empty", True)
                ):
                    if text:
                        if i > 0:
                            self.turn_used_failover = True
                        logger.info(
                            "companion 模型=%s profile=%s", creds["model"], pid
                        )
                        return text
                    raise RuntimeError("empty response")
                errors.append(f"{pid}: empty response")
            except Exception as e:
                errors.append(f"{pid}: {e}")
                logger.warning("companion 供应商 %s 失败: %s", pid, e)

        if self.providers_cfg.get("use_astrbot_fallback", False):
            try:
                text = await self._chat_astrbot(messages)
                if text:
                    logger.info("companion 使用 AstrBot 全局供应商")
                    return text
            except Exception as e:
                errors.append(f"astrbot: {e}")
                logger.warning("companion AstrBot 全局供应商失败: %s", e)

        raise RuntimeError("; ".join(errors) or "no provider configured")

    async def chat_completions_raw(
        self,
        *,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] = "auto",
    ) -> tuple[dict[str, Any], str, str]:
        """按供应商链调用 chat/completions；返回 (data, profile_id, model)。"""
        timeout = int(self.providers_cfg.get("timeout_sec") or 60)
        retries = int(self.providers_cfg.get("retries") or 3)
        errors: list[str] = []
        chain = self._chain()
        if not chain:
            raise RuntimeError(self._missing_hint_any())

        for i, (pid, creds) in enumerate(chain):
            try:
                data = await chat_completions_raw(
                    base_url=creds["base_url"],
                    api_key=creds["api_key"],
                    model=creds["model"],
                    messages=messages,
                    timeout_sec=timeout,
                    tools=tools,
                    tool_choice=tool_choice,
                    retries=retries if i == 0 else 1,
                )
                if i > 0:
                    self.turn_used_failover = True
                    logger.info(
                        "companion 工具链回退供应商=%s model=%s", pid, creds["model"]
                    )
                return data, pid, creds["model"]
            except Exception as e:
                errors.append(f"{pid}: {e}")
                if is_rate_limit_error(e):
                    logger.warning("companion %s 模型限流: %s", pid, e)
                else:
                    logger.warning("companion %s 模型失败: %s", pid, e)
        raise RuntimeError("; ".join(errors) or "no provider configured")

    def _resolve_block(self, block: dict[str, Any], *, role: str) -> dict[str, str] | None:
        if (block.get("type") or "openai_compatible") != "openai_compatible":
            return None

        base_url = (block.get("base_url") or "").strip()
        if not base_url:
            base_url = os.getenv(
                (block.get("base_url_env") or "").strip() or "BS_BASE_URL",
                "",
            ).strip()

        api_key = (block.get("api_key") or "").strip()
        if not api_key:
            env = (block.get("api_key_env") or "").strip()
            if env:
                api_key = os.getenv(env, "").strip()
            # 兼容旧环境变量名
            if not api_key and role in ("claude", "daodun"):
                api_key = (
                    os.getenv("CLAUDE_API_KEY", "").strip()
                    or os.getenv("DAODUN_API_KEY", "").strip()
                )

        if not base_url and role in ("claude", "daodun"):
            base_url = (
                os.getenv("CLAUDE_BASE_URL", "").strip()
                or os.getenv("DAODUN_BASE_URL", "").strip()
            )

        model = (block.get("model") or "").strip()

        if not base_url or not api_key or not model:
            return None
        return {"base_url": base_url, "api_key": api_key, "model": model}

    def _missing_hint_any(self) -> str:
        active = self.active_id()
        profiles = self._profiles()
        block = profiles.get(active) or {}
        return self._missing_hint(block, role=active)

    def _missing_hint(self, block: dict[str, Any], *, role: str) -> str:
        base_url = (block.get("base_url") or "").strip()
        env_base = (block.get("base_url_env") or "").strip()
        if not base_url and env_base:
            base_url = os.getenv(env_base, "").strip()

        api_key = (block.get("api_key") or "").strip()
        env_name = (block.get("api_key_env") or "BS_API_KEY").strip()
        if not api_key:
            api_key = os.getenv(env_name, "").strip()

        model = (block.get("model") or "").strip()

        missing: list[str] = []
        if not base_url:
            missing.append("接口地址")
        if not api_key:
            missing.append(
                f"API Key（面板密钥留空时需环境变量 {env_name}）"
            )
        if not model:
            missing.append("模型名称")
        return f"供应商 {role} 未配置：缺少 {', '.join(missing) or '未知项'}"

    def readiness(self) -> str:
        chain = self._chain()
        active = self.active_id()
        if not chain:
            return self._missing_hint_any()
        first = chain[0]
        rest = ",".join(p for p, _ in chain[1:]) or "-"
        return f"ok active={first[0]} model={first[1]['model']} chain={active}>{rest}"

    def format_status(self) -> str:
        lines = ["【供应商】"]
        for row in self.list_profiles():
            mark = "▶" if row["active"] else "·"
            ready = "就绪" if row["ready"] else "缺密钥/地址"
            lines.append(
                f"{mark} {row['id']}（{row['label']}）· {row['model'] or '?'} · {ready}"
            )
            if row["base_url"]:
                lines.append(f"    {row['base_url']}")
        lines.append("切换：/伴侣 供应商 claude | 供应商 minimax")
        return "\n".join(lines)

    async def _chat_astrbot(self, messages: list[dict[str, str]]) -> str:
        provider = None
        if hasattr(self.context, "get_using_provider"):
            provider = self.context.get_using_provider()
        if provider is None and hasattr(self.context, "provider_manager"):
            pm = self.context.provider_manager
            providers = (
                getattr(pm, "provider_insts", None)
                or getattr(pm, "providers", None)
                or []
            )
            if isinstance(providers, dict) and providers:
                provider = next(iter(providers.values()))
            elif providers:
                provider = providers[0]
        if provider is None:
            raise RuntimeError("no astrbot provider")

        if hasattr(provider, "text_chat"):
            resp = await provider.text_chat(
                prompt=_last_user(messages),
                session_id=None,
                contexts=[m for m in messages if m.get("role") in ("user", "assistant")],
                system_prompt=_system(messages),
            )
            return _extract(resp)
        if hasattr(provider, "chat"):
            return _extract(await provider.chat(messages))
        raise RuntimeError(f"unsupported astrbot provider: {type(provider)}")


def _system(messages: list[dict[str, str]]) -> str:
    for m in messages:
        if m.get("role") == "system":
            return m.get("content") or ""
    return ""


def _last_user(messages: list[dict[str, str]]) -> str:
    for m in reversed(messages):
        if m.get("role") == "user":
            return m.get("content") or ""
    return ""


def _extract(resp: Any) -> str:
    if resp is None:
        return ""
    if isinstance(resp, str):
        return resp
    for attr in ("completion_text", "text", "content", "result"):
        if hasattr(resp, attr):
            val = getattr(resp, attr)
            if isinstance(val, str):
                return val
    if isinstance(resp, dict):
        for k in ("completion_text", "text", "content", "result"):
            if isinstance(resp.get(k), str):
                return resp[k]
    return str(resp)

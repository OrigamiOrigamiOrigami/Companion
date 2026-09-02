from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

from ..provider.router import ProviderRouter
from .store import MemoryStore, empty_portrait

logger = logging.getLogger("astrbot")

_VALID_FAMILIARITY = frozenset({"stranger", "warming", "trusted", "burden_shared"})
_JSON_FENCE = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.I)


class PortraitConsolidator:
    """异步 Portrait Summarizer：episodic → impression + anchors。"""

    def __init__(
        self,
        memory: MemoryStore,
        provider: ProviderRouter,
        config: dict[str, Any],
        *,
        character_id: str,
    ):
        self.memory = memory
        self.provider = provider
        self.config = config
        self.character_id = character_id
        self.portrait_cfg = config.get("portrait") or {}
        self._pending: set[str] = set()

    def maybe_schedule(self, user_id: str, *, force: bool = False) -> None:
        uid = str(user_id)
        if uid in self._pending:
            return
        if not force and not self._should_auto_run(uid):
            return
        self._pending.add(uid)
        asyncio.create_task(self._run(uid, force=force))

    def _should_auto_run(self, user_id: str) -> bool:
        portrait = self.memory.load_portrait(user_id)
        if not portrait.get("dirty"):
            return False
        if self._in_backoff(portrait):
            return False
        if not self._cooldown_ok(portrait):
            return False
        return self._gate_open(portrait, user_id)

    def _gate_open(self, portrait: dict[str, Any], user_id: str) -> bool:
        last = self._parse_ts(portrait.get("last_consolidate_at"))
        min_hours = float(self.portrait_cfg.get("consolidate_min_hours") or 6)
        if last and (time.time() - last) >= min_hours * 3600:
            return True
        min_epi = int(self.portrait_cfg.get("consolidate_min_episodic") or 8)
        since = self.memory.count_episodic_since(user_id, since_ts=last)
        return since >= min_epi

    def _cooldown_ok(self, portrait: dict[str, Any]) -> bool:
        last = self._parse_ts(portrait.get("last_consolidate_at"))
        if not last:
            return True
        cooldown_min = int(self.portrait_cfg.get("consolidate_cooldown_min") or 30)
        return (time.time() - last) >= cooldown_min * 60

    def _in_backoff(self, portrait: dict[str, Any]) -> bool:
        until = self._parse_ts(portrait.get("consolidate_backoff_until"))
        return bool(until and time.time() < until)

    async def _run(self, user_id: str, *, force: bool = False) -> bool:
        try:
            return await self.consolidate(user_id, force=force)
        finally:
            self._pending.discard(user_id)

    async def consolidate(self, user_id: str, *, force: bool = False) -> bool:
        portrait = self.memory.load_portrait(user_id)
        if not force:
            if not portrait.get("dirty"):
                return False
            if self._in_backoff(portrait):
                return False
            if not self._cooldown_ok(portrait):
                return False
            if not self._gate_open(portrait, user_id):
                return False

        digest = self.memory.episodic_digest(user_id, limit=20)
        last = self._parse_ts(portrait.get("last_consolidate_at"))
        new_anchors = [
            a
            for a in (portrait.get("anchors") or [])
            if self._parse_ts(a.get("updated_at")) and (
                not last or self._parse_ts(a.get("updated_at")) >= last
            )
        ]

        prompt = self._build_prompt(
            user_id=user_id,
            portrait=portrait,
            digest=digest,
            new_anchors=new_anchors,
        )
        raw = ""
        which = (self.portrait_cfg.get("summarizer_provider") or "fallback").strip().lower()
        try:
            raw = await self._call_summarizer(prompt)
            parsed = self._parse_output(raw)
            self._apply(user_id, portrait, parsed)
            logger.info(
                "companion 画像已整理 用户=%s 供应商=%s 原文长度=%s",
                user_id,
                which,
                len(raw or ""),
            )
            return True
        except Exception as e:
            logger.warning(
                "companion 画像整理失败 用户=%s 供应商=%s 错误=%s 原文长度=%s 预览=%r",
                user_id,
                which,
                e,
                len(raw or ""),
                self._raw_preview(raw),
            )
            self._record_failure(user_id, portrait)
            return False

    async def _call_summarizer(self, prompt: str) -> str:
        which = (self.portrait_cfg.get("summarizer_provider") or "fallback").strip().lower()
        block_key = "primary" if which == "primary" else "fallback"
        block = (self.config.get("providers") or {}).get(block_key) or {}
        creds = self.provider._resolve_block(block, role=block_key)
        if creds is None and block_key == "fallback":
            creds = self.provider._resolve_block(
                (self.config.get("providers") or {}).get("primary") or {},
                role="primary",
            )
        if creds is None:
            raise RuntimeError("no summarizer provider")

        from ..provider.openai_compat import chat_completions

        messages = [
            {
                "role": "system",
                "content": (
                    "你是 Portrait Summarizer。输出必须是单个 JSON 对象，不要 markdown 包裹。"
                    "字段: impression(string,≤400字,当前角色卡视角的观察), "
                    "anchors(array of {key,value,updated_at}), "
                    "familiarity(stranger|warming|trusted|burden_shared), "
                    "form_bias(pink|black|null)。"
                    "禁止编造无依据事实；不写不宜群聊公开的秘密细节。"
                ),
            },
            {"role": "user", "content": prompt},
        ]
        return await chat_completions(
            base_url=creds["base_url"],
            api_key=creds["api_key"],
            model=creds["model"],
            messages=messages,
            timeout_sec=int((self.config.get("providers") or {}).get("timeout_sec") or 60),
        )

    def _build_prompt(
        self,
        *,
        user_id: str,
        portrait: dict[str, Any],
        digest: list[dict[str, Any]],
        new_anchors: list[dict[str, Any]],
    ) -> str:
        budget = int(
            (self.config.get("memory") or {}).get("portrait_inject_max_chars") or 400
        )
        payload = {
            "character_id": self.character_id,
            "user_id": user_id,
            "old_portrait": {
                "impression": portrait.get("impression") or "",
                "anchors": portrait.get("anchors") or [],
                "familiarity": portrait.get("familiarity") or "stranger",
                "form_bias": portrait.get("form_bias"),
            },
            "new_anchors_since_last": new_anchors,
            "episodic_digest": digest,
            "token_budget": budget,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2)

    def _parse_output(self, raw: str) -> dict[str, Any]:
        text = (raw or "").strip()
        m = _JSON_FENCE.search(text)
        if m:
            text = m.group(1).strip()
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("summarizer output not object")
        if not (data.get("impression") or "").strip():
            raise ValueError("missing impression")
        fam = (data.get("familiarity") or "stranger").strip()
        if fam not in _VALID_FAMILIARITY:
            fam = "stranger"
        data["familiarity"] = fam
        anchors = data.get("anchors")
        if not isinstance(anchors, list):
            raise ValueError("missing anchors list")
        return data

    def _apply(self, user_id: str, old: dict[str, Any], parsed: dict[str, Any]) -> None:
        now = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        max_anchors = int((self.config.get("memory") or {}).get("portrait_max_anchors") or 30)
        anchors = parsed.get("anchors") or []
        cleaned: list[dict[str, Any]] = []
        for a in anchors:
            if not isinstance(a, dict):
                continue
            key = (a.get("key") or "").strip()
            val = a.get("value")
            if not key or val is None:
                continue
            cleaned.append(
                {
                    "key": key[:32],
                    "value": str(val)[:64],
                    "updated_at": a.get("updated_at") or now,
                }
            )
        portrait = {
            **old,
            "version": 1,
            "impression": str(parsed.get("impression") or "")[:400],
            "anchors": cleaned[:max_anchors],
            "familiarity": parsed.get("familiarity") or old.get("familiarity") or "stranger",
            "form_bias": parsed.get("form_bias"),
            "dirty": False,
            "consecutive_failures": 0,
            "consolidate_backoff_until": None,
            "last_consolidate_at": now,
            "updated_at": now,
        }
        self.memory.save_portrait(user_id, portrait)

    def _record_failure(self, user_id: str, portrait: dict[str, Any]) -> None:
        fails = int(portrait.get("consecutive_failures") or 0) + 1
        portrait["consecutive_failures"] = fails
        threshold = int(self.portrait_cfg.get("failure_backoff_threshold") or 5)
        if fails >= threshold:
            steps = min(fails - threshold + 1, 4)
            backoff_hours = 0.5 * (4 ** (steps - 1))  # 30m, 2h, 8h, 24h cap
            backoff_hours = min(backoff_hours, 24)
            portrait["consolidate_backoff_until"] = time.strftime(
                "%Y-%m-%dT%H:%M:%S%z",
                time.localtime(time.time() + backoff_hours * 3600),
            )
        self.memory.save_portrait(user_id, portrait)

    @staticmethod
    def _raw_preview(raw: Any, *, limit: int = 240) -> str:
        text = (raw if isinstance(raw, str) else "") or ""
        text = text.replace("\n", "\\n").strip()
        if len(text) > limit:
            return text[:limit] + "…"
        return text or "<empty>"

    @staticmethod
    def _parse_ts(raw: Any) -> float | None:
        if raw is None:
            return None
        if isinstance(raw, (int, float)):
            return float(raw)
        if isinstance(raw, str):
            try:
                return time.mktime(time.strptime(raw[:19], "%Y-%m-%dT%H:%M:%S"))
            except ValueError:
                return None
        return None

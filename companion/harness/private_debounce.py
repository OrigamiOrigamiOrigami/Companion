"""私聊 Turn Aggregation：短窗合并连发。"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("astrbot")


@dataclass
class _DebounceBucket:
    gen: int = 0
    parts: list[str] = field(default_factory=list)
    event: Any = None


class PrivateDebouncer:
    """同一私聊用户短窗内连发合并；仅最后一次 wait 返回合并结果。"""

    def __init__(self) -> None:
        self._buckets: dict[str, _DebounceBucket] = {}

    @staticmethod
    def resolve_window_ms(turn_cfg: dict[str, Any] | None) -> int:
        cfg = turn_cfg or {}
        ms = int(cfg.get("debounce_ms") or 2000)
        if cfg.get("adaptive_debounce", True):
            ms = max(1500, min(3000, ms))
        return max(0, ms)

    async def coalesce(
        self,
        *,
        key: str,
        event: Any,
        text: str,
        window_ms: int,
    ) -> tuple[Any, str] | None:
        """
        等待窗口结束。
        若期间有更新消息：返回 None（本调用被取代）。
        若自己是最后一代：返回 (latest_event, merged_text)。
        """
        k = str(key or "").strip() or "default"
        bucket = self._buckets.setdefault(k, _DebounceBucket())
        bucket.gen += 1
        my = bucket.gen
        t = (text or "").strip()
        if t:
            bucket.parts.append(t)
        bucket.event = event

        if window_ms > 0:
            await asyncio.sleep(window_ms / 1000.0)

        if my != bucket.gen:
            return None

        parts = list(bucket.parts)
        latest = bucket.event
        bucket.parts.clear()
        merged = "\n".join(parts).strip()
        logger.info(
            "companion 私聊合并 key=%s parts=%s chars=%s window_ms=%s",
            k,
            len(parts),
            len(merged),
            window_ms,
        )
        return latest, merged

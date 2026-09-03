"""同频道回合闸门：容量 1（令牌桶），忙则拒绝并提示。"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("astrbot")


class TurnGate:
    """同群/同私聊同时只跑一轮 Express；忙时 try_acquire 失败。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._busy: set[str] = set()

    def is_busy(self, key: str) -> bool:
        return str(key) in self._busy

    async def try_acquire(self, key: str, *, global_max: int = 0) -> bool:
        """拿到令牌返回 True；频道忙或全局已满返回 False。"""
        k = str(key or "").strip() or "default"
        async with self._lock:
            if k in self._busy:
                return False
            if global_max > 0 and len(self._busy) >= int(global_max):
                return False
            self._busy.add(k)
            logger.info(
                "companion 回合闸门 占用 channel=%s inflight=%s",
                k,
                len(self._busy),
            )
            return True

    async def release(self, key: str) -> None:
        k = str(key or "").strip() or "default"
        async with self._lock:
            self._busy.discard(k)
            logger.info(
                "companion 回合闸门 释放 channel=%s inflight=%s",
                k,
                len(self._busy),
            )

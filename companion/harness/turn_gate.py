"""同频道回合闸门：容量 1 + FIFO 排队（超时 / 超限丢弃）。"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Optional

logger = logging.getLogger("astrbot")

OnEnqueued = Optional[Callable[[], Any]]


@dataclass
class _Waiter:
    event: asyncio.Event
    enqueued_at: float
    result: str = ""  # set to overflow before wake when dropped


class TurnGate:
    """同群/同私聊同时只跑一轮 Express；忙则 FIFO 等待。"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._busy: set[str] = set()
        self._queues: dict[str, Deque[_Waiter]] = {}

    def is_busy(self, key: str) -> bool:
        return str(key) in self._busy

    def queue_len(self, key: str) -> int:
        q = self._queues.get(str(key or "").strip() or "default")
        return len(q) if q else 0

    def inflight(self) -> int:
        return len(self._busy)

    async def acquire_fifo(
        self,
        key: str,
        *,
        global_max: int = 0,
        queue_max: int = 3,
        timeout_sec: float = 60,
        on_enqueued: Optional[OnEnqueued] = None,
    ) -> str:
        """拿到令牌返回 ``ok``；等待超时 ``timeout``；被挤出队列 ``overflow``。"""
        k = str(key or "").strip() or "default"
        queue_max = max(0, int(queue_max))
        timeout_sec = max(0.1, float(timeout_sec or 60))
        global_max = int(global_max or 0)

        while True:
            waiter: _Waiter | None = None
            enqueued = False
            async with self._lock:
                if self._can_take(k, global_max):
                    self._busy.add(k)
                    logger.info(
                        "companion 回合闸门 占用 channel=%s inflight=%s q=%s",
                        k,
                        len(self._busy),
                        self.queue_len(k),
                    )
                    return "ok"

                if queue_max <= 0:
                    return "overflow"

                q = self._queues.setdefault(k, deque())
                while len(q) >= queue_max:
                    old = q.popleft()
                    old.result = "overflow"
                    old.event.set()
                    logger.warning(
                        "companion 回合闸门 丢最旧排队 channel=%s qmax=%s",
                        k,
                        queue_max,
                    )
                waiter = _Waiter(event=asyncio.Event(), enqueued_at=time.monotonic())
                q.append(waiter)
                enqueued = True
                logger.info(
                    "companion 回合闸门 入队 channel=%s qlen=%s timeout=%.0fs",
                    k,
                    len(q),
                    timeout_sec,
                )

            if enqueued and on_enqueued is not None:
                try:
                    maybe = on_enqueued()
                    if asyncio.iscoroutine(maybe):
                        await maybe
                except Exception as e:
                    logger.warning("companion 回合闸门 on_enqueued 失败: %s", e)

            assert waiter is not None
            try:
                await asyncio.wait_for(waiter.event.wait(), timeout=timeout_sec)
            except asyncio.TimeoutError:
                async with self._lock:
                    q = self._queues.get(k)
                    if q and waiter in q:
                        q.remove(waiter)
                    if q is not None and not q:
                        self._queues.pop(k, None)
                logger.warning(
                    "companion 回合闸门 排队超时 channel=%s after=%.0fs",
                    k,
                    timeout_sec,
                )
                return "timeout"

            if waiter.result == "overflow":
                return "overflow"
            # 被唤醒后重试抢占

    async def release(self, key: str) -> None:
        k = str(key or "").strip() or "default"
        async with self._lock:
            self._busy.discard(k)
            self._wake_one(k)
            # 全局腾出名额时，唤醒其他频道队首
            if self._queues:
                for other in list(self._queues.keys()):
                    if other == k:
                        continue
                    if other not in self._busy:
                        self._wake_one(other)
                        break
            logger.info(
                "companion 回合闸门 释放 channel=%s inflight=%s",
                k,
                len(self._busy),
            )

    def _can_take(self, key: str, global_max: int) -> bool:
        if key in self._busy:
            return False
        if global_max > 0 and len(self._busy) >= global_max:
            return False
        return True

    def _wake_one(self, key: str) -> None:
        q = self._queues.get(key)
        if not q:
            return
        waiter = q.popleft()
        if not q:
            self._queues.pop(key, None)
        waiter.event.set()

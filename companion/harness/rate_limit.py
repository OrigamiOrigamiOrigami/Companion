from __future__ import annotations

import hashlib
import re
import time
from dataclasses import dataclass


_WS_RE = re.compile(r"[\s\u00a0\u3000]+")


def normalize_text(text: str) -> str:
    return _WS_RE.sub("", (text or "").strip())


@dataclass
class RateLimitHit:
    reason: str  # dedupe | user_cooldown


class TurnRateLimiter:
    """同文去重 + 同人短窗限流，挡住刷屏重复 LLM。"""

    def __init__(self) -> None:
        self._dedupe_until: dict[str, float] = {}
        self._user_until: dict[str, float] = {}

    def check(
        self,
        *,
        channel: str,
        user_id: str,
        text: str,
        dedupe_sec: float = 45.0,
        user_cooldown_sec: float = 8.0,
        now: float | None = None,
    ) -> RateLimitHit | None:
        t = now if now is not None else time.time()
        self._prune(t)
        uid = str(user_id)
        ch = str(channel)
        norm = normalize_text(text)
        user_key = f"{ch}:{uid}"

        if user_cooldown_sec > 0 and t < self._user_until.get(user_key, 0):
            return RateLimitHit("user_cooldown")

        if norm and dedupe_sec > 0:
            digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]
            dedupe_key = f"{ch}:{uid}:{digest}"
            if t < self._dedupe_until.get(dedupe_key, 0):
                return RateLimitHit("dedupe")

        return None

    def commit(
        self,
        *,
        channel: str,
        user_id: str,
        text: str,
        dedupe_sec: float = 45.0,
        user_cooldown_sec: float = 8.0,
        now: float | None = None,
    ) -> None:
        """仅在即将真正走 Express/LLM 时调用。"""
        t = now if now is not None else time.time()
        uid = str(user_id)
        ch = str(channel)
        user_key = f"{ch}:{uid}"
        if user_cooldown_sec > 0:
            self._user_until[user_key] = t + float(user_cooldown_sec)
        norm = normalize_text(text)
        if norm and dedupe_sec > 0:
            digest = hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]
            dedupe_key = f"{ch}:{uid}:{digest}"
            self._dedupe_until[dedupe_key] = t + float(dedupe_sec)

    def _prune(self, now: float) -> None:
        for store in (self._dedupe_until, self._user_until):
            dead = [k for k, until in store.items() if until <= now]
            for k in dead:
                del store[k]

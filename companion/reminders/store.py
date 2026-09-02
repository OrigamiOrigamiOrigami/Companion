from __future__ import annotations

import json
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

logger = logging.getLogger("astrbot")


@dataclass
class ReminderJob:
    id: str
    due_ts: float
    user_id: str
    session: str
    note: str = ""
    group_id: str | None = None
    platform: str = "aiocqhttp"
    poke: bool = True
    character_id: str = ""
    created_ts: float = 0.0
    status: str = "pending"  # pending | done | cancelled
    sender_name: str = ""

    @classmethod
    def create(
        cls,
        *,
        delay_sec: float,
        user_id: str,
        session: str,
        note: str = "",
        group_id: str | None = None,
        platform: str = "aiocqhttp",
        poke: bool = True,
        character_id: str = "",
        sender_name: str = "",
    ) -> "ReminderJob":
        now = time.time()
        return cls(
            id=uuid.uuid4().hex[:12],
            due_ts=now + max(5.0, float(delay_sec)),
            user_id=str(user_id),
            session=session,
            note=(note or "").strip()[:200],
            group_id=str(group_id) if group_id else None,
            platform=platform or "aiocqhttp",
            poke=bool(poke),
            character_id=character_id or "",
            created_ts=now,
            status="pending",
            sender_name=(sender_name or "")[:32],
        )


class ReminderStore:
    """角色维度落盘：data/reminders/<character_id>.json"""

    def __init__(self, data_dir: str, *, character_id: str):
        self.character_id = character_id
        self.path = os.path.join(data_dir, "reminders", f"{character_id}.json")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        self._jobs: list[ReminderJob] = []
        self.load()

    def load(self) -> None:
        if not os.path.isfile(self.path):
            self._jobs = []
            return
        try:
            raw = json.load(open(self.path, encoding="utf-8")) or []
        except Exception as e:
            logger.warning("companion 提醒读盘失败: %s", e)
            self._jobs = []
            return
        jobs: list[ReminderJob] = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            try:
                jobs.append(ReminderJob(**{k: item.get(k) for k in ReminderJob.__dataclass_fields__}))
            except Exception:
                continue
        self._jobs = jobs

    def save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump([asdict(j) for j in self._jobs], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("companion 提醒写盘失败: %s", e)

    def list_pending(self) -> list[ReminderJob]:
        return [j for j in self._jobs if j.status == "pending"]

    def due_jobs(self, now: float | None = None) -> list[ReminderJob]:
        t = now if now is not None else time.time()
        return [j for j in self.list_pending() if j.due_ts <= t]

    def add(self, job: ReminderJob, *, replace_same_user: bool = True) -> ReminderJob:
        if replace_same_user:
            for old in self._jobs:
                if (
                    old.status == "pending"
                    and old.user_id == job.user_id
                    and (old.group_id or "") == (job.group_id or "")
                ):
                    old.status = "cancelled"
        self._jobs.append(job)
        self._prune()
        self.save()
        return job

    def mark(self, job_id: str, status: str) -> None:
        for j in self._jobs:
            if j.id == job_id:
                j.status = status
                break
        self.save()

    def cancel_user(self, user_id: str, group_id: str | None = None) -> int:
        n = 0
        for j in self._jobs:
            if j.status != "pending" or j.user_id != str(user_id):
                continue
            if group_id is not None and (j.group_id or "") != str(group_id):
                continue
            j.status = "cancelled"
            n += 1
        if n:
            self.save()
        return n

    def pending_for_user(self, user_id: str, group_id: str | None = None) -> list[ReminderJob]:
        out = []
        for j in self.list_pending():
            if j.user_id != str(user_id):
                continue
            if group_id is not None and (j.group_id or "") != str(group_id):
                continue
            out.append(j)
        return out

    def _prune(self, keep: int = 80) -> None:
        pending = [j for j in self._jobs if j.status == "pending"]
        done = [j for j in self._jobs if j.status != "pending"]
        done = done[-(keep - len(pending)) :] if keep > len(pending) else []
        self._jobs = pending + done

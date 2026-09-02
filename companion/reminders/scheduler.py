from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

from .store import ReminderJob, ReminderStore
from ..variants import pick_variant

logger = logging.getLogger("astrbot")

ComposeFn = Callable[[ReminderJob], Awaitable[str]]


class ReminderScheduler:
    """后台轮询到期提醒：主动发消息（可 @）+ 可选戳一戳。"""

    def __init__(
        self,
        context: Any,
        store: ReminderStore,
        config: dict[str, Any] | None = None,
        *,
        character_name: str = "",
        compose_fn: ComposeFn | None = None,
    ):
        self.context = context
        self.store = store
        self.config = config or {}
        self.character_name = character_name or "小爱"
        self.compose_fn = compose_fn
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @property
    def enabled(self) -> bool:
        return bool((self.config.get("reminders") or {}).get("enabled", True))

    def start(self) -> None:
        if not self.enabled:
            return
        if self._task and not self._task.done():
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="companion_reminders")
        n = len(self.store.list_pending())
        logger.info("companion 提醒调度已启动 待办=%s", n)

    async def stop(self) -> None:
        self._stop.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None

    def schedule(
        self,
        *,
        delay_sec: float,
        user_id: str,
        session: str,
        note: str = "",
        group_id: str | None = None,
        platform: str = "aiocqhttp",
        poke: bool = True,
        sender_name: str = "",
    ) -> ReminderJob:
        cfg = self.config.get("reminders") or {}
        max_sec = float(cfg.get("max_delay_sec") or 24 * 3600)
        min_sec = float(cfg.get("min_delay_sec") or 30)
        delay = max(min_sec, min(float(delay_sec), max_sec))
        job = ReminderJob.create(
            delay_sec=delay,
            user_id=user_id,
            session=session,
            note=note,
            group_id=group_id,
            platform=platform,
            poke=poke if cfg.get("poke_on_fire", True) else False,
            character_id=self.store.character_id,
            sender_name=sender_name,
        )
        self.store.add(job, replace_same_user=bool(cfg.get("replace_same_user", True)))
        logger.info(
            "companion 提醒已排程 id=%s 用户=%s 秒=%s 到点=%s note=%s",
            job.id,
            user_id,
            int(delay),
            time.strftime("%H:%M:%S", time.localtime(job.due_ts)),
            (note or "")[:40],
        )
        return job

    async def _loop(self) -> None:
        interval = float((self.config.get("reminders") or {}).get("poll_sec") or 5)
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception as e:
                logger.warning("companion 提醒轮询异常: %s", e)
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass

    async def _tick(self) -> None:
        due = self.store.due_jobs()
        for job in due:
            try:
                ok = await self._fire(job)
                self.store.mark(job.id, "done" if ok else "done")
            except Exception as e:
                logger.warning("companion 提醒发送失败 id=%s: %s", job.id, e)
                self.store.mark(job.id, "done")

    async def _fire(self, job: ReminderJob) -> bool:
        text = await self._compose_text(job)
        sent = await self._send_chat(job, text)
        if job.poke:
            await self._poke(job)
        logger.info(
            "companion 提醒已触发 id=%s 用户=%s 群=%s sent=%s",
            job.id,
            job.user_id,
            job.group_id or "-",
            sent,
        )
        return sent

    def _canned_text(self, job: ReminderJob) -> str:
        who = job.sender_name or "你"
        note = (job.note or "").strip()
        base = pick_variant("reminder_fire") or "诶——到点啦！"
        if note:
            return f"{base} {who}，你让我记的是：{note}"
        return f"{base} {who}，你设的时间到啦~"

    async def _compose_text(self, job: ReminderJob) -> str:
        canned = self._canned_text(job)
        if not self.compose_fn:
            return canned
        timeout = float((self.config.get("reminders") or {}).get("compose_timeout_sec") or 12)
        try:
            text = await asyncio.wait_for(self.compose_fn(job), timeout=timeout)
            clean = (text or "").strip()
            if clean:
                return clean[:160]
        except Exception as e:
            logger.warning("companion 提醒 LLM 文案失败，用变体兜底: %s", e)
        return canned

    async def _send_chat(self, job: ReminderJob, text: str) -> bool:
        try:
            from astrbot.api.message_components import At, Plain
            from astrbot.core.message.message_event_result import MessageChain

            from ..harness.outbound_at import build_at_text_chain
        except ImportError:
            logger.warning("companion 提醒：无法导入消息组件")
            return False
        # 与日常出站同一套：群聊先 @ 再正文
        leading = job.user_id if job.group_id and job.user_id else None
        chain_parts = build_at_text_chain(
            text, leading_qq=leading, At=At, Plain=Plain
        )
        if not chain_parts:
            return False
        try:
            return bool(
                await self.context.send_message(job.session, MessageChain(chain_parts))
            )
        except Exception as e:
            logger.warning("companion 提醒 send_message 失败: %s", e)
            return False

    async def _poke(self, job: ReminderJob) -> bool:
        if job.platform not in ("aiocqhttp", "onebot"):
            return False
        bot = self._get_aiocqhttp_bot()
        if bot is None:
            return False
        try:
            uid = int(job.user_id)
            if job.group_id:
                await bot.call_action(
                    "group_poke", group_id=int(job.group_id), user_id=uid
                )
            else:
                await bot.call_action("friend_poke", user_id=uid)
            return True
        except Exception as e:
            logger.warning("companion 提醒戳一戳失败: %s", e)
            return False

    def _get_aiocqhttp_bot(self) -> Any | None:
        pm = getattr(self.context, "platform_manager", None)
        insts = getattr(pm, "platform_insts", None) or []
        for platform in insts:
            try:
                if platform.meta().name == "aiocqhttp":
                    return platform.get_client()
            except Exception:
                continue
        return None

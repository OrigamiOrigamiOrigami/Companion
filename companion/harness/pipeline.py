from __future__ import annotations

import asyncio
import logging
import os
import random
import re
import time
from typing import Any
from astrbot.api.all import CommandResult
from astrbot.api.event import AstrMessageEvent

from ..card.loader import CardLoader, CharacterCard
from ..canned import (
    pick_fallback,
    PORTRAIT_EMPTY,
    STATUS_BRIEF,
    STATUS_OK_HEADER,
    VOICE_OFF,
    VOICE_ON,
    VOICE_ON_NO_KEY,
)
from ..logging.turn_logger import TurnLogger
from ..memory.anchors import extract_anchors
from ..memory.consolidator import PortraitConsolidator
from ..memory.member_card import MemberCardStore
from ..memory.store import MemoryStore
from ..provider.router import ProviderRouter
from ..provider.safety_refuse import (
    is_upstream_safety_refusal,
    strip_refusal_from_joined,
)
from ..reminders import ReminderScheduler, ReminderStore
from ..stickers.picker import StickerPicker
from ..tools.adapters.handlers import (
    bind_member_cards,
    bind_mute_config,
    bind_reminder_scheduler,
)
from ..tools.bridge import ToolBridge
from ..tools.loop import ToolLoopRunner
from ..voice import VoiceOutbound, build_tts, is_song_tool_intent
from ..variants import pick_variant
from .decide import decide
from .express import Expressor
from .form_resolver import FormResolver
from .outbound_sanitize import finalize_outbound_bubbles, sanitize_outbound_text
from .outbound_at import send_bubble_with_ats, strip_at_markers
from .perceive import perceive
from .poke import parse_poke, pick_poke_reply, pick_poke_sticker_intent, send_poke_with_pause
from .presence import is_night_hours, typing_delay_ms
from .rate_limit import TurnRateLimiter
from .tool_plan import plan_tool_order
from .turn_gate import TurnGate
from .types import Decision, ExpressResult, InnerState, Perception

logger = logging.getLogger("astrbot")


class HarnessPipeline:
    def __init__(
        self,
        context: Any,
        config: dict[str, Any],
        plugin_root: str,
        data_dir: str,
        adapters: Any | None = None,
        astrbot_config: Any | None = None,
    ):
        self.context = context
        self.config = config
        self.astrbot_config = astrbot_config
        self.adapters = adapters
        self.plugin_root = plugin_root
        self.data_dir = data_dir

        self.card_loader = CardLoader(
            plugin_root,
            data_dir,
            max_prompt_bytes=int((config.get("card") or {}).get("max_prompt_bytes") or 12000),
        )
        self.active_id = config.get("active_character") or "Aemeath"
        self.card: CharacterCard = self.card_loader.load(self.active_id)

        ns = self.card.companion_ext.get("memory_namespace") or self.card.id
        self.memory = MemoryStore(
            data_dir,
            character_ns=ns,
            memory_cfg=config.get("memory") or {},
        )
        self.member_cards = MemberCardStore(self.memory.root)
        self.rate_limiter = TurnRateLimiter()
        self.turn_gate = TurnGate()

        stickers_cfg = config.get("stickers") or {}
        override = stickers_cfg.get("data_override_dir") or os.path.join(
            data_dir, "stickers", self.card.id
        )
        self.stickers = StickerPicker(
            stickers_cfg,
            self.card.root_dir,
            override,
            character_id=self.card.id,
        )

        self.provider = ProviderRouter(context, config)
        self.tool_bridge = ToolBridge(context, config)
        tool_loop = ToolLoopRunner(context, config, self.provider, self.tool_bridge)
        self.expressor = Expressor(config, self.provider.chat, tool_loop)
        self.portrait_job = PortraitConsolidator(
            self.memory,
            self.provider,
            config,
            character_id=self.card.id,
        )
        self.form_resolver = FormResolver(config)
        self.turn_logger = TurnLogger(data_dir)
        voice_cfg = config.get("voice") or {}
        self.voice = VoiceOutbound(
            build_tts(voice_cfg, os.path.join(data_dir, "voice_cache")),
            voice_cfg,
        )

        self._states: dict[str, InnerState] = {}
        self._group_enabled: dict[str, bool] = {}
        self._group_cd: dict[str, float] = {}
        self._poke_cd: dict[str, float] = {}

        reminder_store = ReminderStore(data_dir, character_id=self.card.id)
        self.reminders = ReminderScheduler(
            context,
            reminder_store,
            config,
            character_name=self.card.display_name or self.card.id,
            compose_fn=self._compose_reminder_line,
        )
        bind_reminder_scheduler(self.reminders)
        bind_mute_config(config)
        bind_member_cards(self.member_cards)

    def start_background(self) -> None:
        self.reminders.start()

    async def stop_background(self) -> None:
        await self.reminders.stop()
        bind_reminder_scheduler(None)
        bind_member_cards(None)

    async def _compose_reminder_line(self, job: Any) -> str:
        """到点提醒文案：短人设 LLM；失败由 scheduler 回落变体池。"""
        from .outbound_sanitize import sanitize_outbound_text

        who = (getattr(job, "sender_name", None) or "你").strip() or "你"
        note = (getattr(job, "note", None) or "").strip()
        name = self.card.display_name or self.card.id
        tone = (self.card.tone_reference or "").strip()[:400]
        system = (
            f"你是{name}。现在要主动喊对方：时间到了，提醒一下。"
            f"对方可称呼「{who}」。事由：{note or '（对方没写具体事由）'}。"
            "用一两句口语，像真人催一句；可轻俏，勿 Markdown、勿列点、勿自称 AI、勿提系统/工具。"
            "只输出要发到聊天的正文，不要 emotion/sticker 控制行。"
        )
        if tone:
            system = f"{system}\n【语气参考】\n{tone}"
        raw = await self.provider.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": "到点了，提醒对方。"},
            ]
        )
        return sanitize_outbound_text(raw or "", strip_asterisk_actions=True)

    def wake_words(self) -> list[str]:
        extra = ((self.config.get("wake_words") or {}).get(self.card.id)) or []
        words = list(self.card.wake_words) + list(self.card.aliases) + [self.card.display_name] + list(extra)
        out, seen = [], set()
        for w in words:
            if w and w not in seen:
                seen.add(w)
                out.append(w)
        return out

    def status_summary(self, *, brief: bool = False) -> str:
        n_tools = len(self.tool_bridge.list_tools(card=self.card))
        n_stickers = len(self.stickers.items)
        voice_on = self.voice.tts.enabled()
        voice_bit = "语音开" if voice_on else "语音关"
        if brief:
            return STATUS_BRIEF.format(
                name=self.card.display_name,
                n_tools=n_tools,
                n_stickers=n_stickers,
                voice=voice_bit,
            )
        voice_cfg = self.config.get("voice") or {}
        prov = voice_cfg.get("provider") or "siliconflow"
        voice_line = (
            f"语音：开 · {prov} · {voice_cfg.get('model') or '?'} / "
            f"{voice_cfg.get('voice_id') or '(dynamic ref)'}"
            if voice_on
            else "语音：关"
        )
        return (
            f"{STATUS_OK_HEADER}\n"
            f"角色：{self.card.display_name}（{self.card.id}）\n"
            f"供应商：{self.provider.readiness()}\n"
            f"工具：{n_tools} 个可用\n"
            f"表情包：{n_stickers} 张\n"
            f"{voice_line}\n"
            "记忆：用户画像 + 频道对话 + 群旁听带"
        )

    def provider_status_text(self) -> str:
        return self.provider.format_status()

    def set_provider_active(self, profile_id: str) -> str:
        msg = self.provider.set_active(profile_id)
        self._persist_provider_active(self.provider.active_id())
        return msg

    def _persist_provider_active(self, profile_id: str) -> None:
        if self.astrbot_config is None:
            return
        try:
            self.astrbot_config["当前供应商"] = profile_id
            save = getattr(self.astrbot_config, "save_config", None)
            if callable(save):
                save()
                logger.info("companion 当前供应商已写入面板 active=%s", profile_id)
        except Exception as e:
            logger.warning("companion 供应商切换未能持久化: %s", e)

    def voice_status_text(self) -> str:
        cfg = self.config.setdefault("voice", {})
        flag = "开" if cfg.get("enabled") else "关"
        ready = "可用" if self.voice.tts.enabled() else "不可用（缺 key 或未开）"
        mode = self.voice.mode()
        mode_label = {"keyword": "关键词触发", "always": "每条都念", "off": "强制不念"}.get(
            mode, mode
        )
        prov = cfg.get("provider") or "siliconflow"
        return (
            f"语音开关：{flag}\n"
            f"实际状态：{ready}\n"
            f"服务商：{prov}\n"
            f"触发：{mode_label}\n"
            f"模型：{cfg.get('model') or '?'}\n"
            f"音色：{cfg.get('voice_id') or '(dynamic ref)'}\n"
            f"参考音频：{cfg.get('reference_audio') or '无'}\n"
            "说「语音 / 念一下 / 听听」会念完整回复。\n"
            "硅基克隆：官网通常无上传页，用 API 上传参考音；"
            "或面板填「语音参考音频路径+文稿」做动态克隆。\n"
            "指令：/companion voice on | voice off | voice"
        )

    def set_voice_enabled(self, enabled: bool) -> str:
        enabled = bool(enabled)
        cfg = self.config.setdefault("voice", {})
        cfg["enabled"] = enabled
        # MiniMaxTTS 持有同一份 voice dict；兜底再写一遍
        self.voice.tts.cfg["enabled"] = enabled
        self._persist_voice_enabled(enabled)
        if enabled and not self.voice.tts._api_key():
            return VOICE_ON_NO_KEY
        return VOICE_ON if enabled else VOICE_OFF

    def _persist_voice_enabled(self, enabled: bool) -> None:
        """把开关写回 AstrBot 面板配置，避免重载后丢状态。"""
        ac = self.astrbot_config
        if ac is None:
            return
        try:
            ac["启用语音合成"] = bool(enabled)
            save = getattr(ac, "save_config", None)
            if callable(save):
                save()
                logger.info("companion 语音开关已写入 AstrBot 配置 enabled=%s", enabled)
            else:
                logger.warning("companion 语音开关未能持久化（无 save_config）")
        except Exception as e:
            logger.warning("companion 语音开关持久化失败: %s", e)

    def tools_list_text(self) -> str:
        lines: list[str] = []
        if self.adapters:
            lines.extend(self.adapters.adapter_status_lines())
            lines.append("")
        mcp = self.tool_bridge.mcp_status()
        if mcp.get("enabled"):
            connected = mcp.get("connected") or []
            visible = mcp.get("visible") or []
            if connected:
                lines.append(f"MCP 已连接: {', '.join(connected)}")
                if visible:
                    lines.append(f"MCP 可用工具 ({len(visible)}): {', '.join(visible)}")
                else:
                    lines.append("MCP 已连接但当前无可见工具（检查启用MCP工具 / 黑名单）")
            else:
                lines.append("MCP: 尚未连接（AstrBot 异步初始化中或未配置）")
            lines.append("")
        specs = self.tool_bridge.list_tools(card=self.card)
        if not specs:
            lines.append("当前没有可用工具（检查 tools.enabled / 适配开关 / 其他插件 llm_tool）。")
            return "\n".join(lines)
        lines.append(f"共 {len(specs)} 个工具：")
        for s in specs:
            desc = (s.description or "").split("\n", 1)[0].strip()
            lines.append(f"- {s.name} [{s.source_label}] {desc}")
        return "\n".join(lines)

    def adapters_status_text(self) -> str:
        if not self.adapters:
            return "适配器未初始化"
        lines = ["插件适配状态：", *self.adapters.adapter_status_lines(), ""]
        if self.adapters.registered_names():
            lines.append("已注册桥接工具：")
            lines.extend(f"- {n}" for n in self.adapters.registered_names())
        else:
            lines.append("（无桥接工具，可能均已关闭）")
        return "\n".join(lines)

    def set_group_enabled(self, group_id: str, enabled: bool) -> None:
        self._group_enabled[str(group_id)] = enabled

    def reload_stickers(self) -> int:
        return self.stickers.reload()

    def sticker_stats(self) -> str:
        return self.stickers.stats.format_brief()

    def reset_sticker_stats(self) -> str:
        self.stickers.stats.reset()
        return "表情情绪统计已清零~"

    def build_sticker_catalog_image(self) -> dict:
        from ..stickers.gallery import get_or_build_sticker_catalog

        self.reload_stickers()
        out_dir = self.sticker_upload_root()
        os.makedirs(out_dir, exist_ok=True)
        name = self.card.display_name or self.card.id
        return get_or_build_sticker_catalog(
            self.stickers.items,
            output_dir=out_dir,
            title=f"{name} 表情包",
        )

    def sticker_upload_root(self) -> str:
        """运行时上传目录（data 覆盖层，不写进角色卡仓库）。"""
        stickers_cfg = self.config.get("stickers") or {}
        override = (stickers_cfg.get("data_override_dir") or "").strip()
        if override:
            return override
        return os.path.join(self.data_dir, "stickers", self.card.id)

    async def upload_sticker(
        self,
        event: Any,
        tag: str,
        *,
        form: str = "default",
        image_url: str = "",
    ) -> dict[str, Any]:
        """从本条附图、引用回复或直链取图，存入覆盖目录并 reload。"""
        from ..harness.media import (
            extract_image_payloads,
            fetch_image_payload_from_url,
        )
        from ..stickers.limits import sticker_max_file_bytes
        from ..stickers.tags import resolve_tag, tag_alias_help
        from ..stickers.upload import save_sticker_file
        from ..tools.link_intent import extract_urls

        stickers_cfg = self.config.get("stickers") or {}
        max_bytes = sticker_max_file_bytes(stickers_cfg)
        allow = set(self.stickers.allow_tags)
        card_tags = list(self.card.companion_ext.get("sticker_tags") or [])
        if card_tags:
            allow = set(t.lower() for t in card_tags) | allow
        tag_n = resolve_tag(tag)
        if not tag_n or tag_n not in allow:
            raise ValueError(f"未知情绪「{tag}」。可用：{tag_alias_help(allow)}")

        payloads = await extract_image_payloads(
            event,
            max_images=1,
            include_reply=True,
            max_bytes=max_bytes,
        )
        if not payloads:
            url = (image_url or "").strip()
            if not url:
                try:
                    text = ""
                    if getattr(event, "message_str", None):
                        text = event.message_str
                    elif hasattr(event, "get_message_str"):
                        text = event.get_message_str() or ""
                    urls = extract_urls(text, limit=1)
                    url = urls[0] if urls else ""
                except Exception:
                    url = ""
            if url:
                payload = await fetch_image_payload_from_url(url, max_bytes=max_bytes)
                if payload:
                    payloads = [payload]
                else:
                    raise ValueError(
                        "链接下载失败了……请确认是图片直链，或改成附图/回复一张图。"
                    )
        if not payloads:
            raise ValueError(
                "没找到图片诶。请附图、回复一张带图的消息，或跟上图片直链。"
            )

        info = save_sticker_file(
            root_dir=self.sticker_upload_root(),
            character_id=self.card.id,
            tag=tag_n,
            payload=payloads[0],
            max_file_bytes=max_bytes,
        )
        info["total"] = self.reload_stickers()
        info["source"] = payloads[0].source
        return info

    def portrait_show(self, user_id: str) -> str:
        p = self.memory.load_portrait(user_id)
        fam = p.get("familiarity") or "stranger"
        lines = [f"熟悉度: {fam}", (p.get("impression") or "").strip() or PORTRAIT_EMPTY]
        anchors = p.get("anchors") or []
        if anchors:
            lines.append("锚点:")
            for a in anchors:
                lines.append(f"- {a.get('key')}={a.get('value')}")
        return "\n".join(lines)

    async def refresh_portrait(self, user_id: str, *, force: bool = True) -> bool:
        return await self.portrait_job.consolidate(str(user_id), force=force)

    def clear_user_memory(self, user_id: str) -> None:
        uid = str(user_id)
        suffix = f":{uid}"
        prefix = f"{self.card.id}:"
        for key in list(self._states.keys()):
            if key.startswith(prefix) and key.endswith(suffix):
                del self._states[key]
        self.memory.clear_user(uid)

    def _with_pending_reminders(
        self,
        memory_block: str,
        *,
        user_id: str,
        group_id: str | None,
    ) -> str:
        try:
            pending = self.reminders.store.pending_for_user(user_id, group_id)
        except Exception:
            return memory_block
        if not pending:
            return memory_block
        now = time.time()
        lines = ["【待办提醒】（系统已排程；被问「还有多久/刚才交代什么」时以此为准）"]
        for j in pending[:3]:
            remain = max(0, int(j.due_ts - now))
            if remain >= 60:
                human = f"约 {remain // 60} 分 {remain % 60} 秒后"
            else:
                human = f"约 {remain} 秒后"
            note = j.note or "（未写事由）"
            lines.append(f"- {human}提醒：{note}（job={j.id}）")
        block = "\n".join(lines)
        if memory_block:
            return f"{memory_block}\n{block}"
        return block

    def _strip_asterisk_actions(self) -> bool:
        """角色卡关闭星号动作时，发送前强制剥掉 `*…*`。"""
        return not bool(self.card.companion_ext.get("allow_asterisk_actions", True))

    def _key(self, user_id: str, channel: str) -> str:
        return f"{self.card.id}:{channel}:{user_id}"

    def _state(self, user_id: str, channel: str) -> InnerState:
        key = self._key(user_id, channel)
        if key not in self._states:
            forms = self.card.companion_ext.get("forms") or {}
            form = (
                self.card.companion_ext.get("default_form")
                or (next(iter(forms), None) if forms else None)
                or "default"
            )
            self._states[key] = InnerState(active_form=str(form))
        portrait = self.memory.load_portrait(user_id)
        self._states[key].familiarity = portrait.get("familiarity") or "stranger"
        return self._states[key]

    async def handle_poke(self, event: AstrMessageEvent):
        info = parse_poke(event)
        if info is None or not info.to_self:
            return None
        if info.group_id and self._group_enabled.get(str(info.group_id), True) is False:
            return None

        cd_key = f"{info.group_id or 'private'}:{info.sender_id}"
        cd = float(
            (self.config.get("poke") or {}).get("incoming_cooldown_sec")
            or (self.config.get("group") or {}).get("poke_cooldown_sec")
            or 4
        )
        now = time.time()
        if now < self._poke_cd.get(cd_key, 0):
            return None
        self._poke_cd[cd_key] = now + cd

        channel = "private" if not info.group_id else f"group:{info.group_id}"
        state = self._state(info.sender_id, channel)
        is_private = not bool(info.group_id)
        bubble = pick_poke_reply(familiarity=state.familiarity, is_private=is_private)
        intent = pick_poke_sticker_intent(familiarity=state.familiarity, is_private=is_private)
        allow_tags = list(self.card.companion_ext.get("sticker_tags") or self.stickers.allow_tags)
        if intent not in allow_tags:
            intent = self._fallback_sticker_intent(intent, allow_tags, state)

        result = ExpressResult(
            bubbles=[bubble],
            sticker_wanted=True,
            sticker_intent=intent,
        )
        picked = self.stickers.pick_detailed(
            wanted=True, intent=intent, active_form=state.active_form
        )
        result.sticker_match_stage = picked.stage
        result.sticker_score = float(picked.score or 0.0)
        if picked.stage == "sent" and picked.path:
            result.sticker_id = picked.sticker_id
            result.sticker_path = picked.path

        poke_cfg = self.config.get("poke") or {}
        if random.random() < float(poke_cfg.get("counter_poke_prob") or 0.35):
            result.poke_wanted = True

        logger.info(
            "companion 戳一戳 用户=%s 群=%s 熟悉=%s 回复=%s 表情=%s",
            info.sender_id,
            info.group_id or "-",
            state.familiarity,
            bubble[:40],
            intent,
        )
        await self._send(
            event,
            result,
            state=state,
            is_private=is_private,
            poke_user_id=info.sender_id,
            poke_group_id=info.group_id,
        )
        try:
            event.stop_event()
        except Exception:
            pass
        return None

    async def handle(self, event: AstrMessageEvent, trigger: str):
        perception = perceive(
            event,
            trigger=trigger,
            wake_words=self.wake_words(),
            rest_keywords=(self.config.get("rest") or {}).get("keywords"),
        )

        if perception.group_id:
            if self._group_enabled.get(str(perception.group_id), True) is False:
                return None

        key = self._key(perception.user_id, perception.channel)
        state = self.form_resolver.update(
            self._state(perception.user_id, perception.channel),
            perception,
            card=self.card,
        )
        self._states[key] = state

        group_enabled = True
        if perception.group_id:
            group_enabled = self._group_enabled.get(str(perception.group_id), True)

        decision: Decision = decide(perception, state, self.config, group_enabled=group_enabled)

        logger.info(
            "companion 决策=%s 原因=%s 形态=%s 触发=%s 频道=%s 媒体=%s",
            decision.action, decision.reason, state.active_form, trigger, perception.channel,
            perception.media_note or "无",
        )
        if decision.action == "SILENCE":
            self._apply_anchors(perception)
            try:
                self._record_observation(
                    perception,
                    form=state.active_form,
                    observed=True,
                )
            except Exception as e:
                logger.warning("旁观记录写入失败: %s", e)
            return None

        gate_key = str(perception.channel or f"user:{perception.user_id}")
        conc = self.config.get("concurrency") or {}
        global_max = int(conc.get("global_max") or 0)
        # per_group>0 启用同频道容量 1；忙则提示，不排队
        gate_on = int(conc.get("per_group") if conc.get("per_group") is not None else 1) > 0
        if gate_on and not await self.turn_gate.try_acquire(gate_key, global_max=global_max):
            await self._send_busy_tip(event, perception)
            return None

        reply_quote = {"id": self._event_message_id(event), "used": False}
        try:
            # 深夜挂机短句：不走 LLM，直接变体池
            if decision.reason == "night_afk":
                line = pick_variant("night_afk")
                result = ExpressResult(bubbles=[line], degraded=False)
                try:
                    self._record_observation(
                        perception,
                        reply=line[:120],
                        form=state.active_form,
                    )
                except Exception as e:
                    logger.warning("情景记忆写入失败: %s", e)
                if perception.group_id:
                    cd = float((self.config.get("group") or {}).get("cooldown_sec") or 8)
                    self._group_cd[str(perception.group_id)] = time.time() + cd
                return await self._send(
                    event,
                    result,
                    state=state,
                    is_private=perception.is_private,
                    force_voice=False,
                    reply_quote_id=None if reply_quote["used"] else reply_quote["id"],
                    reply_quote_state=reply_quote,
                )

            group_cfg = self.config.get("group") or {}
            dedupe_sec = float(group_cfg.get("dedupe_sec") or 45)
            user_cd = float(
                group_cfg.get("user_cooldown_sec")
                if group_cfg.get("user_cooldown_sec") is not None
                else (group_cfg.get("cooldown_sec") or 8)
            )
            rate_hit = self.rate_limiter.check(
                channel=perception.channel,
                user_id=perception.user_id,
                text=perception.text or "",
                dedupe_sec=dedupe_sec,
                user_cooldown_sec=user_cd,
            )
            if rate_hit:
                logger.info(
                    "companion 限流=%s 频道=%s 用户=%s",
                    rate_hit.reason,
                    perception.channel,
                    perception.user_id,
                )
                self._apply_anchors(perception)
                try:
                    self._record_observation(
                        perception,
                        form=state.active_form,
                        observed=True,
                    )
                except Exception as e:
                    logger.warning("限流旁观记录写入失败: %s", e)
                return None

            self.rate_limiter.commit(
                channel=perception.channel,
                user_id=perception.user_id,
                text=perception.text or "",
                dedupe_sec=dedupe_sec,
                user_cooldown_sec=user_cd,
            )

            self.tool_bridge.begin_turn(card=self.card)

            self._apply_anchors(perception)
            memory_block = self.memory.inject_block(
                perception.user_id,
                perception.channel,
                max_chars=int(
                    (self.config.get("memory") or {}).get("portrait_inject_max_chars") or 400
                ),
            )
            memory_block = self._with_pending_reminders(
                memory_block,
                user_id=perception.user_id,
                group_id=perception.group_id,
            )
            allow_tags = list(self.card.companion_ext.get("sticker_tags") or self.stickers.allow_tags)

            mem_cfg = self.config.get("memory") or {}
            # 群聊默认拉更长滑动窗，便于接话
            default_before = 10 if perception.group_id else 3
            nearby = self.memory.nearby_context(
                perception.user_id,
                perception.channel,
                before_n=int(mem_cfg.get("nearby_before") or default_before),
                after_n=int(mem_cfg.get("nearby_after") or 3),
                current_text=perception.text or "",
            )
            force_voice = self._detect_force_voice(perception, nearby)
            # 纯「用语音说某句」：关掉工具，避免点歌/搜旧话题串戏
            voice_speak_only = force_voice and not is_song_tool_intent(perception.text or "")
            if voice_speak_only:
                decision = Decision(decision.action, decision.reason, allow_tools=False)
                # 念白回合只留画像，去掉群 tape/episodic 里「她回过 CosyVoice」之类长串
                memory_block = self.memory.inject_block(
                    perception.user_id,
                    perception.channel,
                    max_chars=int(
                        (self.config.get("memory") or {}).get("portrait_inject_max_chars") or 400
                    ),
                    portrait_only=True,
                )

            if perception.group_id:
                neighbor_ids = [
                    str(item.get("user_id") or "")
                    for item in (nearby.get("before") or [])
                    if item.get("user_id")
                ]
                card_block = self.member_cards.inject_block(
                    str(perception.group_id),
                    perception.user_id,
                    neighbor_ids=neighbor_ids,
                    max_neighbors=3,
                )
                if card_block:
                    memory_block = (
                        f"{memory_block}\n{card_block}".strip()
                        if memory_block
                        else card_block
                    )

            tool_plan = plan_tool_order(perception, state, decision, self.config)
            preface_sink: list[str] = []
            typed_once = {"done": False}
            at_name_map: dict[str, str] = {}
            if perception.group_id:
                try:
                    at_name_map = self.member_cards.build_at_name_index(str(perception.group_id))
                except Exception as e:
                    logger.warning("companion @名索引失败: %s", e)

            async def send_preface(bubble: str) -> None:
                clean = sanitize_outbound_text(
                    bubble, strip_asterisk_actions=self._strip_asterisk_actions()
                )
                if not clean:
                    return
                # 同轮工具前言勿连发相同句
                if preface_sink and preface_sink[-1] == clean:
                    return
                if not typed_once["done"]:
                    await self._typing_delay([clean])
                    typed_once["done"] = True
                else:
                    lo, hi = self._bubble_jitter_ms()
                    await self._sleep_jitter(lo, hi)
                rid = None if reply_quote["used"] else reply_quote["id"]
                await send_bubble_with_ats(event, clean, name_to_qq=at_name_map, reply_id=rid)
                if rid not in (None, ""):
                    reply_quote["used"] = True
                preface_sink.append(clean)

            logger.info(
                "companion 工具序=%s 原因=%s 强制语音=%s 上文=%s 下文=%s",
                tool_plan.order,
                tool_plan.reason,
                force_voice,
                len(nearby.get("before") or []),
                len(nearby.get("after") or []),
            )

            result: ExpressResult = await self.expressor.run(
                self.card,
                state,
                perception,
                memory_block,
                decision,
                allow_tags,
                event=event,
                tool_plan=tool_plan,
                send_preface=send_preface,
                preface_sink=preface_sink,
                force_voice=force_voice,
                nearby=nearby,
                recent_sticker_intents=self.stickers.recent_intents(5),
            )

            # 发送前清洗（与 _send 内二次确认；此处更新 result 供记忆/日志一致）
            expr_cfg = self.config.get("express") or {}
            style_hints = (
                ((self.card.companion_ext.get("forms") or {}).get(state.active_form) or {}).get(
                    "style_hints"
                )
                or {}
            )
            result.bubbles = finalize_outbound_bubbles(
                result.bubbles,
                max_bubbles=int(style_hints.get("max_bubbles") or expr_cfg.get("max_bubbles", 3)),
                max_chars=int(style_hints.get("max_chars") or expr_cfg.get("max_chars", 120)),
                fallback=(expr_cfg.get("fallback_message")) or pick_fallback(),
                skip=result.preface_bubbles,
                strip_asterisk_actions=self._strip_asterisk_actions(),
            )
            if result.preface_bubbles:
                result.preface_bubbles = finalize_outbound_bubbles(
                    result.preface_bubbles,
                    max_bubbles=2,
                    max_chars=int(style_hints.get("max_chars") or expr_cfg.get("max_chars", 120)),
                    fallback="",
                    strip_asterisk_actions=self._strip_asterisk_actions(),
                )
            self._scrub_safety_refusal_bubbles(result, expr_cfg)

            # 选图在记日志前完成，便于审计 match_stage / score
            # 降级/纯兜底句不发表情，避免「呜不太行」还配一张图
            if result.degraded or self._is_fallback_only_bubbles(result, expr_cfg):
                result.degraded = True
                result.sticker_wanted = False
                result.sticker_path = None
                result.sticker_id = None
                result.sticker_match_stage = "gated"
                result.poke_wanted = False
                self.stickers.stats.record("gated", "degraded")
                logger.info("companion 表情包 跳过（降级/兜底）")
            else:
                if not result.sticker_wanted or result.sticker_intent in ("", "none"):
                    result.sticker_wanted = True
                    result.sticker_intent = self._fallback_sticker_intent(
                        result.sticker_intent, allow_tags, state
                    )
                if result.sticker_wanted:
                    picked = self.stickers.pick_detailed(
                        wanted=True, intent=result.sticker_intent, active_form=state.active_form
                    )
                    result.sticker_match_stage = picked.stage
                    result.sticker_score = float(picked.score or 0.0)
                    if picked.stage == "sent" and picked.path:
                        result.sticker_id = picked.sticker_id
                        result.sticker_path = picked.path
                    logger.info(
                        "companion 表情包 意图=%s 阶段=%s 分数=%.2f id=%s",
                        result.sticker_intent or "none",
                        picked.stage,
                        float(picked.score or 0.0),
                        picked.sticker_id or "-",
                    )
                else:
                    result.sticker_match_stage = "gated"
                    self.stickers.stats.record("gated", result.sticker_intent or "none")

            self.turn_logger.log_turn(
                trigger=trigger,
                perception=perception,
                decision=decision,
                state=state,
                result=result,
                character_id=self.card.id,
            )

            try:
                if not result.degraded:
                    reply = " / ".join([*result.preface_bubbles, *result.bubbles])[:120]
                    reply = strip_at_markers(strip_refusal_from_joined(reply)) or reply[:120]
                    self._record_observation(
                        perception,
                        reply=reply,
                        form=state.active_form,
                        tools=result.tools_used,
                    )
            except Exception as e:
                logger.warning("情景记忆写入失败: %s", e)

            if perception.group_id:
                cd = float((self.config.get("group") or {}).get("cooldown_sec") or 8)
                self._group_cd[str(perception.group_id)] = time.time() + cd

            return await self._send(
                event,
                result,
                state=state,
                is_private=perception.is_private,
                force_voice=force_voice,
                poke_user_id=perception.user_id,
                poke_group_id=perception.group_id,
                at_name_map=at_name_map,
                reply_quote_id=None if reply_quote["used"] else reply_quote["id"],
                reply_quote_state=reply_quote,
            )
        finally:
            if gate_on:
                await self.turn_gate.release(gate_key)


    async def _send(
        self,
        event: AstrMessageEvent,
        result: ExpressResult,
        *,
        state: InnerState | None = None,
        is_private: bool = False,
        force_voice: bool = False,
        poke_user_id: str | None = None,
        poke_group_id: str | None = None,
        at_name_map: dict[str, str] | None = None,
        reply_quote_id: str | int | None = None,
        reply_quote_state: dict[str, Any] | None = None,
    ):
        expr = self.config.get("express") or {}
        style = {}
        if state is not None:
            style = (
                ((self.card.companion_ext.get("forms") or {}).get(state.active_form) or {}).get(
                    "style_hints"
                )
                or {}
            )
        max_bubbles = int(style.get("max_bubbles") or expr.get("max_bubbles", 3))
        max_chars = int(style.get("max_chars") or expr.get("max_chars", 120))
        fallback = (expr.get("fallback_message")) or pick_fallback()

        result.bubbles = finalize_outbound_bubbles(
            result.bubbles,
            max_bubbles=max_bubbles,
            max_chars=max_chars,
            fallback=fallback,
            skip=result.preface_bubbles,
            strip_asterisk_actions=self._strip_asterisk_actions(),
        )
        if result.preface_bubbles:
            result.preface_bubbles = finalize_outbound_bubbles(
                result.preface_bubbles,
                max_bubbles=2,
                max_chars=max_chars,
                fallback="",
                strip_asterisk_actions=self._strip_asterisk_actions(),
            )

        # 首条气泡前打字延迟（若本回合已有 preface，那边已经等过）
        if not result.preface_bubbles and result.bubbles:
            await self._typing_delay(result.bubbles)

        keep_text = bool((self.config.get("voice") or {}).get("keep_text", True))
        want_voice = (
            (not result.degraded)
            and self.voice.should_speak(is_private=is_private, force=force_voice)
        )

        lo, hi = self._bubble_jitter_ms()
        name_map = at_name_map or {}
        quote_state = reply_quote_state if reply_quote_state is not None else {
            "id": reply_quote_id,
            "used": reply_quote_id in (None, ""),
        }
        try:
            if keep_text or not want_voice:
                for i, bubble in enumerate(result.bubbles):
                    if i > 0:
                        await self._sleep_jitter(lo, hi)
                    rid = None if quote_state.get("used") else quote_state.get("id")
                    await send_bubble_with_ats(
                        event, bubble, name_to_qq=name_map, reply_id=rid
                    )
                    if rid not in (None, ""):
                        quote_state["used"] = True
            if want_voice and result.bubbles:
                if keep_text:
                    await self._sleep_jitter(lo, hi)
                voice_bubbles = [
                    strip_at_markers(b, name_to_qq=name_map) or b for b in result.bubbles
                ]
                await self.voice.send_voice(
                    event,
                    voice_bubbles,
                    full=force_voice,
                    emotion=result.voice_emotion or None,
                )
            if (
                not result.degraded
                and result.sticker_path
                and os.path.isfile(result.sticker_path)
            ):
                if result.bubbles or keep_text:
                    await self._sleep_jitter(lo, hi)
                await event.send(CommandResult().file_image(os.path.abspath(result.sticker_path)))
            if poke_user_id is not None:
                await self._maybe_poke_user(
                    event,
                    user_id=poke_user_id,
                    group_id=poke_group_id,
                    result=result,
                )
            return None
        except Exception as e:
            logger.error("companion 发送失败: %s", e)
            safe = finalize_outbound_bubbles(
                result.bubbles,
                max_bubbles=max_bubbles,
                max_chars=max_chars,
                fallback=fallback,
                strip_asterisk_actions=self._strip_asterisk_actions(),
            )
            return CommandResult().message("\n".join(safe))

    @staticmethod
    def _event_message_id(event: AstrMessageEvent) -> str | int | None:
        try:
            msg = getattr(event, "message_obj", None)
            mid = getattr(msg, "message_id", None) if msg else None
            if mid not in (None, "", 0, "0"):
                return mid
        except Exception:
            pass
        try:
            if hasattr(event, "get_message_id"):
                mid = event.get_message_id()
                if mid not in (None, "", 0, "0"):
                    return mid
        except Exception:
            pass
        return None

    async def _send_busy_tip(
        self,
        event: AstrMessageEvent,
        perception: Perception,
    ) -> None:
        """同频道令牌占用中：引用对方消息提示稍等。"""
        tip = pick_variant("busy") or "稍等下嘛，我还在回上一条~"
        who = (perception.sender_name or "").strip()
        if who:
            tip = f"{tip}"
        mid = self._event_message_id(event)
        try:
            await send_bubble_with_ats(event, tip, reply_id=mid)
            logger.info(
                "companion 忙线提示 channel=%s user=%s",
                perception.channel,
                perception.user_id,
            )
        except Exception as e:
            logger.warning("companion 忙线提示失败: %s", e)
        try:
            self._record_observation(
                perception,
                form=self._state(perception.user_id, perception.channel).active_form,
                observed=True,
            )
        except Exception:
            pass

    async def _maybe_poke_user(
        self,
        event: AstrMessageEvent,
        *,
        user_id: str,
        group_id: str | None,
        result: ExpressResult,
    ) -> None:
        poke_cfg = self.config.get("poke") or {}
        if poke_cfg.get("enabled", True) is False:
            return
        if not result.poke_wanted or result.degraded:
            return
        if not user_id:
            return
        cd_key = f"out:{group_id or 'private'}:{user_id}"
        cd = float(poke_cfg.get("outgoing_cooldown_sec") or 8)
        now = time.time()
        if now < self._poke_cd.get(cd_key, 0):
            return
        delay = poke_cfg.get("outgoing_delay_ms") or [400, 1200]
        if isinstance(delay, (list, tuple)) and len(delay) >= 2:
            delay_ms = (int(delay[0]), int(delay[1]))
        else:
            delay_ms = (400, 1200)
        ok = await send_poke_with_pause(
            event,
            user_id=user_id,
            group_id=group_id,
            delay_ms=delay_ms,
        )
        if ok:
            self._poke_cd[cd_key] = now + cd

    async def _typing_delay(self, bubbles: list[str]) -> None:
        ms = typing_delay_ms(
            bubbles,
            self.config,
            night=is_night_hours(self.config),
        )
        if ms <= 0:
            return
        await asyncio.sleep(ms / 1000.0)

    def _bubble_jitter_ms(self) -> tuple[int, int]:
        expr = self.config.get("express") or {}
        raw = expr.get("bubble_jitter_ms")
        if raw is None:
            raw = (self.config.get("group") or {}).get("reply_jitter_ms")
        if not raw or len(raw) < 2:
            return 600, 2200
        lo, hi = int(raw[0]), int(raw[1])
        if lo <= 0 and hi <= 0:
            return 0, 0
        if lo > hi:
            lo, hi = hi, lo
        return lo, hi

    @staticmethod
    async def _sleep_jitter(lo_ms: int, hi_ms: int) -> None:
        if lo_ms <= 0 and hi_ms <= 0:
            return
        lo, hi = (lo_ms, hi_ms) if lo_ms <= hi_ms else (hi_ms, lo_ms)
        await asyncio.sleep(random.uniform(lo, hi) / 1000.0)

    def _detect_force_voice(
        self,
        perception: Perception,
        nearby: dict[str, list[dict[str, str]]],
    ) -> bool:
        if self.voice.detect_force(perception.text or ""):
            return True
        # 仅当本条像「接上文」（只喊娅娅 / 极短），才继承上一句同人的强制语音
        if not self._is_voice_continuation(perception.text or ""):
            return False
        uid = str(perception.user_id)
        for item in reversed(nearby.get("before") or []):
            if str(item.get("user_id") or "") not in ("", uid):
                continue
            return self.voice.detect_force(item.get("text") or "")
        return False

    def _is_voice_continuation(self, text: str) -> bool:
        """去掉唤醒词后几乎没内容 → 视为接上文，可继承「用语音」。"""
        t = (text or "").strip()
        if not t:
            return True
        for w in self.wake_words():
            if w:
                t = t.replace(w, " ")
        t = re.sub(r"\s+", "", t)
        t = re.sub(r"[….。，,!~～？\?！\s…·\-—_]", "", t)
        return len(t) <= 2

    @staticmethod
    def _fallback_sticker_intent(
        current: str,
        allow_tags: list[str],
        state: InnerState,
    ) -> str:
        from ..stickers.tags import resolve_tag

        allow = {str(t).lower() for t in allow_tags}
        tag = resolve_tag(current or "")
        if tag and tag in allow:
            return tag
        mood_map = {
            "happy": "happy",
            "sad": "sad",
            "angry": "angry",
            "neutral": "playful",
        }
        mood_tag = mood_map.get((state.mood or "").lower())
        if mood_tag and mood_tag in allow:
            return mood_tag
        for pick in ("playful", "warm", "happy", "tease"):
            if pick in allow:
                return pick
        return allow_tags[0] if allow_tags else "playful"

    def _group_tape_enabled(self) -> bool:
        return bool((self.config.get("memory") or {}).get("group_tape_enabled", True))

    @staticmethod
    def _observation_text(perception: Perception) -> tuple[str, str]:
        text = (perception.text[:200] or perception.media_note[:200] or "")
        summary = (perception.text[:80] or perception.media_note[:80] or "（媒体）")
        return text, summary

    def _apply_anchors(self, perception: Perception) -> None:
        for anchor_key, anchor_val in extract_anchors(perception.text or ""):
            self.memory.upsert_anchor(perception.user_id, anchor_key, anchor_val)

    def _scrub_safety_refusal_bubbles(
        self, result: ExpressResult, expr_cfg: dict[str, Any]
    ) -> None:
        """上游安全拒答不进记忆；出站改人设兜底，避免冷冰冰模板污染下轮上下文。"""
        fallback = (expr_cfg.get("fallback_message")) or pick_fallback()
        hit = False
        cleaned_preface: list[str] = []
        for b in result.preface_bubbles or []:
            if is_upstream_safety_refusal(b):
                hit = True
                continue
            cleaned_preface.append(b)
        result.preface_bubbles = cleaned_preface
        cleaned_bubbles: list[str] = []
        for b in result.bubbles or []:
            if is_upstream_safety_refusal(b):
                hit = True
                continue
            cleaned_bubbles.append(b)
        if hit:
            logger.info("companion 已拦截上游安全拒答文案，不写入记忆")
            result.bubbles = cleaned_bubbles or ([fallback] if not cleaned_preface else [])
            # 拒答被换成兜底：按降级处理，勿再硬塞表情
            if not cleaned_bubbles and not cleaned_preface:
                result.degraded = True

    @staticmethod
    def _is_fallback_only_bubbles(result: ExpressResult, expr_cfg: dict[str, Any]) -> bool:
        """正文只剩配置/变体兜底句时，视为失败收尾。"""
        configured = ((expr_cfg.get("fallback_message")) or "").strip()
        from ..variants import POOLS

        pool = {str(x).strip() for x in (POOLS.get("fallback") or []) if str(x).strip()}
        if configured:
            pool.add(configured)
        texts = [str(b).strip() for b in (result.bubbles or []) if str(b).strip()]
        if result.preface_bubbles:
            return False
        if not texts:
            return True
        return len(texts) == 1 and texts[0] in pool

    def _record_observation(
        self,
        perception: Perception,
        *,
        reply: str = "",
        form: str | None = None,
        tools: list[str] | None = None,
        observed: bool = False,
    ) -> None:
        text, summary = self._observation_text(perception)
        if not text and not summary:
            return

        speaker = (perception.sender_name or perception.user_id)[:32]
        mem_cfg = self.config.get("memory") or {}
        quota_epi = int(mem_cfg.get("quota_episodic") or 500)

        if perception.group_id and perception.sender_name:
            try:
                self.member_cards.touch_display_name(
                    str(perception.group_id),
                    perception.user_id,
                    perception.sender_name,
                )
            except Exception as e:
                logger.warning("群友卡更新失败: %s", e)

        if perception.group_id and self._group_tape_enabled():
            tape_item: dict[str, Any] = {
                "ts": time.time(),
                "user_id": perception.user_id,
                "speaker": speaker,
                "text": text,
                "summary": summary,
            }
            if reply:
                tape_item["reply"] = reply[:120]
            elif observed:
                tape_item["observed"] = True
            self.memory.append_group_tape(str(perception.group_id), tape_item)

        write_episodic = (not perception.group_id) or bool(reply)
        if not write_episodic:
            return

        episodic: dict[str, Any] = {
            "ts": time.time(),
            "text": text,
            "summary": summary,
            "reply": reply[:120] if reply else "",
            "form": form or (self.card.companion_ext.get("default_form") if self.card else None) or "default",
        }
        if observed and not reply:
            episodic["observed"] = True
        if perception.has_visual:
            episodic["media"] = perception.media_note[:80]
        if tools:
            episodic["tools"] = ",".join(tools[:5])

        mark_dirty = bool(reply)
        self.memory.append_episodic(
            perception.user_id,
            perception.channel,
            episodic,
            quota=quota_epi,
            mark_dirty=mark_dirty,
        )
        if mark_dirty:
            self.portrait_job.maybe_schedule(perception.user_id)
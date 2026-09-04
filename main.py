"""Companion — AstrBot social character plugin (persona harness)."""
from __future__ import annotations

import logging
import os
import re
from typing import Optional

from astrbot.api.all import At, CommandResult
from astrbot.api.event import AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.core.star.star_handler import EventType, StarHandlerMetadata, star_handlers_registry

from .companion.canned import (
    ADMIN_ADDED,
    ADMIN_CANNOT_SELF_SUPER,
    ADMIN_EXISTS,
    ADMIN_LIST_EMPTY,
    ADMIN_NEED_TARGET,
    ADMIN_NO_PERM,
    ADMIN_NOT_FOUND,
    ADMIN_REMOVED,
    GROUP_OFF,
    GROUP_ON,
    GROUP_ONLY_OFF,
    GROUP_ONLY_ON,
    MEMORY_CLEARED,
    MEMORY_CLEAR_SELF_ONLY,
    PORTRAIT_EMPTY,
    PORTRAIT_NO_PERM,
    PORTRAIT_PRIVATE_ONLY,
    PORTRAIT_REFRESH_FAIL,
    PORTRAIT_REFRESH_OK,
    STICKERS_RELOADED,
    STICKERS_CATALOG_EMPTY,
    STICKERS_CATALOG_OK,
    STICKERS_CATALOG_CACHED,
    STICKERS_UPLOAD_NO_PERM,
    STICKERS_UPLOAD_OK,
    STICKERS_UPLOAD_OK_MULTI,
    stickers_upload_usage,
)
from .companion.cmd_alias import HELP_TEXT, PLUGIN_PREFIX_RE, resolve_command_args
from .companion.config_loader import load_config
from .companion.env_loader import bootstrap_plugin_env
from .companion.harness.pipeline import HarnessPipeline
from .companion.platform.filters import AtFilter, GroupObserveFilter, PokeFilter, PrivateFilter
from .companion.tools.adapters import AdapterRegistry

logger = logging.getLogger("astrbot")


@register("companion", "Origami", "社交真实感角色插件（人设外置）", "0.3.0")
class CompanionPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.context = context
        self.plugin_root = os.path.dirname(os.path.abspath(__file__))
        self.data_dir = os.path.join(self.plugin_root, "data")
        os.makedirs(self.data_dir, exist_ok=True)

        bootstrap_plugin_env(self.plugin_root)
        # AstrBot 面板配置（扁平键）；load_config 产出运行时嵌套 dict
        self.astrbot_config = config
        self.config = load_config(config, self.plugin_root, self.data_dir)
        self.adapters = AdapterRegistry(context, self.config)
        self.adapters.register_all()
        self.pipeline = HarnessPipeline(
            context=context,
            config=self.config,
            plugin_root=self.plugin_root,
            data_dir=self.data_dir,
            adapters=self.adapters,
            astrbot_config=self.astrbot_config,
        )
        self._register_handlers()
        self._register_commands()
        self.pipeline.start_background()
        logger.info(
            "companion 已加载 角色=%s 供应商=%s",
            self.config.get("active_character"),
            self.pipeline.provider.readiness(),
        )

    async def terminate(self):
        try:
            await self.pipeline.stop_background()
        except Exception as e:
            logger.warning("companion 后台停止失败: %s", e)

    def _register_handlers(self) -> None:
        mod = self.__module__
        # 重载插件时去掉旧 handler，避免 star_request 找不到对应 plugin 实例
        for handler in list(star_handlers_registry.get_handlers_by_module_name(mod)):
            star_handlers_registry.remove(handler)
        for key in list(star_handlers_registry.star_handlers_map):
            if key.startswith(f"{mod}_"):
                del star_handlers_registry.star_handlers_map[key]
        specs = [
            ("_handle_poke", self._handle_poke, PokeFilter(self), "companion poke"),
            ("_handle_at", self._handle_at, AtFilter(self), "companion hard @"),
            ("_handle_private", self._handle_private, PrivateFilter(self), "companion private"),
            ("_handle_group", self._handle_group, GroupObserveFilter(self), "companion group soft"),
        ]
        for name, handler, filt, desc in specs:
            star_handlers_registry.append(
                StarHandlerMetadata(
                    event_type=EventType.AdapterMessageEvent,
                    handler_full_name=f"{self.__module__}_{name.lstrip('_')}",
                    handler_name=name,
                    handler_module_path=self.__module__,
                    handler=handler,
                    event_filters=[filt],
                    desc=desc,
                )
            )

    def _register_commands(self) -> None:
        reg = self.context.register_commands
        _common = dict(use_regex=True, ignore_prefix=True)
        reg(
            "companion",
            rf"(?i)^/?{PLUGIN_PREFIX_RE}\s*(.*)$",
            "Companion 管理命令",
            1,
            self.cmd_companion,
            **_common,
        )
        # 短指令：上传害羞 / 上传疲惫https://…gif
        reg(
            "companion",
            r"(?i)^/?上传.*$",
            "上传表情包",
            1,
            self.cmd_sticker_upload,
            **_common,
        )
        # 短指令：表情统计 / 情绪统计
        reg(
            "companion",
            r"(?i)^/?(?:表情包?统计|情绪统计)\s*(清零)?\s*$",
            "表情情绪统计",
            1,
            self.cmd_emotion_stats,
            **_common,
        )
        reg(
            "companion",
            r"(?i)^/?(?:清除记忆|清空记忆)\s*$",
            "清除记忆",
            1,
            self.cmd_clear_memory,
            **_common,
        )
        reg(
            "companion",
            r"(?i)^/?(?:表情图鉴|表情一览|表情包?图鉴)\s*$",
            "表情包图鉴",
            1,
            self.cmd_sticker_catalog,
            **_common,
        )

        reg(
            "companion",
            r"(?i)^/?.*(?:添加管理员|加管理员|删除管理员|移除管理员|管理员名单|查看管理员).*$",
            "管理员增删",
            1,
            self.cmd_admin_short,
            **_common,
        )

    async def cmd_sticker_catalog(self, context, event: AstrMessageEvent):
        try:
            info = self.pipeline.build_sticker_catalog_image()
        except ValueError:
            return CommandResult().message(STICKERS_CATALOG_EMPTY)
        except ImportError:
            return CommandResult().message(
                "生成图鉴需要 Pillow：pip install pillow"
            )
        except Exception as e:
            logger.warning("companion 表情包图鉴失败: %s", e, exc_info=True)
            return CommandResult().message(f"图鉴生成失败了……{e}")
        path = os.path.abspath(info["path"])
        tpl = STICKERS_CATALOG_CACHED if info.get("cached") else STICKERS_CATALOG_OK
        cap = tpl.format(
            n=info.get("count", 0),
            tags=info.get("tags", 0),
            w=info.get("width", 0),
            h=info.get("height", 0),
        )
        return CommandResult().message(cap).file_image(path)

    async def _handle_at(self, context, event: AstrMessageEvent):
        return await self.pipeline.handle(event, trigger="hard_mention")

    async def _handle_poke(self, context, event: AstrMessageEvent):
        return await self.pipeline.handle_poke(event)

    async def _handle_private(self, context, event: AstrMessageEvent):
        return await self.pipeline.handle(event, trigger="private")

    async def _handle_group(self, context, event: AstrMessageEvent):
        return await self.pipeline.handle(event, trigger="group_observe")

    async def cmd_sticker_upload(self, context, event: AstrMessageEvent):
        if not _is_admin(event, self.config):
            return CommandResult().message(STICKERS_UPLOAD_NO_PERM)
        tag, urls = _parse_upload_parts(event)
        if not tag:
            return CommandResult().message(stickers_upload_usage())
        return await self._do_sticker_upload(event, tag, image_urls=urls)

    async def cmd_emotion_stats(self, context, event: AstrMessageEvent):
        text = _event_text(event)
        if re.search(r"清零", text or ""):
            if not _is_admin(event, self.config):
                return CommandResult().message(STICKERS_UPLOAD_NO_PERM)
            return CommandResult().message(self.pipeline.reset_sticker_stats())
        return CommandResult().message(self.pipeline.sticker_stats())

    async def cmd_clear_memory(self, context, event: AstrMessageEvent):
        uid = str(event.get_sender_id())
        self.pipeline.clear_user_memory(uid)
        return CommandResult().message(MEMORY_CLEARED)

    async def cmd_admin_short(self, context, event: AstrMessageEvent):
        text = _event_text(event)
        tail = re.sub(r"^/?", "", text or "").strip()
        args = resolve_command_args(tail)
        if not args or args[0] != "admin":
            return CommandResult().message(
                "用法：添加管理员 @某人  或  @某人 添加管理员；删除同理"
            )
        return self._cmd_admin(event, args[1:])

    async def _do_sticker_upload(
        self, event: AstrMessageEvent, tag: str, *, image_urls: list[str] | None = None
    ):
        try:
            info = await self.pipeline.upload_sticker(
                event, tag, image_urls=image_urls or []
            )
        except ValueError as e:
            return CommandResult().message(str(e))
        except Exception as e:
            logger.warning("companion 表情包上传失败: %s", e)
            return CommandResult().message(f"上传失败了……{e}")
        src = info.get("source") or "message"
        if src == "reply":
            source = "引用"
        elif src == "url":
            source = "链接"
        elif src == "mixed":
            source = "混合"
        else:
            source = "本条"
        ids = list(info.get("sticker_ids") or [])
        count = int(info.get("count") or len(ids) or 1)
        n = info.get("total") or 0
        if count <= 1:
            return CommandResult().message(
                STICKERS_UPLOAD_OK.format(
                    id=(ids[0] if ids else info.get("sticker_id") or "?"),
                    source=source,
                    n=n,
                )
            )
        show = ids[:5]
        ids_bit = "、".join(show)
        if len(ids) > 5:
            ids_bit += f"…(+{len(ids) - 5})"
        return CommandResult().message(
            STICKERS_UPLOAD_OK_MULTI.format(
                count=count,
                ids=ids_bit,
                source=source,
                n=n,
            )
        )

    async def cmd_companion(self, context, event: AstrMessageEvent):
        tail = _parse_companion_tail(event)
        args = resolve_command_args(tail)
        sub = args[0] if args else "status"
        if sub in ("help",):
            return CommandResult().message(HELP_TEXT)
        if sub == "status":
            brief = bool(_group_id(event))
            return CommandResult().message(
                self.pipeline.status_summary(brief=brief)
            )
        if sub == "on":
            gid = _group_id(event)
            if not gid:
                return CommandResult().message(GROUP_ONLY_ON)
            self.pipeline.set_group_enabled(gid, True)
            return CommandResult().message(GROUP_ON)
        if sub == "off":
            gid = _group_id(event)
            if not gid:
                return CommandResult().message(GROUP_ONLY_OFF)
            self.pipeline.set_group_enabled(gid, False)
            return CommandResult().message(GROUP_OFF)
        if sub == "stickers":
            action = args[1] if len(args) >= 2 else "stats"
            if action == "reload":
                n = self.pipeline.reload_stickers()
                return CommandResult().message(STICKERS_RELOADED.format(n=n))
            if action == "stats" and len(args) >= 3 and args[2] == "reset":
                if not _is_admin(event, self.config):
                    return CommandResult().message(STICKERS_UPLOAD_NO_PERM)
                return CommandResult().message(self.pipeline.reset_sticker_stats())
            if action == "stats":
                return CommandResult().message(self.pipeline.sticker_stats())
            if action == "catalog":
                return await self.cmd_sticker_catalog(context, event)
            if action in ("upload", "add"):
                if not _is_admin(event, self.config):
                    return CommandResult().message(STICKERS_UPLOAD_NO_PERM)
                raw_tail = " ".join(args[2:]) if len(args) >= 3 else ""
                tag, urls = _split_tag_and_url(raw_tail)
                if not tag:
                    return CommandResult().message(stickers_upload_usage())
                return await self._do_sticker_upload(event, tag, image_urls=urls)
            return CommandResult().message(
                "表情：重载 / 统计 / 图鉴 / 统计 清零 / 上传 <情绪>"
            )
        if sub == "emotions":
            if len(args) >= 2 and args[1] == "reset":
                if not _is_admin(event, self.config):
                    return CommandResult().message(STICKERS_UPLOAD_NO_PERM)
                return CommandResult().message(self.pipeline.reset_sticker_stats())
            return CommandResult().message(self.pipeline.sticker_stats())
        if sub == "tools":
            return CommandResult().message(self.pipeline.tools_list_text())
        if sub == "adapters":
            return CommandResult().message(self.pipeline.adapters_status_text())
        if sub == "portrait":
            action = args[1] if len(args) >= 2 else "show"
            if action == "show":
                if _group_id(event):
                    return CommandResult().message(PORTRAIT_PRIVATE_ONLY)
                uid = str(event.get_sender_id())
                return CommandResult().message(
                    self.pipeline.portrait_show(uid) or PORTRAIT_EMPTY
                )
            if action == "refresh":
                target = _resolve_user_target(event, args, idx=2)
                sender = str(event.get_sender_id())
                if target != sender and not _can_manage_user(event, target, self.config):
                    return CommandResult().message(PORTRAIT_NO_PERM)
                ok = await self.pipeline.refresh_portrait(target, force=True)
                if ok:
                    return CommandResult().message(PORTRAIT_REFRESH_OK)
                return CommandResult().message(PORTRAIT_REFRESH_FAIL)
            return CommandResult().message("画像：查看 | 刷新")
        if sub == "voice":
            action = args[1] if len(args) >= 2 else "status"
            if action == "on":
                return CommandResult().message(self.pipeline.set_voice_enabled(True))
            if action == "off":
                return CommandResult().message(self.pipeline.set_voice_enabled(False))
            return CommandResult().message(self.pipeline.voice_status_text())
        if sub in ("provider", "providers", "模型", "供应商"):
            action = args[1] if len(args) >= 2 else "list"
            if action in ("list", "ls", "status", "名单", "列表", "help"):
                return CommandResult().message(self.pipeline.provider_status_text())
            # /伴侣 供应商 claude | 供应商 minimax — 第二段即目标，无需「用」
            target = action
            if action in ("use", "set", "用", "切换", "切"):
                target = args[2] if len(args) >= 3 else ""
            if not target:
                return CommandResult().message(self.pipeline.provider_status_text())
            if not _is_admin(event, self.config):
                return CommandResult().message(ADMIN_NO_PERM)
            try:
                return CommandResult().message(
                    self.pipeline.set_provider_active(target)
                )
            except ValueError as e:
                return CommandResult().message(str(e))
        if sub == "memory":
            if len(args) >= 2 and args[1] == "reset":
                uid = str(event.get_sender_id())
                self.pipeline.clear_user_memory(uid)
                return CommandResult().message(MEMORY_CLEARED)
            return CommandResult().message(
                "清自己的记忆请发：清除记忆  或  /伴侣 清除记忆"
            )
        if sub == "admin":
            return self._cmd_admin(event, args[1:])
        return CommandResult().message(HELP_TEXT)

    def _cmd_admin(self, event: AstrMessageEvent, args: list[str]):
        action = args[0] if args else "list"
        if action in ("list", "show"):
            return CommandResult().message(_format_admin_list(self.config))
        if action == "add":
            if not _is_super(event, self.config):
                return CommandResult().message(ADMIN_NO_PERM)
            target = _resolve_admin_target(event, args, idx=1)
            if not target:
                return CommandResult().message(ADMIN_NEED_TARGET)
            if _is_super_id(target, self.config):
                return CommandResult().message(ADMIN_CANNOT_SELF_SUPER)
            ops = _operator_ids(self.config)
            if target in ops:
                return CommandResult().message(ADMIN_EXISTS.format(uid=target))
            ops.append(target)
            _save_operators(self.config, self.astrbot_config, ops)
            return CommandResult().message(ADMIN_ADDED.format(uid=target))
        if action == "remove":
            if not _is_super(event, self.config):
                return CommandResult().message(ADMIN_NO_PERM)
            target = _resolve_admin_target(event, args, idx=1)
            if not target:
                return CommandResult().message(ADMIN_NEED_TARGET)
            if _is_super_id(target, self.config):
                return CommandResult().message(ADMIN_CANNOT_SELF_SUPER)
            ops = _operator_ids(self.config)
            if target not in ops:
                return CommandResult().message(ADMIN_NOT_FOUND.format(uid=target))
            ops = [x for x in ops if x != target]
            _save_operators(self.config, self.astrbot_config, ops)
            return CommandResult().message(ADMIN_REMOVED.format(uid=target))
        return CommandResult().message(
            "用法：添加管理员 @某人  或  @某人 添加管理员；删除同理\n"
            "名单：管理员名单（增删仅超管）"
        )


def _event_text(event: AstrMessageEvent) -> str:
    try:
        if getattr(event, "message_str", None):
            return event.message_str.strip()
        if hasattr(event, "get_message_str"):
            return (event.get_message_str() or "").strip()
    except Exception:
        pass
    return ""


def _split_tag_and_url(text: str) -> tuple[str, list[str]]:
    """从「疲惫https://…」或「疲惫 https://a https://b」拆出情绪与直链列表。"""
    from .companion.tools.link_intent import extract_urls

    raw = (text or "").strip()
    if not raw:
        return "", []
    urls = extract_urls(raw, limit=32)
    leftover = raw
    for u in urls:
        leftover = leftover.replace(u, " ")
    tag = leftover.strip().split()[0] if leftover.strip() else ""
    return tag, urls


def _parse_upload_parts(event: AstrMessageEvent) -> tuple[str, list[str]]:
    """解析「上传 <情绪> [直链…]」；支持情绪与链接粘连。"""
    try:
        text = _event_text(event)
        m = re.match(r"(?i)^/?上传\s*(.*)$", text)
        if not m:
            return "", []
        return _split_tag_and_url(m.group(1) or "")
    except Exception:
        return "", []


def _parse_upload_tag(event: AstrMessageEvent) -> str:
    tag, _urls = _parse_upload_parts(event)
    return tag


def _parse_companion_tail(event: AstrMessageEvent) -> str:
    try:
        text = _event_text(event)
        m = re.match(rf"(?i)^/?{PLUGIN_PREFIX_RE}\s*(.*)$", text)
        if not m:
            return ""
        return (m.group(1) or "").strip()
    except Exception:
        return ""


def _parse_companion_args(event: AstrMessageEvent) -> list[str]:
    tail = _parse_companion_tail(event)
    return tail.split() if tail else []


def _group_id(event: AstrMessageEvent) -> Optional[str]:
    try:
        if hasattr(event, "get_group_id"):
            gid = event.get_group_id()
            return str(gid) if gid else None
        msg = getattr(event, "message_obj", None)
        gid = getattr(msg, "group_id", None) if msg else None
        return str(gid) if gid else None
    except Exception:
        return None


def _mentions(event: AstrMessageEvent) -> list[str]:
    out: list[str] = []
    try:
        for part in event.get_messages():
            if isinstance(part, At):
                out.append(str(part.qq))
    except Exception:
        pass
    return out


def _resolve_user_target(event: AstrMessageEvent, args: list[str], idx: int = 2) -> str:
    mentions = _mentions(event)
    if mentions:
        return mentions[0]
    if len(args) > idx and args[idx].isdigit():
        return args[idx]
    return str(event.get_sender_id())


def _resolve_admin_target(event: AstrMessageEvent, args: list[str], idx: int = 1) -> str:
    mentions = _mentions(event)
    if mentions:
        return str(mentions[0])
    if len(args) > idx and str(args[idx]).isdigit():
        return str(args[idx])
    return ""


def _super_ids(config: dict) -> list[str]:
    raw = ((config.get("admins") or {}).get("super") or [])
    out: list[str] = []
    seen: set[str] = set()
    for x in raw:
        s = str(x).strip()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _operator_ids(config: dict) -> list[str]:
    adm = config.get("admins") or {}
    # 兼容旧键 list
    raw = adm.get("operators")
    if raw is None:
        raw = adm.get("list") or []
    out: list[str] = []
    seen: set[str] = set()
    supers = set(_super_ids(config))
    for x in raw:
        s = str(x).strip()
        if s and s not in seen and s not in supers:
            seen.add(s)
            out.append(s)
    return out


def _is_super_id(uid: str, config: dict) -> bool:
    return str(uid) in set(_super_ids(config))


def _is_super(event: AstrMessageEvent, config: dict) -> bool:
    return str(event.get_sender_id()) in set(_super_ids(config))


def _is_admin(event: AstrMessageEvent, config: dict) -> bool:
    sender = str(event.get_sender_id())
    if sender in set(_super_ids(config)):
        return True
    if sender in set(_operator_ids(config)):
        return True
    try:
        if hasattr(event, "is_admin") and event.is_admin():
            return True
    except Exception:
        pass
    return False


def _can_manage_user(event: AstrMessageEvent, target_id: str, config: dict) -> bool:
    sender = str(event.get_sender_id())
    if sender == str(target_id):
        return True
    return _is_admin(event, config)


def _format_admin_list(config: dict) -> str:
    supers = _super_ids(config)
    ops = _operator_ids(config)
    lines = ["【companion 权限】"]
    lines.append("超管：" + ("、".join(supers) if supers else "（面板未配置）"))
    if ops:
        lines.append("管理员：" + "、".join(ops))
    else:
        lines.append(ADMIN_LIST_EMPTY)
    lines.append("增删：添加管理员 @某人 / 删除管理员 @某人（仅超管）")
    return "\n".join(lines)


def _save_operators(config: dict, astrbot_config: object | None, ops: list[str]) -> None:
    adm = config.setdefault("admins", {})
    adm["operators"] = list(ops)
    if astrbot_config is None:
        return
    try:
        astrbot_config["管理员QQ号"] = list(ops)
        save = getattr(astrbot_config, "save_config", None)
        if callable(save):
            save()
            logger.info("companion 管理员名单已写入 AstrBot 配置 n=%s", len(ops))
        else:
            logger.warning("companion 管理员名单未能持久化（无 save_config）")
    except Exception as e:
        logger.warning("companion 管理员名单持久化失败: %s", e)

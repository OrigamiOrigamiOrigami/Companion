from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

from . import handlers

logger = logging.getLogger("astrbot")

# (tool_name, description, func_args, handler, adapter_key)
ADAPTER_SPECS: list[tuple[str, str, list, Callable[..., Awaitable[str]], str]] = [
    (
        "image_search_saucenao",
        "对当前消息或引用里的图片做 SauceNAO 以图搜图（需带图）",
        [],
        handlers.image_search_saucenao,
        "image_search",
    ),
    (
        "image_search_ascii2d",
        "对当前消息或引用里的图片做 Ascii2D 以图搜图（需带图）",
        [],
        handlers.image_search_ascii2d,
        "image_search",
    ),
    (
        "image_search_google",
        "对当前消息或引用里的图片做谷歌 Lens 识图（需带图）",
        [],
        handlers.image_search_google,
        "image_search",
    ),
    (
        "jmcomic_search",
        "按标签或标题搜索禁漫本子",
        [
            {"type": "string", "name": "mode", "description": "tag 或 title"},
            {"type": "string", "name": "keyword", "description": "搜索关键词"},
            {"type": "number", "name": "page", "description": "页码，默认 1"},
        ],
        handlers.jmcomic_search,
        "jmcomic",
    ),
    (
        "jmcomic_download",
        "下载禁漫本子为 PDF；用户给出本子 ID（5 位以上数字，如 1087827）或说「看/下/要」某 ID 时用；会先发预览卡再后台下载",
        [{"type": "string", "name": "comic_id", "description": "本子 ID，纯数字"}],
        handlers.jmcomic_download,
        "jmcomic",
    ),
    (
        "setu_send_image",
        "发二次元插画/涩图；用户说「涩涩」「涩图」「好康的」或「来点XX」（XX 为标签如萝莉、白丝）时用。tags 填标签，多个空格分隔；留空随机",
        [{"type": "string", "name": "tags", "description": "图站搜索标签，空格分隔，如「白丝 女仆」。复合名用引号。随机/随便/无具体要素时必须传空字符串 \"\"，不要传「随机」二字"}],
        handlers.setu_send_image,
        "setu",
    ),
    (
        "schedule_reminder",
        "设定延迟提醒/闹钟：N 分钟后到点 @ 对方（可戳一戳）。用户说闹钟、提醒我、几分钟后喊我、到点艾特我时用。无法真正拨打语音电话。",
        [
            {"type": "number", "name": "delay_minutes", "description": "延迟分钟数，可小数"},
            {"type": "number", "name": "delay_seconds", "description": "延迟秒数；与 delay_minutes 二选一，优先秒"},
            {"type": "string", "name": "note", "description": "提醒事由，简短即可；可空"},
            {"type": "boolean", "name": "poke", "description": "到点是否戳一戳，默认 true"},
        ],
        handlers.schedule_reminder,
        "reminder",
    ),
    (
        "cancel_reminder",
        "取消当前用户在本群/私聊未触发的提醒",
        [],
        handlers.cancel_reminder,
        "reminder",
    ),
    (
        "mute_group_member",
        "群禁言：把指定成员禁言一段时间。用户说禁言/闭嘴/口球并 @ 对方或回复其消息时用。机器人需有群管权限。",
        [
            {"type": "string", "name": "user_id", "description": "被禁言 QQ 号；也可留空从 @/回复推断"},
            {"type": "number", "name": "duration_minutes", "description": "禁言分钟数，可小数"},
            {"type": "number", "name": "duration_seconds", "description": "禁言秒数；与分钟二选一，优先秒"},
            {"type": "string", "name": "reason", "description": "事由，可空"},
        ],
        handlers.mute_group_member,
        "mute",
    ),
    (
        "unmute_group_member",
        "解除群禁言。用户说解禁/解除禁言并 @ 对方时用。",
        [
            {"type": "string", "name": "user_id", "description": "要解禁的 QQ 号；可留空从 @/回复推断"},
        ],
        handlers.unmute_group_member,
        "mute",
    ),
]

MUSIC_NATIVE_TOOL = "play_song_by_name"


class AdapterRegistry:
    def __init__(self, context: Any, config: dict[str, Any]):
        self.context = context
        self.adapters_cfg = (config.get("tools") or {}).get("adapters") or {}
        self._registered: list[str] = []

    def register_all(self) -> list[str]:
        if not self.adapters_cfg:
            self.adapters_cfg = {
                "music": True,
                "image_search": True,
                "jmcomic": True,
                "setu": True,
                "reminder": True,
                "mute": True,
            }

        registered: list[str] = []
        if self.adapters_cfg.get("music", True):
            if self._music_available():
                registered.append(f"native:{MUSIC_NATIVE_TOOL}")

        for name, desc, args, handler, key in ADAPTER_SPECS:
            if not self.adapters_cfg.get(key, True):
                continue
            if self._register_one(name, desc, args, handler):
                registered.append(name)

        self._registered = registered
        if registered:
            logger.info("companion 适配器已注册: %s", ", ".join(registered))
        return registered

    def registered_names(self) -> list[str]:
        return list(self._registered)

    def adapter_status_lines(self) -> list[str]:
        lines: list[str] = []
        for key, star_name in (
            ("music", "astrbot_plugin_music"),
            ("image_search", "image_search"),
            ("jmcomic", "jmcomic"),
            ("setu", "setu"),
            ("reminder", "companion"),
            ("mute", "companion"),
        ):
            from .registry import resolve_plugin

            enabled = self.adapters_cfg.get(key, True)
            if key in ("reminder", "mute"):
                lines.append(f"- {key}: 适配{'开' if enabled else '关'} / 内置")
                continue
            loaded = resolve_plugin(star_name) is not None
            flag = "开" if enabled else "关"
            state = "已加载" if loaded else "未加载"
            lines.append(f"- {key}: 适配{flag} / 插件{state}")
        return lines

    def _music_available(self) -> bool:
        mgr = None
        if hasattr(self.context, "get_llm_tool_manager"):
            mgr = self.context.get_llm_tool_manager()
        if mgr is None:
            return False
        return mgr.get_func(MUSIC_NATIVE_TOOL) is not None

    def _register_one(self, name: str, desc: str, args: list, handler) -> bool:
        mgr = None
        if hasattr(self.context, "get_llm_tool_manager"):
            mgr = self.context.get_llm_tool_manager()
        try:
            if hasattr(self.context, "register_llm_tool"):
                self.context.register_llm_tool(name, args, desc, handler)
                return True
        except TypeError:
            pass
        except Exception as e:
            logger.warning("companion 适配器 register_llm_tool 失败 %s: %s", name, e)
        if mgr is None:
            return False
        try:
            mgr.add_func(name, args, desc, handler)
            return True
        except Exception as e:
            logger.warning("companion 适配器注册失败 %s: %s", name, e)
            return False

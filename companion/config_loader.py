from __future__ import annotations

import json
import os
from copy import deepcopy
from typing import Any

# 嵌套配置默认值（与 config/default_config.example.json 对齐）
DEFAULTS: dict[str, Any] = {
    "active_character": "Aemeath",
    "group": {
        "overrides": {},
        "silence_prior": "mid",
        "cooldown_sec": 6,
        "user_cooldown_sec": 8,
        "dedupe_sec": 45,
        "poke_cooldown_sec": 4,
        "reply_jitter_ms": [400, 1800],
        "speech_triggers": {
            "mentioned": True,
            "soft_mention": True,
            "keep_going": False,
        },
    },
    "turn": {
        "debounce_ms": 2000,
        "adaptive_debounce": True,
    },
    "decide": {
        "familiarity_threshold": "warming",
        "llm_assist": False,
        "silence_parser_links": True,
    },
    "express": {
        "fallback_message": "呜……好像不太行，我再想想办法？",
        "max_bubbles": 3,
        "max_chars": 280,
        "bubble_jitter_ms": [600, 2200],
        # 首条发出前的「看消息+打字」延迟
        "typing_delay_ms": [1500, 3500],
        "typing_per_char_ms": 40,
        "typing_delay_max_ms": 5500,
    },
    "presence": {
        "night_hours": [2, 6],
        "night_afk_prob": 0.35,
        "night_hard_always_llm": True,
        "night_delay_mult": 1.35,
    },
    "poke": {
        "enabled": True,
        "incoming_cooldown_sec": 4,
        "outgoing_cooldown_sec": 8,
        "outgoing_delay_ms": [400, 1200],
        "counter_poke_prob": 0.35,
    },
    "reminders": {
        "enabled": True,
        "poll_sec": 5,
        "min_delay_sec": 30,
        "max_delay_sec": 86400,
        "poke_on_fire": True,
        "replace_same_user": True,
        "compose_timeout_sec": 12,
    },
    "providers": {
        "active": "claude",
        "fallback_order": [],
        "profiles": {
            "primary": {
                "label": "minimax",
                "type": "openai_compatible",
                "base_url": "https://api.edgefn.net/v1",
                "api_key": "",
                "model": "MiniMax-M3",
                "api_key_env": "BS_API_KEY",
                "base_url_env": "BS_BASE_URL",
            },
            "claude": {
                "label": "claude",
                "type": "openai_compatible",
                "base_url": "https://daodun.cc/v1",
                "api_key": "",
                "model": "claude-sonnet-5",
                "api_key_env": "CLAUDE_API_KEY",
                "base_url_env": "CLAUDE_BASE_URL",
            },
            "fallback": {
                "label": "备用",
                "type": "openai_compatible",
                "base_url": "",
                "api_key": "",
                "model": "",
                "api_key_env": "BS_API_KEY",
                "base_url_env": "BS_BASE_URL",
            },
        },
        # 面板扁平键仍写这里；load 时同步进 profiles
        "primary": {
            "type": "openai_compatible",
            "base_url": "https://api.edgefn.net/v1",
            "api_key": "",
            "model": "MiniMax-M3",
            "api_key_env": "BS_API_KEY",
            "base_url_env": "BS_BASE_URL",
        },
        "claude": {
            "type": "openai_compatible",
            "base_url": "https://daodun.cc/v1",
            "api_key": "",
            "model": "claude-sonnet-5",
            "api_key_env": "CLAUDE_API_KEY",
            "base_url_env": "CLAUDE_BASE_URL",
        },
        "fallback": {
            "type": "openai_compatible",
            "base_url": "",
            "api_key": "",
            "model": "",
            "api_key_env": "BS_API_KEY",
            "base_url_env": "BS_BASE_URL",
        },
        "timeout_sec": 60,
        "retries": 3,
        "fallback_on_empty": True,
        "use_astrbot_fallback": False,
        "vision_enabled": True,
    },
    "memory": {
        "portrait_enabled": True,
        "episodic_isolation": "channel",
        "max_inject": 6,
        "share_across_characters": False,
        "episodic_ttl_days": 90,
        "quota_episodic": 500,
        "portrait_max_anchors": 30,
        "portrait_inject_max_chars": 400,
        "nearby_before": 10,
        "nearby_after": 3,
        "group_tape_enabled": True,
        "group_tape_inject": 15,
        "group_tape_quota": 200,
    },
    "portrait": {
        "summarizer_provider": "fallback",
        "consolidate_cooldown_min": 30,
        "consolidate_min_hours": 6,
        "consolidate_min_episodic": 8,
        "failure_backoff_threshold": 5,
    },
    "form": {
        "min_dwell_turns": 3,
        "switch_margin": 2,
    },
    "rest": {
        "keywords": ["晚安", "睡了", "别吵", "勿扰"],
        "sleep_until_morning": True,
    },
    "wake_words": {
        "Aemeath": [],
    },
    "stickers": {
        "enabled": True,
        "cooldown_turns": 8,
        "max_per_turn": 1,
        "max_file_mb": 8,
        "min_match_score": 0.55,
        "top_k": 5,
        "allow_tags": [],
        "data_override_dir": "",
        "upload_max_images": 9,
        "intent_boost": {},
        "intent_repeat_window": 3,
        "form_rate_multiplier": {"default": 1.0, "pink": 1.0, "black": 0.9},
    },
    "tools": {
        "enabled": True,
        "mcp_enabled": True,
        "default_mode": "open_with_deny",
        "max_rounds": 3,
        "timeout_sec": 30,
        "slow_timeout_sec": 120,
        "parallel_max": 2,
        "allowlist": [],
        # 未配 API key 时默认藏起；有 key 后从面板黑名单去掉即可
        "denylist": ["web_search_tavily", "web_search_bocha"],
        "persona_outro": True,
        "preface_on_slow": True,
        "media_retry": 1,
        "media_retry_delay_sec": 1.5,
        "failover_shrink_tools": True,
        "adapters": {
            "music": True,
            "image_search": True,
            "jmcomic": True,
            "setu": True,
            "reminder": True,
            "mention": True,
        },
    },
    "concurrency": {
        "per_group": 1,
        "queue_max_per_group": 3,
        "global_max": 8,
        "queue_timeout_sec": 60,
    },
    "card": {
        "sanitize_enabled": True,
        "max_prompt_bytes": 12000,
    },
    "admins": {
        "super": [],
        "operators": [],
        "groups": {},
    },
    "voice": {
        "enabled": False,
        "provider": "siliconflow",
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key": "",
        "api_key_env": "SILICONFLOW_API_KEY",
        "model": "FunAudioLLM/CosyVoice2-0.5B",
        # 预置：FunAudioLLM/CosyVoice2-0.5B:claire ；克隆后填 speech:name:...
        "voice_id": "FunAudioLLM/CosyVoice2-0.5B:claire",
        # 动态克隆（可选）：填本地参考音频+对应文稿后，会覆盖 voice_id 走 references
        "reference_audio": "",
        "reference_text": "",
        "emotion": "",
        "speed": 1.0,
        "vol": 1.0,
        "gain": 0.0,
        "pitch": 0,
        "language_boost": "Chinese",
        "timeout_sec": 60,
        "max_chars": 80,
        "force_max_chars": 200,
        "keep_text": True,
        "speak_last_bubble_only": True,
        "private_only": False,
        "mode": "keyword",
        "force_keywords": [],
    },
}

# AstrBot 配置面板（_conf_schema.json）扁平键 → 嵌套路径（含旧英文键兼容）
FLAT_KEY_PATHS: dict[str, tuple[str, ...]] = {
    # Provider / 模型
    "模型接口地址": ("providers", "primary", "base_url"),
    "模型名称": ("providers", "primary", "model"),
    "API密钥": ("providers", "primary", "api_key"),
    "密钥环境变量名": ("providers", "primary", "api_key_env"),
    "接口地址环境变量名": ("providers", "primary", "base_url_env"),
    "当前供应商": ("providers", "active"),
    "Claude接口地址": ("providers", "claude", "base_url"),
    "Claude模型名称": ("providers", "claude", "model"),
    "ClaudeAPI密钥": ("providers", "claude", "api_key"),
    "Claude密钥环境变量名": ("providers", "claude", "api_key_env"),
    # 旧面板键兼容
    "道盾接口地址": ("providers", "claude", "base_url"),
    "道盾模型名称": ("providers", "claude", "model"),
    "道盾API密钥": ("providers", "claude", "api_key"),
    "道盾密钥环境变量名": ("providers", "claude", "api_key_env"),
    "备用模型接口地址": ("providers", "fallback", "base_url"),
    "备用模型名称": ("providers", "fallback", "model"),
    "LLM请求超时秒": ("providers", "timeout_sec"),
    "空回复切换备用模型": ("providers", "fallback_on_empty"),
    "失败回退AstrBot全局模型": ("providers", "use_astrbot_fallback"),
    "启用多模态视觉": ("providers", "vision_enabled"),
    # 角色 / 群聊 / 回合
    "默认角色卡": ("active_character",),
    "群聊沉默倾向": ("group", "silence_prior"),
    "群聊回复冷却秒": ("group", "cooldown_sec"),
    "同人回复冷却秒": ("group", "user_cooldown_sec"),
    "同文去重秒": ("group", "dedupe_sec"),
    "回复抖动下限毫秒": ("group", "reply_jitter_ms", 0),
    "回复抖动上限毫秒": ("group", "reply_jitter_ms", 1),
    "硬艾特触发": ("group", "speech_triggers", "mentioned"),
    "软唤醒触发": ("group", "speech_triggers", "soft_mention"),
    "续聊触发": ("group", "speech_triggers", "keep_going"),
    "私聊合并窗口毫秒": ("turn", "debounce_ms"),
    "自适应合并窗口": ("turn", "adaptive_debounce"),
    "主动插话熟悉度门槛": ("decide", "familiarity_threshold"),
    "决策层LLM辅助": ("decide", "llm_assist"),
    "私聊解析链接静音": ("decide", "silence_parser_links"),
    "模型全失败兜底句": ("express", "fallback_message"),
    "每回合最多气泡数": ("express", "max_bubbles"),
    "单气泡最大字数": ("express", "max_chars"),
    "气泡间隔抖动下限毫秒": ("express", "bubble_jitter_ms", 0),
    "气泡间隔抖动上限毫秒": ("express", "bubble_jitter_ms", 1),
    "打字延迟下限毫秒": ("express", "typing_delay_ms", 0),
    "打字延迟上限毫秒": ("express", "typing_delay_ms", 1),
    "深夜挂机概率": ("presence", "night_afk_prob"),
    # 记忆 / 画像 / 形态 / 休息
    "记忆注入条数上限": ("memory", "max_inject"),
    "跨角色共享记忆": ("memory", "share_across_characters"),
    "对话记忆保留天数": ("memory", "episodic_ttl_days"),
    "对话记忆条数上限": ("memory", "quota_episodic"),
    "用户画像锚点上限": ("memory", "portrait_max_anchors"),
    "用户画像注入字数": ("memory", "portrait_inject_max_chars"),
    "近聊上文条数": ("memory", "nearby_before"),
    "近聊她侧条数": ("memory", "nearby_after"),
    "画像总结用哪个模型": ("portrait", "summarizer_provider"),
    "画像总结最短间隔分钟": ("portrait", "consolidate_cooldown_min"),
    "画像总结失败退避阈值": ("portrait", "failure_backoff_threshold"),
    "形态最少维持轮数": ("form", "min_dwell_turns"),
    "形态切换领先分差": ("form", "switch_margin"),
    "晚安睡到次日": ("rest", "sleep_until_morning"),
    # 表情 / 工具 / 并发 / 角色卡 / 管理
    "启用表情包": ("stickers", "enabled"),
    "同表情冷却轮数": ("stickers", "cooldown_turns"),
    "每回合最多发图数": ("stickers", "max_per_turn"),
    "表情文件体积上限兆": ("stickers", "max_file_mb"),
    "选图最低匹配分": ("stickers", "min_match_score"),
    "表情加权抽样数量": ("stickers", "top_k"),
    "单次上传最多张数": ("stickers", "upload_max_images"),
    "用户贴纸覆盖目录": ("stickers", "data_override_dir"),
    "启用工具调用": ("tools", "enabled"),
    "启用MCP工具": ("tools", "mcp_enabled"),
    "工具默认策略": ("tools", "default_mode"),
    "每回合最多工具轮数": ("tools", "max_rounds"),
    "单次工具超时秒": ("tools", "timeout_sec"),
    "慢工具超时秒": ("tools", "slow_timeout_sec"),
    "并行工具调用上限": ("tools", "parallel_max"),
    "工具结果人设化收尾": ("tools", "persona_outro"),
    "适配音乐插件": ("tools", "adapters", "music"),
    "适配识图插件": ("tools", "adapters", "image_search"),
    "适配禁漫插件": ("tools", "adapters", "jmcomic"),
    "适配涩图插件": ("tools", "adapters", "setu"),
    "适配提醒工具": ("tools", "adapters", "reminder"),
    "适配点名工具": ("tools", "adapters", "mention"),
    "启用语音合成": ("voice", "enabled"),
    "语音服务商": ("voice", "provider"),
    "语音API密钥": ("voice", "api_key"),
    "语音密钥环境变量名": ("voice", "api_key_env"),
    "语音接口地址": ("voice", "base_url"),
    "语音模型": ("voice", "model"),
    "语音音色ID": ("voice", "voice_id"),
    "语音参考音频路径": ("voice", "reference_audio"),
    "语音参考音频文稿": ("voice", "reference_text"),
    "语音情绪": ("voice", "emotion"),
    "语音最大字数": ("voice", "max_chars"),
    "语音强制触发最大字数": ("voice", "force_max_chars"),
    "语音同时发文字": ("voice", "keep_text"),
    "语音仅念最后一句": ("voice", "speak_last_bubble_only"),
    "语音仅私聊": ("voice", "private_only"),
    "语音触发模式": ("voice", "mode"),
    "同群并行回复数": ("concurrency", "per_group"),
    "同群等待队列上限": ("concurrency", "queue_max_per_group"),
    "全局并行回复上限": ("concurrency", "global_max"),
    "队列等待超时秒": ("concurrency", "queue_timeout_sec"),
    "角色卡提示词清洗": ("card", "sanitize_enabled"),
    "角色卡提示词最大字节": ("card", "max_prompt_bytes"),
    # 旧英文键（升级前配置仍可读）
    "active_character": ("active_character",),
    "group_silence_prior": ("group", "silence_prior"),
    "group_cooldown_sec": ("group", "cooldown_sec"),
    "group_user_cooldown_sec": ("group", "user_cooldown_sec"),
    "group_dedupe_sec": ("group", "dedupe_sec"),
    "group_reply_jitter_min": ("group", "reply_jitter_ms", 0),
    "group_reply_jitter_max": ("group", "reply_jitter_ms", 1),
    "group_trigger_mentioned": ("group", "speech_triggers", "mentioned"),
    "group_trigger_soft_mention": ("group", "speech_triggers", "soft_mention"),
    "group_trigger_keep_going": ("group", "speech_triggers", "keep_going"),
    "turn_debounce_ms": ("turn", "debounce_ms"),
    "turn_adaptive_debounce": ("turn", "adaptive_debounce"),
    "decide_familiarity_threshold": ("decide", "familiarity_threshold"),
    "decide_llm_assist": ("decide", "llm_assist"),
    "decide_silence_parser_links": ("decide", "silence_parser_links"),
    "express_fallback_message": ("express", "fallback_message"),
    "express_max_bubbles": ("express", "max_bubbles"),
    "express_max_chars": ("express", "max_chars"),
    "express_bubble_jitter_min": ("express", "bubble_jitter_ms", 0),
    "express_bubble_jitter_max": ("express", "bubble_jitter_ms", 1),
    "providers_timeout_sec": ("providers", "timeout_sec"),
    "providers_fallback_on_empty": ("providers", "fallback_on_empty"),
    "memory_max_inject": ("memory", "max_inject"),
    "memory_share_across_characters": ("memory", "share_across_characters"),
    "memory_episodic_ttl_days": ("memory", "episodic_ttl_days"),
    "memory_quota_episodic": ("memory", "quota_episodic"),
    "memory_portrait_max_anchors": ("memory", "portrait_max_anchors"),
    "memory_portrait_inject_max_chars": ("memory", "portrait_inject_max_chars"),
    "portrait_summarizer_provider": ("portrait", "summarizer_provider"),
    "portrait_consolidate_cooldown_min": ("portrait", "consolidate_cooldown_min"),
    "portrait_failure_backoff_threshold": ("portrait", "failure_backoff_threshold"),
    "form_min_dwell_turns": ("form", "min_dwell_turns"),
    "form_switch_margin": ("form", "switch_margin"),
    "rest_sleep_until_morning": ("rest", "sleep_until_morning"),
    "stickers_enabled": ("stickers", "enabled"),
    "stickers_cooldown_turns": ("stickers", "cooldown_turns"),
    "stickers_max_per_turn": ("stickers", "max_per_turn"),
    "stickers_max_file_mb": ("stickers", "max_file_mb"),
    "stickers_min_match_score": ("stickers", "min_match_score"),
    "stickers_top_k": ("stickers", "top_k"),
    "stickers_upload_max_images": ("stickers", "upload_max_images"),
    "stickers_data_override_dir": ("stickers", "data_override_dir"),
    "stickers_intent_repeat_window": ("stickers", "intent_repeat_window"),
    "tools_enabled": ("tools", "enabled"),
    "tools_mcp_enabled": ("tools", "mcp_enabled"),
    "tools_default_mode": ("tools", "default_mode"),
    "tools_max_rounds": ("tools", "max_rounds"),
    "tools_timeout_sec": ("tools", "timeout_sec"),
    "tools_slow_timeout_sec": ("tools", "slow_timeout_sec"),
    "tools_parallel_max": ("tools", "parallel_max"),
    "tools_persona_outro": ("tools", "persona_outro"),
    "concurrency_per_group": ("concurrency", "per_group"),
    "concurrency_queue_max_per_group": ("concurrency", "queue_max_per_group"),
    "concurrency_global_max": ("concurrency", "global_max"),
    "concurrency_queue_timeout_sec": ("concurrency", "queue_timeout_sec"),
    "card_sanitize_enabled": ("card", "sanitize_enabled"),
    "card_max_prompt_bytes": ("card", "max_prompt_bytes"),
}

FLAT_LIST_KEYS: dict[str, tuple[str, ...]] = {
    "休息关键词": ("rest", "keywords"),
    "达妮娅额外唤醒词": ("wake_words", "daniya"),
    "Aemeath额外唤醒词": ("wake_words", "Aemeath"),
    "扩展表情标签": ("stickers", "allow_tags"),
    "工具白名单": ("tools", "allowlist"),
    "工具黑名单": ("tools", "denylist"),
    "超级管理员QQ号": ("admins", "super"),
    "管理员QQ号": ("admins", "operators"),
    "语音强制关键词": ("voice", "force_keywords"),
    "rest_keywords": ("rest", "keywords"),
    "wake_words_daniya": ("wake_words", "daniya"),
    "wake_words_Aemeath": ("wake_words", "Aemeath"),
    "stickers_allow_tags": ("stickers", "allow_tags"),
    "tools_allowlist": ("tools", "allowlist"),
    "tools_denylist": ("tools", "denylist"),
    "admins_super": ("admins", "super"),
    "admins_operators": ("admins", "operators"),
    "admins_list": ("admins", "operators"),
}


def load_config(runtime: dict | None, plugin_root: str, data_dir: str | None = None) -> dict[str, Any]:
    cfg = deepcopy(DEFAULTS)

    example = os.path.join(plugin_root, "config", "default_config.example.json")
    if os.path.isfile(example):
        cfg = _merge(cfg, _load_json(example))

    if data_dir:
        user_cfg = os.path.join(data_dir, "config.json")
        if os.path.isfile(user_cfg):
            cfg = _merge(cfg, _load_json(user_cfg))

    if runtime:
        if _looks_nested(runtime):
            cfg = _merge(cfg, runtime)
        else:
            cfg = _apply_flat_overrides(cfg, runtime)

    # V1 固定项（PRD §9）
    cfg.setdefault("memory", {})
    cfg["memory"]["portrait_enabled"] = True
    cfg["memory"]["episodic_isolation"] = "channel"
    cfg.setdefault("tools", {})
    cfg["tools"].setdefault("slow_timeout_sec", 120)
    cfg["tools"].setdefault("preface_on_slow", True)
    _normalize_stickers_size(cfg)
    _normalize_providers(cfg)
    return cfg


def _normalize_stickers_size(cfg: dict[str, Any]) -> None:
    """统一 stickers 体积配置为 max_file_mb；旧字节键折算后丢掉。"""
    st = cfg.setdefault("stickers", {})
    if st.get("max_file_mb") is None and st.get("max_file_bytes") is not None:
        try:
            b = int(st.get("max_file_bytes"))
            st["max_file_mb"] = max(1, round(b / (1024 * 1024)))
        except (TypeError, ValueError):
            st["max_file_mb"] = 8
    st.setdefault("max_file_mb", 8)
    st.pop("max_file_bytes", None)


def _normalize_providers(cfg: dict[str, Any]) -> None:
    """把面板 primary/claude/fallback 同步进 profiles；保证 active 合法。"""
    p = cfg.setdefault("providers", {})
    profiles = p.setdefault("profiles", {})
    if not isinstance(profiles, dict):
        profiles = {}
        p["profiles"] = profiles

    # 旧 id daodun → claude
    if "daodun" in profiles and "claude" not in profiles:
        profiles["claude"] = profiles.pop("daodun")
    elif "daodun" in profiles:
        profiles.pop("daodun", None)
    if isinstance(p.get("daodun"), dict) and not isinstance(p.get("claude"), dict):
        p["claude"] = p.pop("daodun")
    elif "daodun" in p:
        p.pop("daodun", None)
    if str(p.get("active") or "").strip() in ("daodun", "道盾"):
        p["active"] = "claude"

    def _sync(pid: str, label: str, block: dict[str, Any] | None) -> None:
        if not isinstance(block, dict):
            return
        row = dict(profiles.get(pid) or {})
        row.setdefault("label", label)
        row.setdefault("type", "openai_compatible")
        for k in ("base_url", "api_key", "model", "api_key_env", "base_url_env", "type"):
            if k in block:
                val = block.get(k)
                if val not in (None, "") or k in ("api_key", "base_url", "model"):
                    # 允许用面板值覆盖；空 api_key 保留 env 回退
                    if val not in (None, ""):
                        row[k] = val
                    elif k not in row:
                        row[k] = ""
        if block.get("label"):
            row["label"] = block["label"]
        profiles[pid] = row

    primary = p.get("primary") if isinstance(p.get("primary"), dict) else None
    claude = p.get("claude") if isinstance(p.get("claude"), dict) else None
    fallback = p.get("fallback") if isinstance(p.get("fallback"), dict) else None
    _sync("primary", "minimax", primary)
    _sync("claude", "claude", claude)
    if fallback and (
        (fallback.get("base_url") or "").strip()
        or (fallback.get("model") or "").strip()
        or (fallback.get("api_key") or "").strip()
    ):
        _sync("fallback", "备用", fallback)

    if "claude" not in profiles:
        profiles["claude"] = {
            "label": "claude",
            "type": "openai_compatible",
            "base_url": "https://daodun.cc/v1",
            "api_key": "",
            "model": "claude-sonnet-5",
            "api_key_env": "CLAUDE_API_KEY",
            "base_url_env": "CLAUDE_BASE_URL",
        }
    else:
        row = profiles["claude"]
        if str(row.get("label") or "") in ("道盾", "daodun", ""):
            row["label"] = "claude"
        if str(row.get("api_key_env") or "") == "DAODUN_API_KEY":
            row["api_key_env"] = "CLAUDE_API_KEY"
        if str(row.get("base_url_env") or "") == "DAODUN_BASE_URL":
            row["base_url_env"] = "CLAUDE_BASE_URL"
    if "primary" not in profiles and primary:
        profiles["primary"] = dict(primary)
    if "primary" in profiles:
        prow = profiles["primary"]
        if str(prow.get("label") or "").startswith("主"):
            prow["label"] = "minimax"

    active = str(p.get("active") or "claude").strip() or "claude"
    if active in ("daodun", "道盾"):
        active = "claude"
    if active not in profiles:
        active = "claude" if "claude" in profiles else next(iter(profiles), "primary")
    p["active"] = active


def _load_json(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f) or {}


def _looks_nested(runtime: dict) -> bool:
    nested_roots = {
        "group",
        "express",
        "memory",
        "stickers",
        "tools",
        "providers",
        "portrait",
        "form",
        "rest",
        "turn",
        "decide",
        "concurrency",
        "card",
        "admins",
        "wake_words",
        "reminders",
        "poke",
    }
    return any(k in runtime for k in nested_roots)


def _apply_flat_overrides(cfg: dict[str, Any], flat: dict[str, Any]) -> dict[str, Any]:
    out = deepcopy(cfg)
    for key, value in flat.items():
        if key in FLAT_KEY_PATHS:
            _set_path(out, FLAT_KEY_PATHS[key], value)
        elif key in FLAT_LIST_KEYS:
            _set_path(out, FLAT_LIST_KEYS[key], value)
    return out


def _set_path(obj: dict, path: tuple, value: Any) -> None:
    cur: Any = obj
    for i, part in enumerate(path[:-1]):
        nxt = path[i + 1]
        if isinstance(part, int):
            while len(cur) <= part:
                cur.append(0)
            cur = cur[part]
        else:
            if isinstance(nxt, int):
                cur = cur.setdefault(part, [])
            else:
                cur = cur.setdefault(part, {})
    last = path[-1]
    if isinstance(last, int):
        while len(cur) <= last:
            cur.append(0)
        cur[last] = deepcopy(value)
    else:
        cur[last] = deepcopy(value)


def _merge(base: dict, override: dict) -> dict:
    out = deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = deepcopy(v)
    return out

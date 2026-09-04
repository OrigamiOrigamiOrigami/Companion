"""V1 sticker_intent / primary_tag 词表（与 PRD §6.7.2-C 对齐；lonely/guarded 已退役）。"""

from __future__ import annotations

# tag -> 给作者 / Express 的短释义
TAG_GLOSSARY: dict[str, str] = {
    "tease": "调戏、调侃",
    "playful": "调皮、起哄",
    "mock": "嘲笑、嘲讽",
    "shy": "害羞",
    "warm": "温柔、关心",
    "quiet": "沉默、淡",
    "speechless": "无语",
    "surprise": "惊讶、吃惊",
    "happy": "开心",
    "sad": "难过",
    "angry": "生气、恼火",
    "reject": "拒绝、嫌弃",
    "thinking": "思考、琢磨",
    "question": "疑问、疑惑",
    "like": "喜欢、心动",
    "tired": "疲惫、累",
    "sleep": "睡觉、睡着",
    "cute": "卖萌、装可爱",
    "approve": "认可、赞同",
}

DEFAULT_TAGS: list[str] = list(TAG_GLOSSARY.keys())

# 资源库缺某 tag 时的近义回退（按优先级；空桶也要能落到有图的 tag）
INTENT_FALLBACKS: dict[str, tuple[str, ...]] = {
    "happy": ("warm", "playful", "like", "approve", "cute"),
    "shy": ("warm", "quiet", "playful", "cute"),
    "thinking": ("question", "quiet", "speechless"),
    "question": ("thinking", "speechless", "surprise", "playful"),
    "cute": ("playful", "warm", "like", "happy"),
    "like": ("warm", "happy", "cute", "approve"),
    "sleep": ("tired", "quiet", "warm"),
    "reject": ("angry", "speechless", "quiet"),
    "tired": ("sleep", "quiet", "sad"),
    "sad": ("quiet", "warm", "tired"),
    "angry": ("reject", "speechless", "mock", "quiet"),
    "speechless": ("quiet", "surprise", "question", "angry"),
    "tease": ("playful", "mock", "happy", "like"),
    "playful": ("tease", "mock", "happy", "cute"),
    "mock": ("tease", "playful", "speechless", "angry"),
    "surprise": ("speechless", "question", "happy", "shy"),
    "quiet": ("speechless", "warm", "sad"),
    "warm": ("like", "happy", "shy"),
    "approve": ("like", "happy", "warm"),
}

# 中文 / 别名 -> 规范英文 tag（上传指令、人工输入）
TAG_ALIASES: dict[str, str] = {
    "tease": "tease",
    "撩": "tease",
    "调侃": "tease",
    "调戏": "tease",
    "playful": "playful",
    "调皮": "playful",
    "起哄": "playful",
    "玩闹": "playful",
    "mock": "mock",
    "嘲笑": "mock",
    "嘲讽": "mock",
    "讥笑": "mock",
    "嘲": "mock",
    "shy": "shy",
    "害羞": "shy",
    "羞": "shy",
    "warm": "warm",
    "温柔": "warm",
    "关心": "warm",
    "暖": "warm",
    "quiet": "quiet",
    "沉默": "quiet",
    "淡": "quiet",
    "安静": "quiet",
    "speechless": "speechless",
    "无语": "speechless",
    "无言": "speechless",
    "无话可说": "speechless",
    "surprise": "surprise",
    "惊讶": "surprise",
    "吃惊": "surprise",
    "震惊": "surprise",
    "happy": "happy",
    "开心": "happy",
    "高兴": "happy",
    "快乐": "happy",
    "sad": "sad",
    "难过": "sad",
    "伤心": "sad",
    "委屈": "sad",
    "angry": "angry",
    "生气": "angry",
    "恼火": "angry",
    "气": "angry",
    "reject": "reject",
    "拒绝": "reject",
    "不要": "reject",
    "嫌弃": "reject",
    "推开": "reject",
    "滚开": "reject",
    "thinking": "thinking",
    "思考": "thinking",
    "琢磨": "thinking",
    "想": "thinking",
    "question": "question",
    "疑问": "question",
    "疑惑": "question",
    "困惑": "question",
    "like": "like",
    "喜欢": "like",
    "心动": "like",
    "爱": "like",
    "tired": "tired",
    "疲惫": "tired",
    "累": "tired",
    "sleep": "sleep",
    "睡觉": "sleep",
    "睡着": "sleep",
    "睡着了": "sleep",
    "晚安": "sleep",
    "入睡": "sleep",
    "困": "sleep",
    "cute": "cute",
    "卖萌": "cute",
    "装可爱": "cute",
    "萌": "cute",
    "approve": "approve",
    "认可": "approve",
    "赞同": "approve",
    "同意": "approve",
    "点头": "approve",
}


def resolve_tag(raw: str) -> str | None:
    """中文/英文别名 → 规范 tag；无法识别返回 None。"""
    key2 = (raw or "").strip()
    if not key2 or key2.lower() == "none":
        return None
    if key2 in TAG_ALIASES:
        return TAG_ALIASES[key2]
    key = key2.lower()
    if key in TAG_ALIASES:
        return TAG_ALIASES[key]
    if key in TAG_GLOSSARY:
        return key
    return None


def tag_alias_help(allow: list[str] | set[str] | None = None) -> str:
    """列出可用情绪的中英对照，供报错/用法。"""
    allow_set = {str(t).lower() for t in (allow or DEFAULT_TAGS)}
    parts: list[str] = []
    for tag in DEFAULT_TAGS:
        if tag not in allow_set:
            continue
        zh = TAG_GLOSSARY.get(tag, tag).split("、")[0].split("（")[0]
        parts.append(f"{zh}/{tag}")
    return "、".join(parts) if parts else "（空）"


def merge_allow_tags(
    *sources: list[str] | None,
    extra: list[str] | None = None,
) -> list[str]:
    """合并多路 tag 源；未知 tag 仍可进入表（allow_tags 扩展），默认表优先排序。"""
    seen: set[str] = set()
    out: list[str] = []
    for src in (*sources, extra or []):
        if not src:
            continue
        for t in src:
            tag = str(t or "").strip().lower()
            if not tag or tag == "none" or tag in seen:
                continue
            seen.add(tag)
            out.append(tag)
    frozen = [t for t in DEFAULT_TAGS if t in seen]
    rest = sorted(t for t in out if t not in TAG_GLOSSARY)
    return frozen + rest


def glossary_for(tags: list[str]) -> str:
    """Express 注入用：`tease=撩、调侃; playful=…`"""
    parts: list[str] = []
    for t in tags:
        gloss = TAG_GLOSSARY.get(t, t)
        parts.append(f"{t}={gloss}")
    return "; ".join(parts) if parts else "none"

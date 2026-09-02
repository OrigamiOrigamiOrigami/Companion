from __future__ import annotations

import re

# MiniMax speech-2.8 支持的情绪（whisper 仅 2.6，仍接受以便兼容）
VALID_EMOTIONS = frozenset(
    {
        "happy",
        "sad",
        "angry",
        "fearful",
        "disgusted",
        "surprised",
        "calm",
        "fluent",
        "whisper",
    }
)

_ALIAS = {
    "happy": "happy",
    "joy": "happy",
    "开心": "happy",
    "高兴": "happy",
    "欢快": "happy",
    "愉快": "happy",
    "sad": "sad",
    "悲伤": "sad",
    "难过": "sad",
    "伤心": "sad",
    "沮丧": "sad",
    "低落": "sad",
    "angry": "angry",
    "生气": "angry",
    "愤怒": "angry",
    "恼火": "angry",
    "fearful": "fearful",
    "害怕": "fearful",
    "恐惧": "fearful",
    "紧张": "fearful",
    "disgusted": "disgusted",
    "厌恶": "disgusted",
    "嫌弃": "disgusted",
    "surprised": "surprised",
    "惊讶": "surprised",
    "吃惊": "surprised",
    "calm": "calm",
    "平静": "calm",
    "冷静": "calm",
    "中性": "calm",
    "neutral": "calm",
    "fluent": "fluent",
    "生动": "fluent",
    "whisper": "whisper",
    "低语": "whisper",
    "轻声": "whisper",
}

_EMOTION_LINE_RE = re.compile(
    r"voice_emotion\s*[:=]\s*([a-zA-Z_\u4e00-\u9fff]+)",
    re.I,
)

# 官方语气词标签，清洗旁白时需保留
TTS_SOUND_TAGS = frozenset(
    {
        "laughs",
        "chuckle",
        "coughs",
        "clear-throat",
        "groans",
        "breath",
        "pant",
        "inhale",
        "exhale",
        "gasps",
        "sniffs",
        "sighs",
        "snorts",
        "burps",
        "lip-smacking",
        "humming",
        "hissing",
        "emm",
        "sneezes",
    }
)


def normalize_emotion(raw: str | None) -> str:
    s = (raw or "").strip().lower()
    if not s:
        return ""
    mapped = _ALIAS.get(s) or _ALIAS.get((raw or "").strip())
    if mapped and mapped in VALID_EMOTIONS:
        return mapped
    if s in VALID_EMOTIONS:
        return s
    return ""


def extract_voice_emotion(text: str) -> tuple[str, str]:
    """从一行或整段里抽出 voice_emotion，返回 (emotion, 去掉标记后的文本)。"""
    emotion = ""
    cleaned = text or ""

    def _sub(m: re.Match[str]) -> str:
        nonlocal emotion
        if not emotion:
            emotion = normalize_emotion(m.group(1))
        return " "

    cleaned = _EMOTION_LINE_RE.sub(_sub, cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip(" |;,.，。")
    return emotion, cleaned

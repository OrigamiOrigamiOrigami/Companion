from __future__ import annotations

import re
from typing import Iterable

# 用户明确要求听语音/念白时触发；命中后本回合念完整回复。
_DEFAULT_KEYWORDS = (
    "语音",
    "发语音",
    "念一下",
    "念一句",
    "念一句话",
    "念出来",
    "念",
    "读出来",
    "读一下",
    "读一句",
    "听听",
    "听一下",
    "说出来",
    "说一句",
    "用嘴说",
    "voice",
    "tts",
)

# 注意：不要用「说一下」——日常「说一下天气」不是 TTS
_SPEAK_PATTERNS = (
    re.compile(
        r"(?:用)?语音(?:帮我)?(?:说|念|读)(?:一下|一句|一句话|出来)?[，,：:\s]*(.+)$"
    ),
    re.compile(r"(?:用)?念(?:一下|一句|一句话|出来)[，,：:\s]*(.+)$"),
    re.compile(r"用念(?:一下|一句)?[，,：:\s]*(.+)$"),
    re.compile(r"(?:读|说)一句(?:话)?[，,：:\s]*(.+)$"),
)

_WORDISH = re.compile(r"^[a-z0-9_]+$", re.I)


def voice_force_keywords(extra: Iterable[str] | None = None) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in list(_DEFAULT_KEYWORDS) + list(extra or []):
        w = (raw or "").strip()
        if not w:
            continue
        key = w.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(w)
    # 长词优先，避免短词抢匹配时不好排查
    out.sort(key=len, reverse=True)
    return out


def is_voice_force_intent(text: str, extra: Iterable[str] | None = None) -> bool:
    s = (text or "").strip()
    if not s:
        return False
    lower = s.lower()
    for kw in voice_force_keywords(extra):
        if _WORDISH.match(kw):
            if re.search(rf"(?<![a-z0-9_]){re.escape(kw.lower())}(?![a-z0-9_])", lower):
                return True
        elif kw.lower() in lower or kw in s:
            return True
    # 漏写「语音」但能抽出「念一句xxx」正文
    if extract_voice_speak_line(s):
        return True
    return False


# 「用语音说一句话」≠ 点歌；带这些词才允许调音乐工具
_SONG_TOOL_KW = (
    "点歌",
    "放歌",
    "放一首",
    "来一首",
    "来首",
    "播放",
    "听歌",
    "唱一首",
    "唱首",
    "歌曲",
    "music",
)


def is_song_tool_intent(text: str) -> bool:
    s = (text or "").strip().lower()
    if not s:
        return False
    return any(k.lower() in s or k in (text or "") for k in _SONG_TOOL_KW)


def extract_voice_speak_line(text: str) -> str:
    """从「用语音说xxx」「念一句xxx」里抽出要念的正文；抽不到则空串。"""
    s = (text or "").strip()
    if not s:
        return ""
    for prefix in ("小爱", "爱弥斯", "娅娅", "达妮娅"):
        if s.startswith(prefix):
            s = s[len(prefix) :].lstrip(" ，,：:")
            break
    for pat in _SPEAK_PATTERNS:
        m = pat.search(s)
        if not m:
            continue
        line = (m.group(1) or "").strip()
        line = re.sub(r"^[，,。.!！？?\s～~]+", "", line)
        line = re.sub(r"[～~]+$", "", line).strip()
        if len(line) < 1:
            continue
        if line in ("一句", "一下", "一句话", "出来"):
            continue
        return line[:80]
    return ""

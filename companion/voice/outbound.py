from __future__ import annotations

import logging
import re
from typing import Any

from .emotion import TTS_SOUND_TAGS, normalize_emotion
from .intent import is_voice_force_intent
from .minimax_tts import MiniMaxTTSError
from .siliconflow_tts import SiliconFlowTTSError

logger = logging.getLogger("astrbot")

_TTS_ERRORS = (MiniMaxTTSError, SiliconFlowTTSError)

_ACTION_RE = re.compile(r"\*[^*]+\*")
# 中文旁白 （…）/ 英文括号里非官方语气词
_CN_PAREN_RE = re.compile(r"（[^）]*）")
_EN_PAREN_RE = re.compile(r"\(([^)]*)\)")


def clean_tts_text(text: str, *, max_chars: int = 80) -> str:
    """去掉动作描写与旁白，保留 MiniMax 语气词标签。"""
    s = (text or "").strip()
    if not s:
        return ""
    s = _ACTION_RE.sub(" ", s)
    # @[qq:…] / @昵称(QQ) 不念
    s = re.sub(
        r"@\[(?:qq[:：]\s*)?\d{5,12}\]|@[^\s@\[\]()]{1,32}\(\d{5,12}\)",
        " ",
        s,
        flags=re.I,
    )
    s = _CN_PAREN_RE.sub(" ", s)

    def _en_paren(m: re.Match[str]) -> str:
        inner = (m.group(1) or "").strip().lower()
        if inner in TTS_SOUND_TAGS:
            return f"({inner})"
        return " "

    s = _EN_PAREN_RE.sub(_en_paren, s)
    s = re.sub(r"\s+", " ", s).strip(" ，,。.~～")
    if len(s) > max_chars:
        s = s[: max_chars - 1].rstrip() + "…"
    return s


def is_worth_speaking(text: str) -> bool:
    """太短或只有语气词的不念（避免「……嗯」也出语音）。"""
    s = (text or "").strip()
    if not s:
        return False
    core = re.sub(r"[….。，,!~～？\?！\s…·\-—_「」\"']+", "", s)
    if len(core) < 4:
        return False
    if re.fullmatch(r"[嗯啊呃哦嘿哈行吧哒呐]+", core):
        return False
    return True


class VoiceOutbound:
    def __init__(self, tts: Any, cfg: dict[str, Any]):
        self.tts = tts
        self.cfg = cfg or {}

    def mode(self) -> str:
        raw = (self.cfg.get("mode") or "keyword").strip().lower()
        if raw in ("always", "all", "每条", "全部"):
            return "always"
        if raw in ("off", "none", "关"):
            return "off"
        return "keyword"

    def force_keywords(self) -> list[str]:
        extra = self.cfg.get("force_keywords") or []
        if isinstance(extra, str):
            extra = [x.strip() for x in extra.replace("，", ",").split(",") if x.strip()]
        return list(extra)

    def detect_force(self, text: str) -> bool:
        return is_voice_force_intent(text, self.force_keywords())

    def should_speak(self, *, is_private: bool, force: bool = False) -> bool:
        if not self.tts.enabled():
            return False
        mode = self.mode()
        if mode == "off":
            return False
        if force:
            return True
        if mode != "always":
            return False
        if self.cfg.get("private_only", False) and not is_private:
            return False
        return True

    def resolve_emotion(self, turn_emotion: str | None = None) -> str:
        """本回合模型指定优先，否则用配置默认；皆空则不传，交给 API 自适配。"""
        picked = normalize_emotion(turn_emotion)
        if picked:
            return picked
        return normalize_emotion(self.cfg.get("emotion"))

    def speech_text(self, bubbles: list[str], *, full: bool = False) -> str:
        base_max = int(self.cfg.get("max_chars") or 80)
        if full:
            max_chars = int(self.cfg.get("force_max_chars") or max(base_max, 200))
            use_last = False
        else:
            max_chars = base_max
            use_last = bool(self.cfg.get("speak_last_bubble_only", True))
        if use_last and bubbles:
            return clean_tts_text(bubbles[-1], max_chars=max_chars)
        joined = "。".join(b.strip() for b in bubbles if b.strip())
        return clean_tts_text(joined, max_chars=max_chars)

    async def send_voice(
        self,
        event: Any,
        bubbles: list[str],
        *,
        full: bool = False,
        emotion: str | None = None,
    ) -> bool:
        text = self.speech_text(bubbles, full=full)
        if not text or not is_worth_speaking(text):
            return False
        emo = self.resolve_emotion(emotion)
        try:
            path = await self.tts.synthesize(text, emotion=emo or None)
        except _TTS_ERRORS as e:
            logger.warning("companion TTS 失败: %s", e)
            return False
        except Exception as e:
            logger.warning("companion TTS 异常: %s", e, exc_info=True)
            return False

        try:
            from astrbot.core.message.components import Record

            seg = Record.fromFileSystem(str(path.resolve()))
            await event.send(event.chain_result([seg]))
            logger.info(
                "companion 语音已发送 文件=%s 字数=%s 全文=%s 情绪=%s",
                path.name,
                len(text),
                full,
                emo or "auto",
            )
            return True
        except Exception as e:
            logger.warning("companion 语音发送失败: %s", e, exc_info=True)
            return False

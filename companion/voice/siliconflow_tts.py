"""硅基流动 TTS（CosyVoice2）：预置音色 / 上传克隆 / 动态参考音频。"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger("astrbot")

# CosyVoice 用自然语言控情绪（与 MiniMax 的 emotion 字段不同）
_EMOTION_HINTS = {
    "happy": "请用开心、轻快、带笑意的语气说。",
    "sad": "请用温柔、略带伤感的语气说。",
    "angry": "请用生气但不失克制的语气说。",
    "fearful": "请用有点紧张、不安的语气说。",
    "disgusted": "请用嫌弃、无奈的语气说。",
    "surprised": "请用惊讶、惊喜的语气说。",
    "calm": "请用平静、温柔的语气说。",
    "fluent": "请用自然流畅的日常语气说。",
    "whisper": "请用轻声、贴近耳边的语气说。",
}


class SiliconFlowTTSError(RuntimeError):
    pass


class SiliconFlowTTS:
    """OpenAI 兼容 /audio/speech；响应为音频二进制。"""

    def __init__(self, cfg: dict[str, Any], cache_dir: str):
        self.cfg = cfg or {}
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def enabled(self) -> bool:
        return bool(self.cfg.get("enabled", False)) and bool(self._api_key())

    def _api_key(self) -> str:
        key = (self.cfg.get("api_key") or "").strip()
        if key:
            return key
        env_name = (self.cfg.get("api_key_env") or "SILICONFLOW_API_KEY").strip()
        return (os.getenv(env_name) or "").strip()

    def _base(self) -> str:
        raw = (self.cfg.get("base_url") or "https://api.siliconflow.cn/v1").rstrip("/")
        if raw.endswith("/v1"):
            return raw
        return raw + "/v1"

    def _endpoint(self) -> str:
        return f"{self._base()}/audio/speech"

    async def synthesize(self, text: str, *, emotion: str | None = None) -> Path:
        text = (text or "").strip()
        if not text:
            raise SiliconFlowTTSError("empty text")
        key = self._api_key()
        if not key:
            raise SiliconFlowTTSError("missing SILICONFLOW_API_KEY")

        model = (self.cfg.get("model") or "FunAudioLLM/CosyVoice2-0.5B").strip()
        voice = (self.cfg.get("voice_id") or "").strip()
        timeout = float(self.cfg.get("timeout_sec") or 60)
        speed = float(self.cfg.get("speed") or 1.0)
        gain = float(self.cfg.get("gain") if self.cfg.get("gain") is not None else (self.cfg.get("vol") or 0.0))
        # vol 在 MiniMax 是倍率；硅基用 gain(dB)。若误配成 1.0 当增益则几乎无声，归一一下
        if 0 < gain <= 2.0 and self.cfg.get("gain") is None:
            gain = 0.0

        spoken = self._with_emotion(text, emotion)
        payload: dict[str, Any] = {
            "model": model,
            "input": spoken,
            "response_format": "mp3",
            "speed": speed,
            "gain": gain,
        }

        refs = self._build_references()
        if refs:
            # 动态克隆：voice 置空，每轮带参考音频
            payload["voice"] = ""
            payload["references"] = refs
        elif voice:
            payload["voice"] = voice
        else:
            # 默认温柔女声预置
            payload["voice"] = f"{model}:claire"

        audio = await asyncio.to_thread(self._request_audio_bytes, key, payload, timeout)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        out = self.cache_dir / f"tts_{int(time.time() * 1000)}.mp3"
        out.write_bytes(audio)
        self._trim_cache()
        return out

    def _with_emotion(self, text: str, emotion: str | None) -> str:
        emo = (emotion or self.cfg.get("emotion") or "").strip().lower()
        hint = _EMOTION_HINTS.get(emo)
        if not hint:
            return text
        # CosyVoice 富文本控情绪
        if "<|endofprompt|>" in text:
            return text
        return f"{hint}<|endofprompt|>{text}"

    def _build_references(self) -> list[dict[str, str]] | None:
        """配置了 reference_audio(+text) 时走动态克隆。"""
        ref_path = (self.cfg.get("reference_audio") or "").strip()
        ref_text = (self.cfg.get("reference_text") or "").strip()
        if not ref_path:
            return None
        path = Path(ref_path)
        if not path.is_file():
            # 相对插件 data 常见路径兜底
            logger.warning("siliconflow 参考音频缺失: %s", ref_path)
            return None
        if not ref_text:
            logger.warning("siliconflow 参考文本为空；跳过动态克隆")
            return None
        mime = mimetypes.guess_type(str(path))[0] or "audio/wav"
        b64 = base64.b64encode(path.read_bytes()).decode("ascii")
        return [{"audio": f"data:{mime};base64,{b64}", "text": ref_text}]

    def _request_audio_bytes(self, api_key: str, payload: dict[str, Any], timeout: float) -> bytes:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._endpoint(),
            data=body,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                ctype = (resp.headers.get("Content-Type") or "").lower()
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:400]
            raise SiliconFlowTTSError(f"HTTP {e.code}: {detail}") from e
        except Exception as e:
            raise SiliconFlowTTSError(str(e)) from e

        if "application/json" in ctype:
            try:
                data = json.loads(raw.decode("utf-8"))
            except Exception as e:
                raise SiliconFlowTTSError(f"bad json: {raw[:120]!r}") from e
            msg = data.get("message") or data.get("error") or data
            raise SiliconFlowTTSError(f"api error: {msg}")

        if not raw or len(raw) < 64:
            raise SiliconFlowTTSError("empty audio")
        return raw

    def _trim_cache(self, keep: int = 30) -> None:
        files = sorted(self.cache_dir.glob("tts_*.mp3"), key=lambda p: p.stat().st_mtime)
        for old in files[:-keep]:
            try:
                old.unlink(missing_ok=True)
            except OSError:
                pass

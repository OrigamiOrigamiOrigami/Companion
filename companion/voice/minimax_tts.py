from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

logger = logging.getLogger("astrbot")


class MiniMaxTTSError(RuntimeError):
    pass


class MiniMaxTTS:
    """MiniMax 同步 T2A（云端，本机几乎不吃算力）。"""

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
        env_name = (self.cfg.get("api_key_env") or "MINIMAX_API_KEY").strip()
        return (os.getenv(env_name) or "").strip()

    def _endpoint(self) -> str:
        return (
            (self.cfg.get("base_url") or "https://api.minimaxi.com").rstrip("/")
            + "/v1/t2a_v2"
        )

    async def synthesize(self, text: str, *, emotion: str | None = None) -> Path:
        text = (text or "").strip()
        if not text:
            raise MiniMaxTTSError("empty text")
        key = self._api_key()
        if not key:
            raise MiniMaxTTSError("missing MINIMAX_API_KEY")

        model = (self.cfg.get("model") or "speech-2.8-turbo").strip()
        voice_id = (self.cfg.get("voice_id") or "female-shaonv").strip()
        timeout = float(self.cfg.get("timeout_sec") or 45)

        payload: dict[str, Any] = {
            "model": model,
            "text": text,
            "stream": False,
            "language_boost": self.cfg.get("language_boost") or "Chinese",
            "voice_setting": {
                "voice_id": voice_id,
                "speed": float(self.cfg.get("speed") or 1.0),
                "vol": float(self.cfg.get("vol") or 1.0),
                "pitch": int(self.cfg.get("pitch") or 0),
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
        }
        emo = (emotion if emotion is not None else self.cfg.get("emotion") or "").strip()
        if emo:
            payload["voice_setting"]["emotion"] = emo

        audio = await asyncio.to_thread(self._request_hex_audio, key, payload, timeout)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        out = self.cache_dir / f"tts_{int(time.time() * 1000)}.mp3"
        out.write_bytes(audio)
        self._trim_cache()
        return out

    def _request_hex_audio(self, api_key: str, payload: dict[str, Any], timeout: float) -> bytes:
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
                raw = resp.read()
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            raise MiniMaxTTSError(f"HTTP {e.code}: {detail}") from e
        except Exception as e:
            raise MiniMaxTTSError(str(e)) from e

        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception as e:
            raise MiniMaxTTSError(f"bad json: {raw[:120]!r}") from e

        base = data.get("base_resp") or {}
        code = base.get("status_code", 0)
        if code not in (0, None):
            raise MiniMaxTTSError(f"api {code}: {base.get('status_msg')}")

        audio_hex = ((data.get("data") or {}).get("audio")) or ""
        if not audio_hex:
            raise MiniMaxTTSError("empty audio")
        return bytes.fromhex(audio_hex)

    def _trim_cache(self, keep: int = 30) -> None:
        files = sorted(self.cache_dir.glob("tts_*.mp3"), key=lambda p: p.stat().st_mtime)
        for old in files[:-keep]:
            try:
                old.unlink(missing_ok=True)
            except OSError:
                pass

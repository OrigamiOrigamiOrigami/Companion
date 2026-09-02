"""按配置选择 TTS 后端。"""

from __future__ import annotations

from typing import Any, Protocol

from .minimax_tts import MiniMaxTTS
from .siliconflow_tts import SiliconFlowTTS


class TTSClient(Protocol):
    cfg: dict[str, Any]

    def enabled(self) -> bool: ...

    def _api_key(self) -> str: ...

    async def synthesize(self, text: str, *, emotion: str | None = None): ...


def build_tts(cfg: dict[str, Any], cache_dir: str) -> TTSClient:
    provider = str((cfg or {}).get("provider") or "minimax").strip().lower()
    if provider in ("siliconflow", "silicon", "sf", "硅基", "硅基流动"):
        return SiliconFlowTTS(cfg, cache_dir)
    return MiniMaxTTS(cfg, cache_dir)

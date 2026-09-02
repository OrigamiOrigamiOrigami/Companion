"""表情包体积限制：配置填兆 MB，运行时换算字节。"""

from __future__ import annotations

from typing import Any

_DEFAULT_MB = 8.0


def sticker_max_file_bytes(stickers_cfg: dict[str, Any] | None = None) -> int:
    """表情体积上限（字节）。优先 ``max_file_mb``，兼容旧 ``max_file_bytes``。"""
    cfg = stickers_cfg or {}
    if cfg.get("max_file_mb") is not None:
        try:
            mb = float(cfg.get("max_file_mb"))
        except (TypeError, ValueError):
            mb = _DEFAULT_MB
        return max(1, int(mb * 1024 * 1024))
    raw = cfg.get("max_file_bytes")
    if raw is not None:
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            pass
    return int(_DEFAULT_MB * 1024 * 1024)

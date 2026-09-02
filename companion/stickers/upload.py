"""表情包上传：写入 data 覆盖目录扁平文件 `{角色}_{情绪}_{序号}.ext`。"""

from __future__ import annotations

import logging
import os
import re
from typing import Any

from ..harness.media import ImagePayload

logger = logging.getLogger("astrbot")

_FLAT_SEQ_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9]*)_([a-z][a-z0-9_]*)_(\d{2})\.(webp|png|gif|jpg|jpeg)$",
    re.I,
)
# 兼容扫到旧文件名 warm_01.gif
_LEGACY_SEQ_RE = re.compile(
    r"^([a-z][a-z0-9_]*)_(\d{2})\.(webp|png|gif|jpg|jpeg)$",
    re.I,
)


def next_sticker_seq(dir_path: str, tag: str, *, character_id: str) -> int:
    """扫描目录，返回该 tag 下一个可用序号（1–99）。"""
    tag = tag.lower()
    char = (character_id or "").strip()
    used: set[int] = set()
    if os.path.isdir(dir_path):
        for name in os.listdir(dir_path):
            m = _FLAT_SEQ_RE.match(name)
            if m:
                if m.group(2).lower() != tag:
                    continue
                if char and m.group(1).lower() != char.lower():
                    continue
                used.add(int(m.group(3)))
                continue
            m2 = _LEGACY_SEQ_RE.match(name)
            if m2 and m2.group(1).lower() == tag:
                used.add(int(m2.group(2)))
    for i in range(1, 100):
        if i not in used:
            return i
    raise RuntimeError(f"tag={tag} 序号已满（01–99）")


def save_sticker_file(
    *,
    root_dir: str,
    character_id: str,
    tag: str,
    payload: ImagePayload,
    max_file_bytes: int = 8 * 1024 * 1024,
) -> dict[str, Any]:
    """保存到角色目录根下：`{character}_{tag}_{seq}.ext`。"""
    tag = (tag or "").strip().lower()
    char = (character_id or "").strip() or "sticker"
    if not re.match(r"^[A-Za-z][A-Za-z0-9]*$", char):
        raise ValueError("角色 id 不合法，无法命名表情文件")
    if not tag or not re.match(r"^[a-z][a-z0-9_]*$", tag):
        raise ValueError("情绪标签不合法")
    if len(payload.data) > max_file_bytes:
        mb = max_file_bytes / (1024 * 1024)
        raise ValueError(
            f"图片太大（约 {len(payload.data)/(1024*1024):.1f}MB，上限 {mb:.0f}MB）"
        )

    os.makedirs(root_dir, exist_ok=True)
    seq = next_sticker_seq(root_dir, tag, character_id=char)
    ext = payload.ext if payload.ext in {".webp", ".png", ".gif", ".jpg", ".jpeg"} else ".png"
    filename = f"{char}_{tag}_{seq:02d}{ext}"
    path = os.path.join(root_dir, filename)
    with open(path, "wb") as f:
        f.write(payload.data)
    sid = f"{char}_{tag}_{seq:02d}"
    logger.info(
        "companion 表情包已保存 id=%s path=%s source=%s bytes=%s",
        sid,
        path,
        payload.source,
        len(payload.data),
    )
    return {
        "sticker_id": sid,
        "path": path,
        "filename": filename,
        "character_id": char,
        "form": "shared",
        "tag": tag,
        "seq": seq,
    }

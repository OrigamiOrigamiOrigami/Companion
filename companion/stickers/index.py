"""表情包索引：扁平 `{角色}_{情绪}_{序号}.ext` + 可选旧版 `{form}/` 兼容。"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

from .tags import DEFAULT_TAGS, merge_allow_tags

logger = logging.getLogger("astrbot")

# 扁平：Aemeath_warm_01.gif
_FLAT_RE = re.compile(
    r"^([A-Za-z][A-Za-z0-9]*)_([a-z][a-z0-9_]*)_(\d{2})\.(webp|png|gif|jpg|jpeg)$",
    re.I,
)
# 旧版子目录内：warm_01.gif
_LEGACY_NAME_RE = re.compile(
    r"^([a-z][a-z0-9_]*)_(\d{2})\.(webp|png|gif|jpg|jpeg)$",
    re.I,
)
_EXT = {".webp", ".png", ".gif", ".jpg", ".jpeg"}


@dataclass
class StickerItem:
    sticker_id: str
    path: str
    form: str
    primary_tag: str
    tags: list[str] = field(default_factory=list)
    weight: float = 1.0


def load_sticker_index(
    *,
    card_dir: str,
    data_override_dir: str = "",
    allow_tags: list[str] | None = None,
    max_file_bytes: int = 8 * 1024 * 1024,
    character_id: str = "",
) -> list[StickerItem]:
    tags = merge_allow_tags(DEFAULT_TAGS, allow_tags)
    tag_set = set(tags)
    char = (character_id or "").strip() or os.path.basename(
        (data_override_dir or card_dir or "").rstrip("/\\")
    )

    builtin = os.path.join(card_dir, "stickers")
    by_rel: dict[str, str] = {}
    for root in (builtin, data_override_dir):
        if not root or not os.path.isdir(root):
            continue
        for dirpath, _, files in os.walk(root):
            for name in files:
                if os.path.splitext(name)[1].lower() not in _EXT:
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, root).replace("\\", "/")
                by_rel[rel] = full

    meta = _load_manifests(builtin, data_override_dir)
    items: list[StickerItem] = []
    for rel, full in by_rel.items():
        try:
            if os.path.getsize(full) > max_file_bytes:
                logger.warning("表情包过大已跳过 %s", rel)
                continue
        except OSError:
            continue

        parsed = _parse_rel(rel, character_id=char)
        if not parsed:
            logger.warning("表情包文件名不合规已跳过 %s", rel)
            continue
        form, tag, seq, sid = parsed
        if tag not in tag_set:
            logger.warning("表情包标签不在允许列表已跳过 %s", rel)
            continue
        row = meta.get(sid) or meta.get(rel) or {}
        if row.get("enabled") is False:
            continue
        extra_tags = [t.lower() for t in (row.get("tags") or [tag])]
        if tag not in extra_tags:
            extra_tags.insert(0, tag)
        items.append(
            StickerItem(
                sticker_id=sid,
                path=full,
                form=form,
                primary_tag=tag,
                tags=extra_tags,
                weight=float(row.get("weight") or 1.0),
            )
        )
    logger.info("companion 表情包已加载=%s 张 character=%s", len(items), char)
    return items


def _parse_rel(
    rel: str, *, character_id: str
) -> tuple[str, str, str, str] | None:
    """返回 (form, tag, seq, sticker_id)。扁平文件 form=shared 以适配任意形态。"""
    parts = rel.split("/")
    name = parts[-1]
    if len(parts) == 1:
        m = _FLAT_RE.match(name)
        if not m:
            return None
        prefix, tag, seq = m.group(1), m.group(2).lower(), m.group(3)
        if character_id and prefix.lower() != character_id.lower():
            # 允许其它角色前缀误放，但仍用文件名做 id
            pass
        sid = f"{prefix}_{tag}_{seq}"
        return "shared", tag, seq, sid

    # 旧版：default/warm_01.gif → form=default
    form = parts[0].lower()
    if not form or form.startswith("."):
        return None
    m = _LEGACY_NAME_RE.match(name)
    if not m:
        return None
    tag, seq = m.group(1).lower(), m.group(2)
    sid = f"{form}_{tag}_{seq}"
    return form, tag, seq, sid


def _load_manifests(*roots: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for root in roots:
        if not root:
            continue
        path = os.path.join(root, "manifest.yaml")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for row in data.get("stickers") or []:
                if not isinstance(row, dict):
                    continue
                key = row.get("id") or row.get("path")
                if key:
                    out[str(key)] = row
        except Exception as e:
            logger.warning("表情包 manifest 读取失败 %s: %s", path, e)
    return out

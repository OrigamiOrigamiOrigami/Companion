"""用 Pillow 生成表情包分类缩略图总览（单张 PNG）。"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections import defaultdict
from typing import Any

from PIL import Image, ImageDraw, ImageFont, ImageOps

from .index import StickerItem
from .tags import DEFAULT_TAGS, TAG_GLOSSARY

logger = logging.getLogger("astrbot")

_CATALOG_PNG = "_catalog.png"
_CATALOG_META = "_catalog.meta.json"

_THUMB = 96
_PAD = 10
_GAP = 8
_COLS = 8
_HEADER_H = 28
_TITLE_H = 36
_CAPTION_H = 18
_BG = (245, 246, 248)
_SECTION_BG = (255, 255, 255)
_TEXT = (40, 44, 52)
_MUTED = (110, 118, 132)
_BORDER = (220, 224, 230)
_MAX_W = 4096
_MAX_H = 16000

_FONT_CANDIDATES = (
    os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "msyh.ttc"),
    os.path.join(os.environ.get("WINDIR", "C:/Windows"), "Fonts", "simhei.ttf"),
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in _FONT_CANDIDATES:
        if not os.path.isfile(path):
            continue
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _load_thumb(path: str, size: int) -> Image.Image:
    with Image.open(path) as im:
        if getattr(im, "n_frames", 1) > 1:
            im.seek(0)
        frame = im.convert("RGBA")
    frame = ImageOps.contain(frame, (size, size), method=Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (255, 255, 255, 0))
    ox = (size - frame.width) // 2
    oy = (size - frame.height) // 2
    canvas.paste(frame, (ox, oy), frame)
    return canvas


def _tag_label(tag: str) -> str:
    gloss = TAG_GLOSSARY.get(tag, "")
    zh = gloss.split("、")[0].split("（")[0] if gloss else tag
    return f"{tag} · {zh}" if gloss else tag


def _group_items(items: list[StickerItem]) -> list[tuple[str, list[StickerItem]]]:
    by_tag: dict[str, list[StickerItem]] = defaultdict(list)
    for it in items:
        by_tag[it.primary_tag].append(it)
    order = [t for t in DEFAULT_TAGS if t in by_tag]
    for tag in sorted(by_tag.keys()):
        if tag not in order:
            order.append(tag)
    out: list[tuple[str, list[StickerItem]]] = []
    for tag in order:
        rows = sorted(by_tag[tag], key=lambda x: (x.form, x.sticker_id))
        if rows:
            out.append((tag, rows))
    return out


def _layout_height(
    groups: list[tuple[str, list[StickerItem]]],
    *,
    thumb_size: int,
    cols: int,
) -> int:
    h = _PAD + _TITLE_H + _PAD
    for _tag, rows in groups:
        n_rows = (len(rows) + cols - 1) // cols
        h += _HEADER_H + n_rows * (thumb_size + _CAPTION_H + _GAP) + _PAD
    return h


def _fit_layout(
    groups: list[tuple[str, list[StickerItem]]],
    *,
    thumb_size: int,
    cols: int,
) -> tuple[int, int]:
    """若超高则缩小 thumb / 列数直到放进 _MAX_H。"""
    ts, c = thumb_size, cols
    for _ in range(12):
        h = _layout_height(groups, thumb_size=ts, cols=c)
        if h <= _MAX_H:
            return ts, c
        ts = max(48, int(ts * 0.85))
        c = max(4, c - 1)
    return ts, c


def catalog_paths(out_dir: str) -> tuple[str, str]:
    return (
        os.path.join(out_dir, _CATALOG_PNG),
        os.path.join(out_dir, _CATALOG_META),
    )


def _live_items(items: list[StickerItem]) -> list[StickerItem]:
    return [it for it in items if os.path.isfile(it.path)]


def index_fingerprint(items: list[StickerItem]) -> str:
    """索引指纹：id + 路径 + mtime + 大小；改名/增删/换图都会变。"""
    parts: list[str] = []
    for it in sorted(items, key=lambda x: x.sticker_id):
        if not os.path.isfile(it.path):
            continue
        try:
            st = os.stat(it.path)
        except OSError:
            continue
        parts.append(f"{it.sticker_id}|{st.st_mtime_ns}|{st.st_size}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _load_catalog_meta(meta_path: str) -> dict[str, Any] | None:
    if not os.path.isfile(meta_path):
        return None
    try:
        raw = json.load(open(meta_path, encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except Exception as e:
        logger.warning("companion 图鉴缓存 meta 读取失败: %s", e)
        return None


def _save_catalog_meta(meta_path: str, payload: dict[str, Any]) -> None:
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning("companion 图鉴缓存 meta 写入失败: %s", e)


def try_load_cached_catalog(
    *,
    png_path: str,
    meta_path: str,
    items: list[StickerItem],
    title: str,
) -> dict[str, Any] | None:
    """数量不变、索引有效且指纹一致 → 复用上次的 PNG。"""
    live = _live_items(items)
    if not live:
        return None
    if len(live) != len(items):
        return None
    meta = _load_catalog_meta(meta_path)
    if not meta or not os.path.isfile(png_path):
        return None
    fp = index_fingerprint(live)
    if meta.get("fingerprint") != fp:
        return None
    if int(meta.get("count") or 0) != len(live):
        return None
    if str(meta.get("title") or "") != title:
        return None
    logger.info("companion 图鉴命中缓存 n=%s path=%s", len(live), png_path)
    return {
        "path": png_path,
        "count": len(live),
        "width": int(meta.get("width") or 0),
        "height": int(meta.get("height") or 0),
        "tags": int(meta.get("tags") or 0),
        "cached": True,
    }


def get_or_build_sticker_catalog(
    items: list[StickerItem],
    *,
    output_dir: str,
    title: str = "表情包图鉴",
    thumb_size: int = _THUMB,
    cols: int = _COLS,
) -> dict[str, Any]:
    """先尝试缓存；否则 Pillow 渲染并写入 meta。"""
    png_path, meta_path = catalog_paths(output_dir)
    cached = try_load_cached_catalog(
        png_path=png_path,
        meta_path=meta_path,
        items=items,
        title=title,
    )
    if cached:
        return cached

    result = build_sticker_catalog(
        items,
        output_path=png_path,
        title=title,
        thumb_size=thumb_size,
        cols=cols,
    )
    result["cached"] = False
    _save_catalog_meta(
        meta_path,
        {
            "fingerprint": index_fingerprint(_live_items(items)),
            "count": result["count"],
            "tags": result["tags"],
            "width": result["width"],
            "height": result["height"],
            "title": title,
            "generated_ts": time.time(),
        },
    )
    return result


def build_sticker_catalog(
    items: list[StickerItem],
    *,
    output_path: str,
    title: str = "表情包图鉴",
    thumb_size: int = _THUMB,
    cols: int = _COLS,
) -> dict[str, Any]:
    """按 primary_tag 分组拼一张图；返回 path / count / size。"""
    live = [it for it in items if os.path.isfile(it.path)]
    skipped = len(items) - len(live)
    if skipped:
        logger.warning(
            "companion 图鉴跳过 %s 条无效路径（改名/删文件后请表情重载）",
            skipped,
        )
    if not live:
        raise ValueError("还没有表情包素材")

    groups = _group_items(live)
    thumb_size, cols = _fit_layout(groups, thumb_size=thumb_size, cols=cols)
    cell_w = thumb_size + _GAP
    canvas_w = min(_PAD * 2 + cols * cell_w - _GAP, _MAX_W)
    canvas_h = min(_layout_height(groups, thumb_size=thumb_size, cols=cols), _MAX_H)

    canvas = Image.new("RGB", (canvas_w, canvas_h), _BG)
    draw = ImageDraw.Draw(canvas)
    font_title = _font(18)
    font_head = _font(14)
    font_cap = _font(11)

    y = _PAD
    draw.text((_PAD, y), f"{title} · 共 {len(live)} 张", fill=_TEXT, font=font_title)
    y += _TITLE_H

    for tag, rows in groups:
        if y + _HEADER_H + thumb_size > canvas.height:
            break
        draw.rectangle(
            [_PAD, y, canvas_w - _PAD, y + _HEADER_H],
            fill=_SECTION_BG,
            outline=_BORDER,
        )
        draw.text((_PAD + 6, y + 5), _tag_label(tag), fill=_TEXT, font=font_head)
        y += _HEADER_H + 4

        for i, it in enumerate(rows):
            col = i % cols
            row_i = i // cols
            x = _PAD + col * cell_w
            cy = y + row_i * (thumb_size + _CAPTION_H + _GAP)
            if cy + thumb_size + _CAPTION_H > canvas.height:
                break
            try:
                thumb = _load_thumb(it.path, thumb_size)
            except Exception as e:
                logger.warning("companion 图鉴缩略图失败 id=%s: %s", it.sticker_id, e)
                thumb = Image.new("RGBA", (thumb_size, thumb_size), (230, 230, 230, 255))
                td = ImageDraw.Draw(thumb)
                td.text((8, thumb_size // 2 - 6), "?", fill=(120, 120, 120))

            canvas.paste(thumb, (x, cy), thumb)
            cap = it.sticker_id
            if len(cap) > 18:
                cap = cap[-18:]
            draw.text((x, cy + thumb_size + 2), cap, fill=_MUTED, font=font_cap)

        n_rows = (len(rows) + cols - 1) // cols
        y += n_rows * (thumb_size + _CAPTION_H + _GAP) + _PAD

    canvas = canvas.crop((0, 0, canvas_w, min(y + _PAD, canvas.height)))

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    canvas.save(output_path, format="PNG", optimize=True)
    logger.info(
        "companion 表情包图鉴已生成 path=%s n=%s size=%sx%s",
        output_path,
        len(live),
        canvas.width,
        canvas.height,
    )
    return {
        "path": output_path,
        "count": len(live),
        "width": canvas.width,
        "height": canvas.height,
        "tags": len(groups),
        "skipped": skipped,
    }

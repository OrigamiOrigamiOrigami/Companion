from __future__ import annotations

import asyncio
import base64
import logging
import os
from dataclasses import dataclass
from typing import Any

from astrbot.api.event import AstrMessageEvent

logger = logging.getLogger("astrbot")

_MAX_VISION_BYTES = 4 * 1024 * 1024
_MAX_STICKER_BYTES = 512 * 1024

_MIME_EXT = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


@dataclass
class MediaInfo:
    image_count: int = 0
    face_count: int = 0
    reply_image_count: int = 0
    record_count: int = 0

    @property
    def has_visual(self) -> bool:
        return (self.image_count + self.face_count + self.reply_image_count) > 0

    @property
    def has_image(self) -> bool:
        return (self.image_count + self.reply_image_count) > 0

    @property
    def has_any_media(self) -> bool:
        return self.has_visual or self.record_count > 0

    def describe(self) -> str:
        parts: list[str] = []
        if self.image_count:
            parts.append(f"{self.image_count} 张图片")
        if self.face_count:
            parts.append(f"{self.face_count} 个 QQ 表情")
        if self.reply_image_count:
            parts.append(f"引用里还有 {self.reply_image_count} 张图")
        if self.record_count:
            parts.append(f"{self.record_count} 条语音")
        if not parts:
            return ""
        return "对方发来 " + "、".join(parts)


@dataclass
class ImagePayload:
    """通用图片载荷：本条或引用回复里抽到的图。"""

    data: bytes
    mime: str
    ext: str
    source: str = "message"  # message | reply | url


def _components():
    try:
        from astrbot.core.message.components import Face, Image, Record, Reply

        return Image, Face, Record, Reply
    except ImportError:
        return None, None, None, None


def extract_media(event: AstrMessageEvent) -> MediaInfo:
    info = MediaInfo()
    Image, Face, Record, Reply = _components()
    if Image is None:
        return info

    for msg in event.get_messages() or []:
        if isinstance(msg, Image):
            info.image_count += 1
        elif Face is not None and isinstance(msg, Face):
            info.face_count += 1
        elif Record is not None and isinstance(msg, Record):
            info.record_count += 1
        elif Reply is not None and isinstance(msg, Reply) and getattr(msg, "chain", None):
            for seg in msg.chain:
                if isinstance(seg, Image):
                    info.reply_image_count += 1
                elif Face is not None and isinstance(seg, Face):
                    info.face_count += 1
    return info


async def collect_image_segments(
    event: AstrMessageEvent,
    *,
    include_reply: bool = True,
) -> list[tuple[Any, str]]:
    """收集 Image 段，返回 ``(segment, source)``；source 为 message|reply。

    支持：本条附图、引用链里的图；引用 chain 为空时尝试 get_msg 补全。
    """
    Image, _, _, Reply = _components()
    if Image is None:
        return []
    out: list[tuple[Any, str]] = []
    for msg in event.get_messages() or []:
        if isinstance(msg, Image):
            out.append((msg, "message"))
        elif include_reply and Reply is not None and isinstance(msg, Reply):
            chain = getattr(msg, "chain", None) or []
            found = False
            for seg in chain:
                if isinstance(seg, Image):
                    out.append((seg, "reply"))
                    found = True
            if not found:
                for seg in await _resolve_reply_images(event, msg):
                    out.append((seg, "reply"))
    return out


async def extract_image_payloads(
    event: AstrMessageEvent,
    *,
    max_images: int = 1,
    include_reply: bool = True,
    max_bytes: int | None = None,
) -> list[ImagePayload]:
    """通用：从本条 / 引用回复抽出图片字节（可复用：表情上传、识图、视觉等）。"""
    cap = max(1, int(max_images))
    limit = int(max_bytes) if max_bytes is not None else _MAX_VISION_BYTES
    segments = await collect_image_segments(event, include_reply=include_reply)
    payloads: list[ImagePayload] = []
    for seg, source in segments[:cap]:
        raw = await download_image_bytes(event, seg)
        if not raw or len(raw) < 64:
            continue
        if len(raw) > limit:
            logger.warning(
                "companion 图片过大已跳过（约 %.1fMB，上限 %.0fMB）",
                len(raw) / (1024 * 1024),
                limit / (1024 * 1024),
            )
            continue
        mime = guess_image_mime(raw)
        payloads.append(
            ImagePayload(
                data=raw,
                mime=mime,
                ext=_MIME_EXT.get(mime, ".jpg"),
                source=source,
            )
        )
    return payloads


async def extract_vision_images(
    event: AstrMessageEvent,
    *,
    max_images: int = 1,
) -> list[str]:
    """提取图片为 OpenAI 兼容 data URL，供多模态模型使用。"""
    payloads = await extract_image_payloads(
        event,
        max_images=max_images,
        include_reply=True,
        max_bytes=_MAX_VISION_BYTES,
    )
    urls = [f"data:{p.mime};base64,{base64.b64encode(p.data).decode('ascii')}" for p in payloads]
    if urls:
        logger.info("companion 视觉已附带 %d 张图", len(urls))
    return urls


async def fetch_image_payload_from_url(
    url: str,
    *,
    max_bytes: int | None = None,
) -> ImagePayload | None:
    """从 http(s) 直链拉一张图（表情上传等）。"""
    u = (url or "").strip()
    if not u.startswith(("http://", "https://")):
        return None
    limit = int(max_bytes) if max_bytes is not None else _MAX_STICKER_BYTES
    raw = await _fetch_url(u)
    if not raw or len(raw) < 64:
        logger.warning("companion URL 拉图失败或内容过短 url=%s", u[:120])
        return None
    if len(raw) > limit:
        raise ValueError(
            f"链接图片太大（约 {len(raw)/(1024*1024):.1f}MB，上限 {limit/(1024*1024):.0f}MB）"
        )
    mime = guess_image_mime(raw)
    # 非图片魔数时仍允许常见 gif/webp 直链（部分 CDN 返回 octet-stream）
    if mime == "image/jpeg" and not (raw[:2] == b"\xff\xd8"):
        lower = u.lower().split("?", 1)[0]
        if lower.endswith(".gif"):
            mime = "image/gif"
        elif lower.endswith(".png"):
            mime = "image/png"
        elif lower.endswith(".webp"):
            mime = "image/webp"
    return ImagePayload(
        data=raw,
        mime=mime,
        ext=_MIME_EXT.get(mime, ".jpg"),
        source="url",
    )


async def download_image_bytes(event: AstrMessageEvent, image: Any) -> bytes | None:
    """下载单个 Image 段的字节（公开，便于其它模块复用）。"""
    image_data: bytes | None = None
    image_url = getattr(image, "url", None) or None
    if not image_url:
        file_field = getattr(image, "file", "") or ""
        if isinstance(file_field, str) and file_field.startswith(("http://", "https://")):
            image_url = file_field

    bot = getattr(event, "bot", None)
    file_id = getattr(image, "file", None)
    if bot is not None and file_id:
        try:
            data = await bot.call_action(action="get_image", file=file_id)
            image_data = _coerce_bytes(data)
            if image_data is None and isinstance(data, dict):
                if "data" in data:
                    image_data = _coerce_bytes(data["data"])
                elif "file" in data and os.path.isfile(data["file"]):
                    image_data = await asyncio.to_thread(_read_file, data["file"])
        except Exception as e:
            logger.debug("companion 视觉 get_image 失败: %s", e)

    if not image_data and image_url:
        image_data = await _fetch_url(image_url)

    return image_data


def guess_image_mime(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:2] == b"\xff\xd8":
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if len(data) > 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


async def _resolve_reply_images(event: AstrMessageEvent, reply: Any) -> list[Any]:
    """引用 chain 为空时，用 message_id 拉原消息再抽 Image。"""
    Image, _, _, _ = _components()
    if Image is None:
        return []
    bot = getattr(event, "bot", None)
    if bot is None:
        return []
    mid = (
        getattr(reply, "id", None)
        or getattr(reply, "message_id", None)
        or getattr(reply, "msg_id", None)
    )
    if mid is None:
        return []
    try:
        data = await bot.call_action(action="get_msg", message_id=int(mid))
    except Exception as e:
        logger.debug("companion 拉取引用消息失败 mid=%s err=%s", mid, e)
        return []

    message = None
    if isinstance(data, dict):
        message = data.get("message") or (data.get("data") or {}).get("message")
    if not isinstance(message, list):
        return []

    out: list[Any] = []
    for part in message:
        if isinstance(part, dict) and part.get("type") == "image":
            pdata = part.get("data") or {}
            out.append(_FakeImage(url=pdata.get("url"), file=pdata.get("file")))
        elif Image is not None and isinstance(part, Image):
            out.append(part)
    return out


@dataclass
class _FakeImage:
    url: str | None = None
    file: str | None = None


def _read_file(path: str) -> bytes:
    with open(path, "rb") as f:
        return f.read()


def _coerce_bytes(raw: Any) -> bytes | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, str):
        try:
            return base64.b64decode(raw, validate=False)
        except Exception:
            if os.path.isfile(raw):
                return _read_file(raw)
            return raw.encode("utf-8", errors="ignore") or None
    if isinstance(raw, dict):
        if "data" in raw:
            return _coerce_bytes(raw["data"])
        if "file" in raw and os.path.isfile(str(raw["file"])):
            return _read_file(str(raw["file"]))
    return None


async def _fetch_url(url: str) -> bytes | None:
    try:
        import aiohttp
    except ImportError:
        return await asyncio.to_thread(_fetch_url_sync, url)

    fetch_url = url
    if fetch_url.startswith("https://"):
        fetch_url = "http://" + fetch_url[8:]
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                fetch_url, timeout=aiohttp.ClientTimeout(total=20), ssl=False
            ) as resp:
                if resp.status == 200:
                    return await resp.read()
    except Exception as e:
        logger.debug("companion 视觉 URL 拉取失败: %s", e)
    return None


def _fetch_url_sync(url: str) -> bytes | None:
    import urllib.request

    fetch_url = url
    if fetch_url.startswith("https://"):
        fetch_url = "http://" + fetch_url[8:]
    try:
        with urllib.request.urlopen(fetch_url, timeout=20) as resp:
            return resp.read()
    except Exception:
        return None

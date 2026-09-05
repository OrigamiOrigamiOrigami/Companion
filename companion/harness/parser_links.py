"""Detect share links that astrbot_plugin_parser typically handles.

Local needle list only — do not import parser (avoids coupling / empty-keyword traps).
"""

from __future__ import annotations

import re

# Lowercase substrings; prefer host forms that are rare in normal chat.
# Intentionally omit bare douyin 18–20 digit ids (high false positive).
_DOMAIN_NEEDLES: tuple[str, ...] = (
    # bilibili
    "b23.tv",
    "bili2233.cn",
    "bilibili.com",
    "bilibili.tv",
    "t.bilibili.com",
    "live.bilibili.com",
    # youtube
    "youtu.be",
    "youtube.com",
    # douyin
    "v.douyin.com",
    "jx.douyin.com",
    "douyin.com",
    "iesdouyin.com",
    "m.douyin.com",
    "jingxuan.douyin.com",
    "aweme_id",
    "aweme/",
    # xhs
    "xhslink.com",
    "xhslink.cn",
    "xiaohongshu.com",
    # tiktok / kuaishou
    "tiktok.com",
    "v.kuaishou.com",
    "kuaishou.com",
    "chenzhongtech.com",
    # weibo
    "weibo.com",
    "weibo.cn",
    "video.weibo.com",
    "mapp.api.weibo.cn",
    # pixiv / ig / twitter（x.com 用带协议前缀，避免误伤）
    "pixiv.net",
    "instagram.com",
    "instagr.am",
    "twitter.com",
    "://x.com/",
    "://www.x.com/",
    # zhihu / ncm / nga / acfun / iwara / xhh / 视频号
    "zhihu.com",
    "zhuanlan.zhihu.com",
    "music.163.com",
    "y.music.163.com",
    "163cn.tv",
    "music.126.net",
    "ngabbs.com",
    "nga.178.com",
    "bbs.nga.cn",
    "acfun.cn",
    "iwara.tv",
    "xiaoheihe.cn",
    "weixin.qq.com/sph",
)

# Whole-message bare share dumps (bilibili parity)
_BARE_SHARE_RE = re.compile(
    r"(?is)^\s*(?:"
    r"BV[0-9a-zA-Z]{10}"
    r"|bmBV[0-9a-zA-Z]{10}"
    r"|av\d{6,}"
    r")(?:\s+\d{1,3})?\s*$"
)

_FAVLIST_RE = re.compile(r"(?i)favlist\?fid=\d+")


def looks_like_parser_share(text: str) -> bool:
    """True if text looks like a media share parser would consume."""
    raw = (text or "").strip()
    if not raw:
        return False
    if _BARE_SHARE_RE.match(raw):
        return True
    if _FAVLIST_RE.search(raw):
        return True
    low = raw.lower()
    return any(needle in low for needle in _DOMAIN_NEEDLES)

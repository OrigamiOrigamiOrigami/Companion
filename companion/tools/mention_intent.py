"""群聊「帮我@某人 / 点名」意图。"""

from __future__ import annotations

import re

# 用户要机器人去 @ 别人（不是自己 @ 机器人）
_ASK_AT_RE = re.compile(
    r"(?:帮我|给我|替我|请|麻烦)?.{0,12}(?:@|＠|艾特|at)\s*[^\s@＠]{1,32}"
    r"|(?:@|＠|艾特).{0,8}(?:出来|一下|现身|出来一下)"
    r"|点名\s*[^\s@＠]{1,32}"
    r"|喊\s*[^\s@＠]{1,16}\s*(?:一下|出来|过来)",
    re.I,
)

_NAME_AFTER_AT_RE = re.compile(
    r"(?:@|＠|艾特)\s*([^\s@＠,，。！!？?~～（）()\[\]【】]{1,32})",
    re.I,
)
_NAME_DIANMING_RE = re.compile(r"点名\s*([^\s@＠,，。！!？?]{1,32})")
_NAME_HAN_RE = re.compile(r"喊\s*([^\s@＠,，。！!？?]{1,16})\s*(?:一下|出来|过来)")


def is_mention_intent(text: str) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    return bool(_ASK_AT_RE.search(t))


def extract_mention_name(text: str) -> str:
    """从用户原话里抠要 @ 的称呼（外号/名片）。"""
    t = (text or "").strip()
    if not t:
        return ""
    raw = ""
    for pat in (_NAME_AFTER_AT_RE, _NAME_DIANMING_RE, _NAME_HAN_RE):
        m = pat.search(t)
        if m:
            raw = (m.group(1) or "").strip()
            break
    if not raw:
        return ""
    name = raw.strip("的了啦呀啊哦呢嘛~～")
    for suf in ("出来一下", "出来看看", "出来", "一下", "现身", "过来", "出来吧"):
        if name.endswith(suf) and len(name) > len(suf) + 1:
            name = name[: -len(suf)]
            break
    if name in ("我", "你", "她", "他", "它", "小爱", "爱弥斯"):
        return ""
    return name[:32]
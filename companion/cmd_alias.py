"""Companion 管理命令别名：中文 / 短语 → 规范英文 token。"""

from __future__ import annotations

import re

# 整句尾部短语；长的写前面
_PHRASES: list[tuple[str, list[str]]] = [
    (r"^帮助$", ["help"]),
    (r"^用法$", ["help"]),
    (r"^状态$", ["status"]),
    (r"^开启?$", ["on"]),
    (r"^关闭?$", ["off"]),
    (r"^表情包?\s*重载$", ["stickers", "reload"]),
    (r"^表情\s*重载$", ["stickers", "reload"]),
    (r"^表情包?\s*(?:情绪)?统计\s*清零$", ["stickers", "stats", "reset"]),
    (r"^情绪统计\s*清零$", ["stickers", "stats", "reset"]),
    (r"^表情统计\s*清零$", ["stickers", "stats", "reset"]),
    (r"^表情包?\s*(?:情绪)?统计$", ["emotions"]),
    (r"^情绪统计$", ["emotions"]),
    (r"^表情统计$", ["emotions"]),
    (r"^情绪$", ["emotions"]),
    (r"^表情图鉴$", ["stickers", "catalog"]),
    (r"^表情一览$", ["stickers", "catalog"]),
    (r"^表情包?\s*图鉴$", ["stickers", "catalog"]),
    (r"^工具\s*(?:列表|列出)?$", ["tools", "list"]),
    (r"^工具\s*重载$", ["tools", "reload"]),
    (r"^适配器?$", ["adapters"]),
    (r"^画像\s*(?:查看|显示)?$", ["portrait", "show"]),
    (r"^画像\s*刷新$", ["portrait", "refresh"]),
    (r"^语音\s*(?:开|开启|打开)$", ["voice", "on"]),
    (r"^语音\s*(?:关|关闭)$", ["voice", "off"]),
    (r"^语音$", ["voice"]),
    # 记忆
    (r"^清除记忆$", ["memory", "reset", "me"]),
    (r"^清空记忆$", ["memory", "reset", "me"]),
    (r"^记忆清除$", ["memory", "reset", "me"]),
    # 管理员：添加/删除（@ 可在前后，解析时会剥掉）
    (r"^添加管理员$", ["admin", "add"]),
    (r"^加管理员$", ["admin", "add"]),
    (r"^删除管理员$", ["admin", "remove"]),
    (r"^移除管理员$", ["admin", "remove"]),
    (r"^管理员名单$", ["admin", "list"]),
    (r"^查看管理员$", ["admin", "list"]),
    (r"^管理员列表$", ["admin", "list"]),
    (r"^供应商(?:名单|列表)?$", ["provider", "list"]),
    (r"^模型(?:名单|列表)?$", ["provider", "list"]),
    (r"^供应商\s*claude$", ["provider", "claude"]),
    (r"^供应商\s*minimax$", ["provider", "minimax"]),
    (r"^供应商\s*主(?:模型)?$", ["provider", "primary"]),
]

_TOKEN: dict[str, str] = {
    "status": "status",
    "stat": "status",
    "状态": "status",
    "on": "on",
    "开": "on",
    "开启": "on",
    "打开": "on",
    "enable": "on",
    "off": "off",
    "关": "off",
    "关闭": "off",
    "disable": "off",
    "stickers": "stickers",
    "sticker": "stickers",
    "表情": "stickers",
    "表情包": "stickers",
    "emotions": "emotions",
    "emotion": "emotions",
    "情绪": "emotions",
    "情绪统计": "emotions",
    "表情统计": "emotions",
    "tools": "tools",
    "工具": "tools",
    "adapters": "adapters",
    "adapter": "adapters",
    "适配": "adapters",
    "适配器": "adapters",
    "portrait": "portrait",
    "画像": "portrait",
    "人设卡": "portrait",
    "voice": "voice",
    "tts": "voice",
    "语音": "voice",
    "memory": "memory",
    "记忆": "memory",
    "清除记忆": "memory_clear_alias",  # 交 resolve；勿当普通 token
    "admin": "admin",
    "admins": "admin",
    "op": "admin",
    "ops": "admin",
    "管理": "admin",
    "管理员": "admin",
    "provider": "provider",
    "providers": "provider",
    "供应商": "provider",
    "模型": "provider",
    "help": "help",
    "帮助": "help",
    "用法": "help",
    "reload": "reload",
    "重载": "reload",
    "stats": "stats",
    "统计": "stats",
    "catalog": "catalog",
    "gallery": "catalog",
    "图鉴": "catalog",
    "一览": "catalog",
    "reset": "reset",
    "clear": "reset",
    "清零": "reset",
    "清空": "reset",
    "清除": "reset",
    "upload": "upload",
    "上传": "upload",
    "add": "add",
    "加": "add",
    "添加": "add",
    "set": "add",
    "list": "list",
    "ls": "list",
    "名单": "list",
    "列表": "list",
    "show": "show",
    "查看": "show",
    "显示": "show",
    "refresh": "refresh",
    "刷新": "refresh",
    "重刷": "refresh",
    "remove": "remove",
    "rm": "remove",
    "del": "remove",
    "delete": "remove",
    "删": "remove",
    "删除": "remove",
    "移除": "remove",
    "用": "use",
    "切换": "use",
    "切": "use",
    "use": "use",
    "set": "use",
    "me": "me",
    "self": "me",
    "我": "me",
    "自己": "me",
}

PLUGIN_PREFIX_RE = r"(?:companion|persona|伴侣|人设|小伴)"

HELP_TEXT = (
    "用法（中英都行）：\n"
    "· /伴侣 状态 | 开 | 关\n"
    "· /伴侣 语音 开|关\n"
    "· /伴侣 表情重载 | 表情统计 | 表情图鉴 | 情绪统计 清零\n"
    "· /伴侣 工具 | 适配器\n"
    "· /伴侣 画像 | 画像 刷新（画像查看限私聊）\n"
    "· /伴侣 供应商 | 供应商 claude | 供应商 minimax\n"
    "· /伴侣 清除记忆\n"
    "· /伴侣 添加管理员 @某人  或  @某人 添加管理员\n"
    "· /伴侣 删除管理员 @某人  或  @某人 删除管理员\n"
    "· /伴侣 管理员名单\n"
    "· 也可直接：表情统计 / 表情图鉴 / 清除记忆 / 上传 害羞 + 图"
)


def _strip_mentions_and_qq(text: str) -> str:
    """去掉 @… 与长数字，方便识别「@某人 添加管理员」这类语序。"""
    t = text or ""
    t = re.sub(r"@\S+", " ", t)
    t = re.sub(r"\d{5,}", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def resolve_command_args(tail: str) -> list[str]:
    """从 /伴侣 后面的原文解析规范子命令（支持 @ 前后乱序）。"""
    raw = (tail or "").strip()
    if not raw:
        return []
    cleaned = _strip_mentions_and_qq(raw)
    compact = re.sub(r"\s+", "", cleaned)
    # 关键词优先（@ 已剥掉）
    if compact in ("清除记忆", "清空记忆", "记忆清除"):
        return ["memory", "reset", "me"]
    m_prov = re.fullmatch(r"(?:供应商|模型)(?:用|切换|切)?(.+)", compact)
    if m_prov:
        target = (m_prov.group(1) or "").strip()
        if target and target not in ("名单", "列表"):
            return ["provider", target]
    if compact in ("供应商", "供应商名单", "供应商列表", "模型", "模型名单", "模型列表"):
        return ["provider", "list"]
    if "添加管理员" in compact or compact == "加管理员":
        return ["admin", "add"]
    if "删除管理员" in compact or "移除管理员" in compact:
        return ["admin", "remove"]
    if compact in ("管理员名单", "查看管理员", "管理员列表"):
        return ["admin", "list"]
    return canonicalize_args(cleaned.split() if cleaned else raw.split())


def canonicalize_args(args: list[str]) -> list[str]:
    """把用户输入 token / 短语收成规范英文子命令。"""
    if not args:
        return []
    joined = " ".join(args).strip()
    for pat, canon in _PHRASES:
        if re.fullmatch(pat, joined, flags=re.I):
            return list(canon)
    compact = re.sub(r"\s+", "", joined)
    if compact != joined:
        for pat, canon in _PHRASES:
            if re.fullmatch(pat, compact, flags=re.I):
                return list(canon)
    # 粘连：清除记忆 / 添加管理员
    if compact in ("清除记忆", "清空记忆", "记忆清除"):
        return ["memory", "reset", "me"]
    if compact in ("添加管理员", "加管理员"):
        return ["admin", "add"]
    if compact in ("删除管理员", "移除管理员"):
        return ["admin", "remove"]
    out: list[str] = []
    for tok in args:
        key = tok.strip()
        low = key.lower()
        mapped = None
        if low in _TOKEN:
            mapped = _TOKEN[low]
        elif key in _TOKEN:
            mapped = _TOKEN[key]
        if mapped == "memory_clear_alias":
            return ["memory", "reset", "me"]
        if mapped is not None:
            out.append(mapped)
        else:
            out.append(low if key.isascii() else key)
    return out

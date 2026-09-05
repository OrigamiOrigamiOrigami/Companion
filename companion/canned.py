"""爱弥斯命令回执 / 兜底短句；高频场景走变体池防复读。"""

from __future__ import annotations

from .variants import pick_variant

# —— Express / 发送失败兜底 ——
def _fallback() -> str:
    return pick_variant("fallback")


FALLBACK = pick_variant("fallback")

# —— /companion on|off ——
GROUP_ONLY_ON = "诶，这个要去群里才能开啦，阿漂~"
GROUP_ONLY_OFF = "去群里关吧，私聊这边不行嘛~"
GROUP_ON = "好啦，我在听着呢~"
GROUP_OFF = "嗯，那我先去当会儿电子幽灵，安静一下~"

# —— portrait ——
PORTRAIT_PRIVATE_ONLY = "这种事，私下和我说比较好诶。"
PORTRAIT_EMPTY = "这个嘛……我还没什么印象诶。"
PORTRAIT_NO_PERM = "诶，这个我说了不算啦~"
PORTRAIT_REFRESH_OK = "好啦，数据全部重新对齐了~"
PORTRAIT_REFRESH_FAIL = "有点乱……系统稍微卡住了，稍后再试？"

# —— memory ——
MEMORY_CLEAR_SELF_ONLY = "只能清你自己的啦。用 memory clear me 试试？"
MEMORY_CLEARED = "好啦。那就当作重新开始~"

# —— voice ——
VOICE_ON = "开了~想听我说话的话，直接发消息就好。"
VOICE_OFF = "好啦，那先乖乖打字吧。"
VOICE_ON_NO_KEY = "开了，可密钥还没配好诶。面板里记得填「语音API密钥」呀。"

# —— stickers / status ——
STICKERS_RELOADED = "表情包理好啦，总共 {n} 张~"
STICKERS_CATALOG_EMPTY = "还没有表情包素材呢~ 上传几张再来吧。"
STICKERS_CATALOG_OK = "图鉴好啦~ 共 {n} 张 · {tags} 个分类 · {w}×{h}px"
STICKERS_CATALOG_CACHED = "图鉴（缓存）~ 共 {n} 张 · {tags} 个分类 · {w}×{h}px"
STICKERS_UPLOAD_OK = "收好啦~ {id}（来自{source}），现在一共 {n} 张。"
STICKERS_UPLOAD_OK_MULTI = "收好啦~ {count} 张：{ids}（来自{source}），现在一共 {n} 张。"
STICKERS_UPLOAD_NO_PERM = "诶，这个只有管理员能传啦~"
ADMIN_NO_PERM = "这个只有超管能弄啦~"
ADMIN_NEED_TARGET = "要加/删谁呀？@一下，或跟个 QQ 号~"
ADMIN_ADDED = "好啦，已经把 {uid} 设成管理员了~"
ADMIN_EXISTS = "诶，{uid} 本来就是管理员呀。"
ADMIN_REMOVED = "好，{uid} 的管理员没了~"
ADMIN_NOT_FOUND = "名单里没有 {uid} 诶。"
ADMIN_CANNOT_SELF_SUPER = "超管请在面板「超级管理员QQ号」里改，命令管不了超管名单啦。"
ADMIN_LIST_EMPTY = "现在还没有普通管理员。超管可用：/companion admin add @某人"


def stickers_upload_usage() -> str:
    """上传指令用法：情绪表随 tags 词表生成，免手写漏项。"""
    from .stickers.tags import TAG_GLOSSARY

    lines = [
        "用法：上传 <情绪> + 图片（可一次多张附图；也可回复带多图的消息，或跟上多条图片直链）",
        "例：上传 疲惫 + 多图；上传疲惫https://…gif；上传 tired https://a.png https://b.png",
        "可用情绪（中文或英文）：",
    ]
    for tag, gloss in TAG_GLOSSARY.items():
        zh = gloss.split("、")[0].split("（")[0]
        lines.append(f"  · {zh} / {tag}（{gloss}）")
    return "\n".join(lines)


# 兼容旧常量名；运行时请优先 stickers_upload_usage()
STICKERS_UPLOAD_USAGE = stickers_upload_usage()
STATUS_BRIEF = "在呀~ · {name} · 工具 {n_tools} · 表情 {n_stickers} · {voice}"
STATUS_OK_HEADER = "嗯，状态很好，还在线~"

# —— 工具 ACK ——
TOOL_OK_DEFAULT = pick_variant("tool_ok")
TOOL_PARTIAL_FAIL = "有一个小地方没弄好……不过主要的应该没问题！"
TOOL_FAIL = pick_variant("fallback")
TOOL_MISSING = "那个插件没装，或者没开诶。"
TOOL_IMAGE_SEARCH_OK = "图找到了，发你啦~"
TOOL_ASCII2D_OK = "Ascii2D 的检索结果发过去咯~"
TOOL_GOOGLE_OK = "谷歌识图的结果整理好发给你了~"
TOOL_JM_SEARCH_NEED_KW = "想搜什么？把关键词告诉我嘛~"
TOOL_JM_SEARCH_OK = "搜索做完了（结果在回执里）。"
TOOL_JM_SEARCH_EMPTY = "未找到结果，请换具体标签再搜（不要用「随机/随便」当标签）。"
TOOL_JM_SEARCH_BAD_KW = "「{keyword}」不是有效标签，请换具体 tag（如全彩、中文）再调 jmcomic_search。"
TOOL_JM_NEED_ID = "目标 ID 呢？可别漏了~"
TOOL_JM_PREVIEW_OK = "编号 {comic_id} 处理中，等上传回执再说话。"
TOOL_SETU_OK = "图发过去了哦~{detail}"

# —— 其它场景（运行时请用 pick_*，避免复读）——
PRAISE = pick_variant("praise")
UNSURE = pick_variant("unsure")
REUNION = pick_variant("reunion")
REST_GATE = pick_variant("rest_gate")


def pick_praise() -> str:
    return pick_variant("praise")


def pick_unsure() -> str:
    return pick_variant("unsure")


def pick_reunion() -> str:
    return pick_variant("reunion")


def pick_rest_gate() -> str:
    return pick_variant("rest_gate")


def pick_fallback() -> str:
    return pick_variant("fallback")


def pick_tool_ok() -> str:
    return pick_variant("tool_ok")


def pick_greeting() -> str:
    return pick_variant("greeting")


# —— 给模型的节奏示例 ——
PREFACE_EXAMPLES = "「好，正在下载」「等一下嘛~」「我去找找！」"

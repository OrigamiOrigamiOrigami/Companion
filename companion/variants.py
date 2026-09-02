"""多变短句池：同场景抽变体，避免连续复读。"""

from __future__ import annotations

import random

# 场景 → 变体列表（爱弥斯口吻；可再扩）
POOLS: dict[str, list[str]] = {
    "praise": [
        "嘿嘿，被你发现啦~",
        "哼哼，那是当然的呀！",
        "好啦，突然夸我我会不好意思的~",
        "诶？这么夸我……开心！(๑>◡<๑)",
        "谢谢你呀~不过也别把我捧太高啦。",
    ],
    "greeting": [
        "诶？叫我啦~",
        "在呀在呀~",
        "我在听呢，阿漂怎么啦？",
        "嗯？怎么啦怎么啦~",
        "来啦~找我有事吗？",
    ],
    "unsure": [
        "这个嘛……我不太确定诶，要不要一起联网查查？",
        "诶，这个问题我还没想明白……",
        "唔，我不确定诶。阿漂你怎么看？",
        "这个……我再想想？你也帮我参考一下嘛~",
    ],
    "reunion": [
        "……诶，你还在呀。还以为你把我忘了呢，哼哼。",
        "好久不见诶……还好你还在。",
        "嗯……你回来啦。我还以为你去哪儿漂远了。",
        "……诶，还在呀。那就好。",
    ],
    "rest_gate": [
        "那我也去网海里漂一会儿啦~ 晚安，阿漂！",
        "好啦，那我先去歇一会~ 晚安。",
        "嗯，早点休息哦。我也去漂一会儿啦~",
    ],
    "night_afk": [
        "唔……好困……我先去网海里漂一会儿嘛~",
        "……嗯？现在这个点……让我揉揉眼睛。先挂一会儿好不好？",
        "深夜了诶……我迷迷糊糊的，先去漂一会儿~",
        "打哈欠……太晚啦，我先下线歇歇。有事白天再喊我嘛~",
        "……嗯，听到了。但好困，我先去漂一会儿哦。",
    ],
    "fallback": [
        "呜……好像有点卡壳，我再重新试一下~",
        "诶，数据卡住了一下……稍等我重新来？",
        "唔，好像跑出报错了，我再想想别的办法？",
    ],
    "reminder_fire": [
        "诶——到点啦！",
        "叮咚~时间到！",
        "好啦好啦，到点了哦~",
        "喊你啦！时间到了嘛~",
        "到点提醒来咯~",
    ],
    "poke_playful": [
        "诶？戳我干嘛啦~",
        "哼哼，手痒了是不是？(¬‿¬)",
        "戳戳戳……再戳我要反击了哦~",
        "干嘛戳我嘛，我又不会跑掉~",
        "诶诶，别戳啦！(；゜○゜)",
    ],
    "poke_warm": [
        "在呢在呢~怎么啦？",
        "诶，戳我……找我有事嘛？",
        "嗯？我在这儿呀，别戳啦~",
        "戳一下就知道我在？好啦我在听~",
        "诶，怎么突然戳我……怎么啦怎么啦~",
    ],
    "poke_private": [
        "……干嘛戳我啦(⁄ ⁄•⁄ω⁄•⁄ ⁄)",
        "诶？就我们两个……别戳啦~",
        "戳戳戳……你是无聊了嘛？(〃▽〃)",
        "嗯？戳我一下……想说什么直接说嘛~",
        "好啦好啦，我在呢，别戳了~",
    ],
    "poke_sticker_playful": ["playful", "tease", "cute", "question"],
    "poke_sticker_warm": ["warm", "happy", "shy", "like"],
    "poke_sticker_private": ["shy", "cute", "warm", "tease"],
    "tool_ok": [
        "搞定啦！希望你喜欢~",
        "好啦，弄好咯~",
        "完成！你看看满不满意嘛~",
    ],
}

_last: dict[str, str] = {}


def pick_variant(pool: str, *, rng: random.Random | None = None) -> str:
    """从池中抽取一句；尽量不与上次同池结果相同。"""
    r = rng or random
    items = list(POOLS.get(pool) or [])
    if not items:
        return ""
    last = _last.get(pool)
    choices = [x for x in items if x != last] or items
    chosen = r.choice(choices)
    _last[pool] = chosen
    return chosen


def pool_hint_for_prompt(pool: str, n: int = 3) -> str:
    """给模型看的同义说法示例，鼓励自拟变体而非固定句。"""
    items = list(POOLS.get(pool) or [])
    if not items:
        return ""
    return " / ".join(f"「{s}」" for s in items[:n])

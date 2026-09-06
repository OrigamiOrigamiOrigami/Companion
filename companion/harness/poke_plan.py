from __future__ import annotations

import random
from dataclasses import dataclass

from ..variants import pick_variant

# 被戳反应模式（权重见 config poke.reaction_weights）
POKE_MODE_SPEECH_POKE = "speech_poke"
POKE_MODE_SPEECH = "speech"
POKE_MODE_ANTIPOKE = "antipoke"
POKE_MODE_LLM = "llm"

_DEFAULT_WEIGHTS = {
    POKE_MODE_SPEECH_POKE: 40,
    POKE_MODE_SPEECH: 25,
    POKE_MODE_ANTIPOKE: 20,
    POKE_MODE_LLM: 15,
}


@dataclass
class PokePlan:
    """被戳后的轻量反应计划（不经完整 Express）。"""

    mode: str
    bubble: str
    sticker_intent: str
    poke_times: int
    use_llm: bool


def pick_poke_reply(*, familiarity: str, is_private: bool) -> str:
    fam = (familiarity or "stranger").lower()
    if is_private:
        pool = "poke_private"
    elif fam in ("trusted", "close", "intimate"):
        pool = "poke_warm"
    elif fam in ("warming", "friend"):
        pool = "poke_playful"
    else:
        pool = "poke_playful"
    text = pick_variant(pool)
    return text or pick_variant("poke_playful") or "诶？戳我干嘛啦~"


def pick_poke_sticker_intent(*, familiarity: str, is_private: bool) -> str:
    fam = (familiarity or "stranger").lower()
    if is_private:
        return pick_variant("poke_sticker_private") or "shy"
    if fam in ("trusted", "close", "intimate"):
        return pick_variant("poke_sticker_warm") or "warm"
    return pick_variant("poke_sticker_playful") or "playful"


def normalize_poke_weights(raw: dict | None) -> dict[str, float]:
    if not isinstance(raw, dict) or not raw:
        return dict(_DEFAULT_WEIGHTS)
    base = {k: 0.0 for k in _DEFAULT_WEIGHTS}
    for k, v in raw.items():
        key = str(k).strip()
        if key not in base:
            continue
        try:
            w = float(v)
        except (TypeError, ValueError):
            continue
        base[key] = w if w > 0 else 0.0
    if sum(base.values()) <= 0:
        return dict(_DEFAULT_WEIGHTS)
    return base


def pick_poke_mode(weights: dict[str, float] | None = None) -> str:
    wmap = normalize_poke_weights(weights)
    modes = list(wmap.keys())
    ws = [float(wmap[m]) for m in modes]
    return random.choices(modes, weights=ws, k=1)[0]


def plan_poke_reaction(
    *,
    familiarity: str,
    is_private: bool,
    poke_cfg: dict | None = None,
) -> PokePlan:
    """按权重抽被戳反应：说话回戳 / 只说话 / 连戳 / 短 LLM。"""
    cfg = poke_cfg or {}
    mode = pick_poke_mode(cfg.get("reaction_weights"))
    intent = pick_poke_sticker_intent(familiarity=familiarity, is_private=is_private)
    bubble = pick_poke_reply(familiarity=familiarity, is_private=is_private)

    if mode == POKE_MODE_SPEECH:
        return PokePlan(
            mode=mode, bubble=bubble, sticker_intent=intent, poke_times=0, use_llm=False
        )
    if mode == POKE_MODE_ANTIPOKE:
        max_n = int(cfg.get("antipoke_max_times") or 3)
        max_n = max(2, min(5, max_n))
        times = random.randint(2, max_n)
        short = pick_variant("poke_antipoke") or bubble
        return PokePlan(
            mode=mode,
            bubble=short,
            sticker_intent=intent,
            poke_times=times,
            use_llm=False,
        )
    if mode == POKE_MODE_LLM:
        return PokePlan(
            mode=mode,
            bubble=bubble,
            sticker_intent=intent,
            poke_times=1,
            use_llm=True,
        )
    return PokePlan(
        mode=POKE_MODE_SPEECH_POKE,
        bubble=bubble,
        sticker_intent=intent,
        poke_times=1,
        use_llm=False,
    )

"""StickerPicker：Gate → TagMatch → Score → Veto → Weighted Top-K。"""

from __future__ import annotations

import os
import random
from collections import deque
from dataclasses import dataclass
from typing import Any, Optional

from .index import StickerItem, load_sticker_index
from .limits import sticker_max_file_bytes
from .stats import StickerStats
from .tags import DEFAULT_TAGS, INTENT_FALLBACKS, glossary_for, merge_allow_tags


@dataclass
class PickResult:
    stage: str  # gated | no_candidate | veto | sent
    score: float = 0.0
    sticker_id: str | None = None
    path: str | None = None
    intent: str = "none"
    item: StickerItem | None = None


class StickerPicker:
    def __init__(
        self,
        config: dict[str, Any],
        card_dir: str,
        data_override_dir: str = "",
        *,
        character_id: str = "",
    ):
        self.config = config or {}
        self.card_dir = card_dir
        self.data_override_dir = data_override_dir
        self.character_id = (character_id or "").strip() or os.path.basename(
            (data_override_dir or card_dir or "").rstrip("/\\")
        )
        self.items: list[StickerItem] = []
        self._cooldown: dict[str, int] = {}
        self._recent_intents: deque[str] = deque(maxlen=16)
        stats_path = ""
        if self.data_override_dir:
            stats_path = os.path.join(self.data_override_dir, "_emotion_stats.json")
        self.stats = StickerStats(path=stats_path)
        self.reload()

    @property
    def allow_tags(self) -> list[str]:
        return merge_allow_tags(DEFAULT_TAGS, list(self.config.get("allow_tags") or []))

    def tag_glossary_line(self, tags: list[str] | None = None) -> str:
        return glossary_for(tags or self.allow_tags)

    def recent_intents(self, n: int = 5) -> list[str]:
        if n <= 0:
            return []
        items = list(self._recent_intents)
        return items[-n:]

    def inventory_by_tag(self) -> dict[str, int]:
        """allow_tags → 库存张数（含 0）。"""
        counts: dict[str, int] = {t: 0 for t in self.allow_tags}
        for it in self.items:
            tag = (it.primary_tag or "").strip().lower()
            if tag in counts:
                counts[tag] += 1
            elif tag:
                counts[tag] = counts.get(tag, 0) + 1
        return counts

    def empty_tags(self) -> list[str]:
        """有 allow、库存为 0 的 tag（建议补图或依赖近义回退）。"""
        return [t for t, n in self.inventory_by_tag().items() if n <= 0 and t in self.allow_tags]

    def reload(self) -> int:
        self.items = load_sticker_index(
            card_dir=self.card_dir,
            data_override_dir=self.data_override_dir,
            allow_tags=list(self.config.get("allow_tags") or []),
            max_file_bytes=sticker_max_file_bytes(self.config),
            character_id=self.character_id,
        )
        return len(self.items)

    def _tick(self) -> None:
        done = [k for k, v in self._cooldown.items() if v <= 1]
        for k in list(self._cooldown):
            self._cooldown[k] -= 1
        for k in done:
            self._cooldown.pop(k, None)

    def pick(
        self, *, wanted: bool, intent: str, active_form: str
    ) -> Optional[StickerItem]:
        """兼容旧调用：仅返回 StickerItem | None。完整结果见 pick_detailed。"""
        result = self.pick_detailed(wanted=wanted, intent=intent, active_form=active_form)
        return result.item if result.stage == "sent" else None

    def pick_detailed(
        self, *, wanted: bool, intent: str, active_form: str
    ) -> PickResult:
        self._tick()
        intent_n = (intent or "none").strip().lower() or "none"
        form = (active_form or "default").strip().lower() or "default"

        if not self.config.get("enabled", True) or not wanted:
            self.stats.record("gated", intent_n)
            return PickResult(stage="gated", intent=intent_n)
        if intent_n == "none" or intent_n not in self.allow_tags:
            self.stats.record("gated", intent_n)
            return PickResult(stage="gated", intent=intent_n)
        if not self.items:
            self.stats.record("no_candidate", intent_n)
            return PickResult(stage="no_candidate", intent=intent_n)

        pool = [
            it
            for it in self.items
            if it.form in (form, "shared") and it.sticker_id not in self._cooldown
        ]
        primary = [it for it in pool if it.primary_tag == intent_n]
        secondary = [it for it in pool if intent_n in it.tags and it.primary_tag != intent_n]
        cands = primary or secondary
        # 无精确 tag 资源时按近义回退（如 happy → warm/playful）
        if not cands:
            for alt in INTENT_FALLBACKS.get(intent_n, ()):
                alt_cands = [it for it in pool if it.primary_tag == alt or alt in it.tags]
                if alt_cands:
                    cands = alt_cands
                    break
        if not cands:
            self.stats.record("no_candidate", intent_n)
            return PickResult(stage="no_candidate", intent=intent_n)

        window = int(self.config.get("intent_repeat_window") or 3)
        recent = self.recent_intents(window)
        recent_same = sum(1 for x in recent if x == intent_n)

        def score(it: StickerItem) -> float:
            tag_score = 1.0 if it.primary_tag == intent_n else 0.6
            form_score = 1.0 if it.form == form else 0.75
            freshness = 1.0
            if recent_same >= 2:
                freshness = 0.55
            elif recent_same == 1:
                freshness = 0.75
            return tag_score * form_score * max(0.01, it.weight) * freshness

        scored = sorted(((score(it), it) for it in cands), key=lambda x: x[0], reverse=True)
        min_score = float(self.config.get("min_match_score") or 0.55)
        scored = [(s, it) for s, it in scored if s >= min_score]
        if not scored:
            self.stats.record("veto", intent_n)
            return PickResult(stage="veto", intent=intent_n, score=0.0)

        top = scored[: int(self.config.get("top_k") or 5)]
        chosen = random.choices([it for _, it in top], weights=[s for s, _ in top], k=1)[0]
        chosen_score = next(s for s, it in top if it.sticker_id == chosen.sticker_id)
        self._cooldown[chosen.sticker_id] = int(self.config.get("cooldown_turns") or 8)
        self._recent_intents.append(intent_n)
        self.stats.record("sent", intent_n)
        return PickResult(
            stage="sent",
            score=float(chosen_score),
            sticker_id=chosen.sticker_id,
            path=chosen.path,
            intent=intent_n,
            item=chosen,
        )

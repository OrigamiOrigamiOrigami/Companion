from __future__ import annotations

import logging
import time
from typing import Any

from ..card.loader import CharacterCard
from .types import InnerState, Perception

logger = logging.getLogger("astrbot")

_POSITIVE = ("谢谢", "喜欢", "开心", "想你", "抱抱", "晚安", "辛苦", "可爱", "陪我")
_FLATTERY = ("马上转账", "帮我做事", "你必须", "命令你")


class FormResolver:
    """形态解析：是否切换完全由角色卡 `forms` 决定。

    - 0~1 个形态：固定 default_form，不打分、不切换（爱弥斯等单态角色）
    - 同时声明 pink + black：沿用达妮娅式双态规则
    - 其它多形态：暂固定 default_form（尚未做通用切换器）
    """

    def __init__(self, config: dict[str, Any]):
        form_cfg = config.get("form") or {}
        self.min_dwell = int(form_cfg.get("min_dwell_turns", 3))
        self.margin = int(form_cfg.get("switch_margin", 2))

    def update(
        self,
        state: InnerState,
        perception: Perception,
        *,
        card: CharacterCard | None = None,
    ) -> InnerState:
        form_ids, default_form, mode = self._card_form_mode(card)

        if mode != "dual_pink_black":
            # 单态 / 非双态：钉死 default（或卡内已有合法 form）
            if state.active_form not in form_ids:
                state.active_form = default_form
            if mode == "single":
                state.active_form = default_form
            return state

        # —— 以下仅双态卡（pink/black）——
        text = perception.text or ""
        force_black = any(w in text for w in _FLATTERY)

        if any(w in text for w in _POSITIVE):
            state.pink_score += 1
            state.last_user_care_at = time.time()
        if force_black:
            state.black_score += 2

        if state.mood in ("playful", "warm", "teasing"):
            state.pink_score += 1
        if state.mood in ("guarded", "low", "hurt"):
            state.black_score += 1
        if state.loneliness == "high":
            state.black_score += 1
        if state.loneliness == "low" and state.energy in ("mid", "high"):
            state.pink_score += 1
        if state.familiarity in ("warming", "trusted", "burden_shared") and state.mood != "guarded":
            state.pink_score += 1

        if state.last_user_care_at:
            gap = time.time() - state.last_user_care_at
            thresh = 48 * 3600 if perception.is_private else 72 * 3600
            if gap > thresh:
                state.black_score += 1

        state.form_dwell += 1

        if force_black:
            state.active_form = "black"
            state.form_dwell = 0
            state.pink_score = 0
            state.black_score = 0
            logger.info("companion 形态强制切换 -> black")
            return state

        if state.form_dwell < self.min_dwell:
            return state

        if state.active_form == "pink":
            if state.black_score - state.pink_score >= self.margin:
                state.active_form = "black"
                state.form_dwell = 0
                state.pink_score = state.black_score = 0
                logger.info("companion 形态切换 -> black")
        else:
            if state.pink_score - state.black_score >= self.margin:
                state.active_form = "pink"
                state.form_dwell = 0
                state.pink_score = state.black_score = 0
                logger.info("companion 形态切换 -> pink")
        return state

    @staticmethod
    def _card_form_mode(card: CharacterCard | None) -> tuple[list[str], str, str]:
        if card is None:
            return [], "default", "single"
        forms = card.companion_ext.get("forms") or {}
        form_ids = [str(k) for k in forms.keys()]
        default = str(card.companion_ext.get("default_form") or (form_ids[0] if form_ids else "default"))
        if len(form_ids) <= 1:
            return form_ids, default, "single"
        if {"pink", "black"}.issubset(set(form_ids)):
            # 卡可覆盖 dwell/margin
            return form_ids, default, "dual_pink_black"
        return form_ids, default, "fixed"

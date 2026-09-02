"""表情包情绪选用统计：按 intent 累计，落盘可查高频。"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from typing import Any

from .tags import TAG_GLOSSARY

logger = logging.getLogger("astrbot")

_STAGES = ("sent", "veto", "no_candidate", "gated")


class StickerStats:
    def __init__(self, path: str = "") -> None:
        self.path = (path or "").strip()
        self.totals: dict[str, int] = {k: 0 for k in _STAGES}
        self.by_intent: dict[str, dict[str, int]] = defaultdict(
            lambda: {k: 0 for k in _STAGES}
        )
        if self.path:
            self.load()

    def record(self, stage: str, intent: str = "") -> None:
        key = stage if stage in self.totals else "gated"
        self.totals[key] = int(self.totals.get(key) or 0) + 1
        tag = (intent or "none").strip().lower() or "none"
        row = self.by_intent[tag]
        row[key] = int(row.get(key) or 0) + 1
        self.save()

    def reset(self) -> None:
        self.totals = {k: 0 for k in _STAGES}
        self.by_intent = defaultdict(lambda: {k: 0 for k in _STAGES})
        self.save()

    def as_dict(self) -> dict[str, Any]:
        return {
            "sent": self.totals["sent"],
            "veto": self.totals["veto"],
            "no_candidate": self.totals["no_candidate"],
            "gated": self.totals["gated"],
            "by_intent": {k: dict(v) for k, v in sorted(self.by_intent.items())},
        }

    def load(self) -> None:
        if not self.path or not os.path.isfile(self.path):
            return
        try:
            raw = json.load(open(self.path, encoding="utf-8")) or {}
        except Exception as e:
            logger.warning("companion 表情统计读盘失败: %s", e)
            return
        totals = raw.get("totals") or raw
        for k in _STAGES:
            if k in totals:
                self.totals[k] = int(totals.get(k) or 0)
        by = raw.get("by_intent") or {}
        if isinstance(by, dict):
            for intent, row in by.items():
                if not isinstance(row, dict):
                    continue
                tag = str(intent or "none").strip().lower() or "none"
                self.by_intent[tag] = {
                    k: int(row.get(k) or 0) for k in _STAGES
                }

    def save(self) -> None:
        if not self.path:
            return
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            payload = {
                "totals": dict(self.totals),
                "by_intent": {
                    k: dict(v) for k, v in sorted(self.by_intent.items())
                },
            }
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("companion 表情统计写盘失败: %s", e)

    def top_sent(self, limit: int = 12) -> list[tuple[str, int]]:
        """按已发送次数降序；(intent, count)，跳过 0。"""
        rows = [
            (intent, int((row or {}).get("sent") or 0))
            for intent, row in self.by_intent.items()
        ]
        rows = [(i, n) for i, n in rows if n > 0]
        rows.sort(key=lambda x: (-x[1], x[0]))
        return rows[: max(0, limit)]

    def format_brief(self, *, top: int = 12) -> str:
        t = self.totals
        sent_total = int(t.get("sent") or 0)
        lines = [
            "表情情绪统计（累计，重载后保留）",
            f"合计：已发送={t['sent']} 否决={t['veto']} "
            f"无候选={t['no_candidate']} 未请求={t['gated']}",
        ]
        ranked = self.top_sent(limit=top)
        if ranked:
            lines.append("高频情绪（按已发送）：")
            for i, (intent, n) in enumerate(ranked, 1):
                gloss = TAG_GLOSSARY.get(intent, "")
                label = f"{intent}" + (f"（{gloss}）" if gloss else "")
                pct = f" {n * 100 // sent_total}%" if sent_total else ""
                lines.append(f"  {i}. {label} · {n}次{pct}")
        else:
            lines.append("还没有成功发出过表情包呢~")

        # 有否决/无候选的意图：素材缺口提示
        gaps: list[str] = []
        for intent, row in sorted(self.by_intent.items()):
            miss = int(row.get("veto") or 0) + int(row.get("no_candidate") or 0)
            if miss <= 0:
                continue
            gloss = TAG_GLOSSARY.get(intent, "")
            label = f"{intent}" + (f"/{gloss.split('、')[0]}" if gloss else "")
            gaps.append(f"{label}×{miss}")
        if gaps:
            lines.append("素材缺口（否决+无候选）：" + "、".join(gaps[:8]))
            if len(gaps) > 8:
                lines.append(f"  …另有 {len(gaps) - 8} 项")

        lines.append("清零：表情统计 清零 或 /伴侣 情绪统计 清零")
        return "\n".join(lines)

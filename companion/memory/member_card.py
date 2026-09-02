from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger("astrbot")


def empty_member_card(user_id: str = "") -> dict[str, Any]:
    return {
        "user_id": str(user_id or ""),
        "display_name": "",
        "aliases": [],
        "traits": [],
        "notes": "",
        "updated_at": "",
    }


class MemberCardStore:
    """群维度成员卡：外号 / 特征，供注入与日后跨人解析。"""

    def __init__(self, memory_root: str):
        self.root = memory_root

    def _path(self, group_id: str, user_id: str) -> str:
        g = str(group_id).replace(":", "_")
        d = os.path.join(self.root, "groups", f"group_{g}", "members")
        os.makedirs(d, exist_ok=True)
        return os.path.join(d, f"{user_id}.json")

    def load(self, group_id: str, user_id: str) -> dict[str, Any]:
        path = self._path(group_id, user_id)
        if not os.path.isfile(path):
            return empty_member_card(user_id)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f) or {}
        except Exception as e:
            logger.warning("群友卡加载失败: %s", e)
            return empty_member_card(user_id)
        base = empty_member_card(user_id)
        base.update(data)
        base["user_id"] = str(user_id)
        base["aliases"] = list(base.get("aliases") or [])
        base["traits"] = list(base.get("traits") or [])
        return base

    def save(self, group_id: str, user_id: str, data: dict[str, Any]) -> None:
        path = self._path(group_id, user_id)
        payload = empty_member_card(user_id)
        payload.update(data or {})
        payload["user_id"] = str(user_id)
        payload["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("群友卡写入失败: %s", e)

    def touch_display_name(
        self,
        group_id: str,
        user_id: str,
        display_name: str,
    ) -> dict[str, Any]:
        """轻量更新群名片；旧名可进 aliases。"""
        name = (display_name or "").strip()[:32]
        card = self.load(group_id, user_id)
        if not name:
            return card
        old = (card.get("display_name") or "").strip()
        aliases = [a for a in (card.get("aliases") or []) if a]
        if old and old != name and old not in aliases:
            aliases.append(old)
        card["display_name"] = name
        card["aliases"] = aliases[-12:]
        self.save(group_id, user_id, card)
        return card

    def format_card_line(self, card: dict[str, Any], *, label: str = "") -> str:
        name = (card.get("display_name") or card.get("user_id") or "?").strip()
        aliases = [a for a in (card.get("aliases") or []) if a and a != name][:4]
        traits = [t for t in (card.get("traits") or []) if t][:4]
        notes = (card.get("notes") or "").strip()[:80]
        parts = [f"{label}{name}" if label else name]
        if card.get("user_id"):
            parts.append(f"QQ={card['user_id']}")
        if aliases:
            parts.append("外号=" + "/".join(aliases))
        if traits:
            parts.append("特征=" + "、".join(traits))
        if notes:
            parts.append(notes)
        return "；".join(parts)

    def inject_block(
        self,
        group_id: str,
        speaker_id: str,
        *,
        neighbor_ids: list[str] | None = None,
        max_neighbors: int = 3,
    ) -> str:
        lines: list[str] = []
        speaker = self.load(group_id, speaker_id)
        if speaker.get("display_name") or speaker.get("aliases") or speaker.get("traits"):
            lines.append("【群友卡·对方】" + self.format_card_line(speaker))
        seen = {str(speaker_id)}
        for uid in neighbor_ids or []:
            uid = str(uid)
            if not uid or uid in seen:
                continue
            seen.add(uid)
            card = self.load(group_id, uid)
            if not (card.get("display_name") or card.get("aliases") or card.get("traits")):
                continue
            lines.append("【群友卡】" + self.format_card_line(card))
            if len(lines) >= 1 + max_neighbors:
                break
        return "\n".join(lines)

    def _members_dir(self, group_id: str) -> str:
        g = str(group_id).replace(":", "_")
        return os.path.join(self.root, "groups", f"group_{g}", "members")

    def list_group_cards(self, group_id: str) -> list[dict[str, Any]]:
        d = self._members_dir(group_id)
        if not os.path.isdir(d):
            return []
        out: list[dict[str, Any]] = []
        for name in os.listdir(d):
            if not name.endswith(".json") or name.startswith("_"):
                continue
            uid = name[:-5]
            if not uid.isdigit():
                continue
            out.append(self.load(group_id, uid))
        return out

    def build_at_name_index(self, group_id: str) -> dict[str, str]:
        """昵称/外号 → QQ。同名冲突时保留先写入的。"""
        index: dict[str, str] = {}
        for card in self.list_group_cards(group_id):
            uid = str(card.get("user_id") or "").strip()
            if not uid:
                continue
            names: list[str] = []
            dn = (card.get("display_name") or "").strip()
            if dn:
                names.append(dn)
            for a in card.get("aliases") or []:
                a = str(a or "").strip()
                if a:
                    names.append(a)
            for n in names:
                if n not in index:
                    index[n] = uid
                elif index[n] != uid:
                    logger.debug(
                        "companion @名冲突 name=%s qq=%s/%s", n, index[n], uid
                    )
        return index

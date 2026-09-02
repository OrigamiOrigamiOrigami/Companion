from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Optional

import yaml

from .character_book import CharacterBook, load_character_book
from .sanitize import sanitize

logger = logging.getLogger("astrbot")


@dataclass
class CharacterCard:
    id: str
    display_name: str
    aliases: list[str] = field(default_factory=list)
    wake_words: list[str] = field(default_factory=list)
    prompt: str = ""
    tone_reference: str = ""
    anchors: str = ""
    forms: dict[str, str] = field(default_factory=dict)
    companion_ext: dict[str, Any] = field(default_factory=dict)
    root_dir: str = ""
    character_book: CharacterBook | None = None


class CardLoader:
    def __init__(self, plugin_root: str, data_dir: str, max_prompt_bytes: int = 12000):
        self.plugin_root = plugin_root
        self.data_dir = data_dir
        self.max_prompt_bytes = max_prompt_bytes
        self._cache: dict[str, CharacterCard] = {}

    def load(self, card_id: str) -> CharacterCard:
        if card_id in self._cache:
            return self._cache[card_id]
        path = self._resolve(card_id)
        if not path:
            raise FileNotFoundError(f"character not found: {card_id}")
        card = self._load_dir(card_id, path)
        self._cache[card_id] = card
        return card

    def reload(self, card_id: str) -> CharacterCard:
        self._cache.pop(card_id, None)
        return self.load(card_id)

    def _resolve(self, card_id: str) -> Optional[str]:
        for base in (
            os.path.join(self.data_dir, "characters"),
            os.path.join(self.plugin_root, "characters"),
        ):
            p = os.path.join(base, card_id)
            if os.path.isfile(os.path.join(p, "card.yaml")):
                return p
        return None

    def _load_dir(self, card_id: str, path: str) -> CharacterCard:
        with open(os.path.join(path, "card.yaml"), "r", encoding="utf-8") as f:
            meta = yaml.safe_load(f) or {}

        ext_root = meta.get("extensions") or {}
        # 新键 companion；兼容旧卡 extensions.daniya
        ext = ext_root.get("companion") or ext_root.get("daniya") or {}

        prompt = ""
        prompt_path = os.path.join(path, "prompt.md")
        if os.path.isfile(prompt_path):
            with open(prompt_path, "r", encoding="utf-8") as f:
                prompt = sanitize(f.read(), max_bytes=self.max_prompt_bytes)

        tone_reference = ""
        tone_rel = ext.get("tone_reference") or "reference/voice_and_lore.md"
        tone_path = os.path.join(path, str(tone_rel))
        if os.path.isfile(tone_path):
            tone_cap = int(ext.get("tone_reference_max_bytes") or 6000)
            with open(tone_path, "r", encoding="utf-8") as f:
                tone_reference = sanitize(f.read(), max_bytes=tone_cap)

        anchors = ""
        anchors_rel = ext.get("anchors") or ""
        if anchors_rel:
            anchors_path = os.path.join(path, str(anchors_rel))
            if os.path.isfile(anchors_path):
                anchors_cap = int(ext.get("anchors_max_bytes") or 5000)
                with open(anchors_path, "r", encoding="utf-8") as f:
                    anchors = sanitize(f.read(), max_bytes=anchors_cap)

        forms: dict[str, str] = {}
        for fid, fmeta in (ext.get("forms") or {}).items():
            rel = (fmeta or {}).get("overlay") or f"forms/{fid}.md"
            fp = os.path.join(path, rel)
            if os.path.isfile(fp):
                with open(fp, "r", encoding="utf-8") as f:
                    forms[fid] = f.read().strip()

        aliases = list(meta.get("aliases") or [])
        wake = list(meta.get("wake_words") or [])
        if not wake:
            wake = [meta.get("display_name") or card_id, *aliases]

        character_book = None
        book_rel = ext.get("character_book") or ""
        if book_rel:
            book_path = os.path.join(path, str(book_rel))
            book_cap = int(ext.get("character_book_max_bytes") or 80000)
            character_book = load_character_book(book_path, max_bytes=book_cap)
            if character_book is not None:
                logger.info(
                    "角色书已加载 卡=%s 条目=%s 预算=%s",
                    card_id,
                    len(character_book.entries),
                    character_book.token_budget,
                )

        return CharacterCard(
            id=meta.get("id") or card_id,
            display_name=meta.get("display_name") or card_id,
            aliases=aliases,
            wake_words=[w for w in wake if w],
            prompt=prompt,
            tone_reference=tone_reference,
            anchors=anchors,
            forms=forms,
            companion_ext=ext,
            root_dir=path,
            character_book=character_book,
        )

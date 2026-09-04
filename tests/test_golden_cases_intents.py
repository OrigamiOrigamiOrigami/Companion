"""Validate golden_cases intents stay inside sticker glossary / card allow-list."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[1]
_STICKERS = _ROOT / "companion" / "stickers"


def _ensure_pkg(name: str, path: Path | None = None):
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    if path is not None:
        mod.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = mod
    return mod


def _load_as(fullname: str, path: Path):
    parent = fullname.rpartition(".")[0]
    spec = importlib.util.spec_from_file_location(fullname, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = parent
    sys.modules[fullname] = mod
    spec.loader.exec_module(mod)
    return mod


_ensure_pkg("companion", _ROOT / "companion")
_ensure_pkg("companion.stickers", _STICKERS)
tags = _load_as("companion.stickers.tags", _STICKERS / "tags.py")
TAG_GLOSSARY = tags.TAG_GLOSSARY
DEFAULT_TAGS = tags.DEFAULT_TAGS
resolve_tag = tags.resolve_tag


def _load_yaml(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _card_tags(card_path: Path) -> set[str]:
    data = _load_yaml(card_path)
    extensions = data.get("extensions") or {}
    # Aemeath: extensions.companion; legacy daniya: extensions.daniya
    for block in extensions.values():
        if not isinstance(block, dict):
            continue
        tag_list = block.get("sticker_tags") or []
        if tag_list:
            return {str(t).strip().lower() for t in tag_list if t}
    return set()


def _collect_intents(cases: list) -> set[str]:
    found: set[str] = set()
    for case in cases or []:
        if not isinstance(case, dict):
            continue
        for key in ("expect_intent", "expect_intent_in"):
            for item in case.get(key) or []:
                s = str(item).strip().lower()
                if s and s != "none":
                    found.add(s)
        for key in ("force_intent", "inject_intent"):
            raw = case.get(key)
            if raw:
                s = str(raw).strip().lower()
                if s and s != "none" and not s.endswith("_99"):
                    found.add(s)
        for item in case.get("empty_tags") or []:
            s = str(item).strip().lower()
            if s:
                found.add(s)
        for item in case.get("forbid_tags") or []:
            s = str(item).strip().lower()
            if s:
                found.add(s)
    return found


class GoldenCasesIntentTests(unittest.TestCase):
    def test_aemeath_intents_in_glossary_and_card(self) -> None:
        card = _ROOT / "characters" / "Aemeath" / "card.yaml"
        golden = _ROOT / "characters" / "Aemeath" / "stickers" / "golden_cases.yaml"
        allow = _card_tags(card)
        data = _load_yaml(golden)
        intents = _collect_intents(data.get("cases") or [])
        self.assertTrue(intents)
        for intent in intents:
            self.assertIn(intent, TAG_GLOSSARY, msg=f"unknown tag in golden: {intent}")
            self.assertIn(intent, allow, msg=f"golden intent not on card allow: {intent}")
            self.assertIn(intent, DEFAULT_TAGS)

    def test_daniya_intents_in_glossary_and_card(self) -> None:
        card = _ROOT / "characters" / "daniya" / "card.yaml"
        golden = _ROOT / "characters" / "daniya" / "stickers" / "golden_cases.yaml"
        allow = _card_tags(card)
        data = _load_yaml(golden)
        intents = _collect_intents(data.get("cases") or [])
        self.assertTrue(intents)
        for intent in intents:
            self.assertIn(intent, TAG_GLOSSARY, msg=f"unknown tag in golden: {intent}")
            self.assertIn(intent, allow, msg=f"golden intent not on card allow: {intent}")

    def test_no_retired_tags(self) -> None:
        for retired in ("lonely", "guarded"):
            self.assertIsNone(resolve_tag(retired))
            self.assertNotIn(retired, TAG_GLOSSARY)

    def test_empty_bucket_fallbacks_exist(self) -> None:
        for tag in ("shy", "cute", "thinking", "reject", "mock", "surprise"):
            self.assertTrue(tags.INTENT_FALLBACKS.get(tag), msg=f"missing fallbacks for {tag}")


if __name__ == "__main__":
    unittest.main()

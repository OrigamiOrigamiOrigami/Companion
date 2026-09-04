"""Seam tests: sticker tag resolution + catalog layout height budget."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STICKERS = _ROOT / "companion" / "stickers"


def _ensure_pkg(name: str, path: Path | None = None) -> types.ModuleType:
    if name in sys.modules:
        return sys.modules[name]
    mod = types.ModuleType(name)
    if path is not None:
        mod.__path__ = [str(path)]  # type: ignore[attr-defined]
    sys.modules[name] = mod
    return mod


def _load_as(fullname: str, path: Path):
    parent = fullname.rpartition(".")[0]
    spec = importlib.util.spec_from_file_location(
        fullname,
        path,
        submodule_search_locations=[str(path.parent)],
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    mod.__package__ = parent
    sys.modules[fullname] = mod
    spec.loader.exec_module(mod)
    return mod


_ensure_pkg("companion", _ROOT / "companion")
_ensure_pkg("companion.stickers", _STICKERS)

tags = _load_as("companion.stickers.tags", _STICKERS / "tags.py")

_index_stub = types.ModuleType("companion.stickers.index")


class StickerItem:
    def __init__(self, sticker_id, path, form, primary_tag, tags=None, weight=1.0):
        self.sticker_id = sticker_id
        self.path = path
        self.form = form
        self.primary_tag = primary_tag
        self.tags = tags or []
        self.weight = weight


_index_stub.StickerItem = StickerItem
sys.modules["companion.stickers.index"] = _index_stub

gallery_mod = _load_as("companion.stickers.gallery", _STICKERS / "gallery.py")

TAG_GLOSSARY = tags.TAG_GLOSSARY
DEFAULT_TAGS = tags.DEFAULT_TAGS
INTENT_FALLBACKS = tags.INTENT_FALLBACKS
resolve_tag = tags.resolve_tag


class TagResolutionTests(unittest.TestCase):
    def test_sleep_and_reject_keys(self) -> None:
        self.assertIn("sleep", TAG_GLOSSARY)
        self.assertIn("reject", TAG_GLOSSARY)
        self.assertIn("mock", TAG_GLOSSARY)
        self.assertIn("surprise", TAG_GLOSSARY)
        self.assertNotIn("lonely", TAG_GLOSSARY)
        self.assertNotIn("guarded", TAG_GLOSSARY)

    def test_order_neighbors(self) -> None:
        self.assertEqual(DEFAULT_TAGS[DEFAULT_TAGS.index("tired") + 1], "sleep")
        self.assertEqual(DEFAULT_TAGS[DEFAULT_TAGS.index("angry") + 1], "reject")
        self.assertEqual(DEFAULT_TAGS[DEFAULT_TAGS.index("playful") + 1], "mock")
        self.assertEqual(DEFAULT_TAGS[DEFAULT_TAGS.index("speechless") + 1], "surprise")

    def test_aliases(self) -> None:
        self.assertEqual(resolve_tag("困"), "sleep")
        self.assertEqual(resolve_tag("睡觉"), "sleep")
        self.assertEqual(resolve_tag("晚安"), "sleep")
        self.assertEqual(resolve_tag("拒绝"), "reject")
        self.assertEqual(resolve_tag("嫌弃"), "reject")
        self.assertEqual(resolve_tag("疲惫"), "tired")
        self.assertEqual(resolve_tag("嘲笑"), "mock")
        self.assertEqual(resolve_tag("嘲讽"), "mock")
        self.assertEqual(resolve_tag("惊讶"), "surprise")
        self.assertEqual(resolve_tag("吃惊"), "surprise")
        self.assertIsNone(resolve_tag("寂寞"))
        self.assertIsNone(resolve_tag("防备"))

    def test_fallbacks(self) -> None:
        self.assertEqual(INTENT_FALLBACKS["sleep"][0], "tired")
        self.assertEqual(INTENT_FALLBACKS["reject"][0], "angry")
        self.assertEqual(INTENT_FALLBACKS["mock"][0], "tease")
        self.assertEqual(INTENT_FALLBACKS["surprise"][0], "speechless")
        self.assertNotIn("lonely", INTENT_FALLBACKS)
        self.assertNotIn("guarded", INTENT_FALLBACKS)


class CatalogLayoutTests(unittest.TestCase):
    def test_layout_height_matches_draw_budget(self) -> None:
        items = []
        for tag in DEFAULT_TAGS:
            for i in range(1, 4):
                items.append(
                    StickerItem(
                        sticker_id=f"Char_{tag}_{i:02d}",
                        path=f"/tmp/Char_{tag}_{i:02d}.png",
                        form="default",
                        primary_tag=tag,
                    )
                )
        by: dict[str, list] = {}
        for it in items:
            by.setdefault(it.primary_tag, []).append(it)
        groups = [(tag, by[tag]) for tag in DEFAULT_TAGS if tag in by]
        thumb, cols = 96, 8
        budget = gallery_mod._layout_height(groups, thumb_size=thumb, cols=cols)
        expected = gallery_mod._PAD + gallery_mod._TITLE_H + gallery_mod._PAD
        for _tag, rows in groups:
            n_rows = (len(rows) + cols - 1) // cols
            expected += (
                gallery_mod._HEADER_H
                + gallery_mod._SECTION_GAP
                + n_rows * (thumb + gallery_mod._CAPTION_H + gallery_mod._GAP)
                + gallery_mod._PAD
            )
        self.assertEqual(budget, expected)
        y2 = gallery_mod._PAD + gallery_mod._TITLE_H
        last_tag = groups[-1][0]
        for tag, rows in groups[:-1]:
            y2 += gallery_mod._HEADER_H + gallery_mod._SECTION_GAP
            n_rows = (len(rows) + cols - 1) // cols
            y2 += n_rows * (thumb + gallery_mod._CAPTION_H + gallery_mod._GAP) + gallery_mod._PAD
        self.assertLessEqual(
            y2 + gallery_mod._HEADER_H + thumb,
            budget,
            msg=f"last tag {last_tag} would be clipped",
        )

    def test_build_catalog_includes_last_tag(self) -> None:
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            items = []
            for tag in DEFAULT_TAGS:
                path = os.path.join(tmp, f"Char_{tag}_01.png")
                Image.new("RGB", (64, 64), (200, 100, 50)).save(path)
                items.append(
                    StickerItem(
                        sticker_id=f"Char_{tag}_01",
                        path=path,
                        form="default",
                        primary_tag=tag,
                    )
                )
            out = os.path.join(tmp, "_catalog.png")
            result = gallery_mod.build_sticker_catalog(
                items,
                output_path=out,
                title="test",
                thumb_size=64,
                cols=6,
            )
            self.assertEqual(result["tags"], len(DEFAULT_TAGS))
            self.assertTrue(os.path.isfile(out))
            self.assertEqual(DEFAULT_TAGS[-1], "approve")


if __name__ == "__main__":
    unittest.main()

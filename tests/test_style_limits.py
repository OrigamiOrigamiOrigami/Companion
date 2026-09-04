"""Outbound bubble limit resolution (panel vs card)."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_HARNESS = _ROOT / "companion" / "harness"


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
_ensure_pkg("companion.harness", _HARNESS)
_ensure_pkg("companion.provider", _ROOT / "companion" / "provider")

# outbound_sanitize imports sanitize_visible_text from openai_compat — stub it
prov = types.ModuleType("companion.provider.openai_compat")
prov.sanitize_visible_text = lambda t, **kw: t  # type: ignore[attr-defined]
sys.modules["companion.provider.openai_compat"] = prov

sanitize = _load_as(
    "companion.harness.outbound_sanitize",
    _HARNESS / "outbound_sanitize.py",
)
resolve_style_limits = sanitize.resolve_style_limits
finalize_outbound_bubbles = sanitize.finalize_outbound_bubbles


class ResolveStyleLimitsTests(unittest.TestCase):
    def test_panel_overrides_card(self) -> None:
        bubbles, chars = resolve_style_limits(
            {"max_bubbles": 3, "max_chars": 280},
            {"max_bubbles": 1, "max_chars": 100},
        )
        self.assertEqual(bubbles, 1)
        self.assertEqual(chars, 100)

    def test_card_fills_when_panel_missing(self) -> None:
        bubbles, chars = resolve_style_limits(
            {"max_bubbles": 2, "max_chars": 80},
            {},
        )
        self.assertEqual(bubbles, 2)
        self.assertEqual(chars, 80)

    def test_multi_bubble_false_forces_one(self) -> None:
        bubbles, _ = resolve_style_limits(
            {"max_bubbles": 3, "multi_bubble": False},
            {"max_bubbles": 5},
        )
        self.assertEqual(bubbles, 1)

    def test_finalize_respects_max_bubbles(self) -> None:
        out = finalize_outbound_bubbles(
            ["一", "二", "三", "四"],
            max_bubbles=2,
            max_chars=500,
            fallback="x",
        )
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0], "一")
        self.assertIn("二", out[1])


if __name__ == "__main__":
    unittest.main()

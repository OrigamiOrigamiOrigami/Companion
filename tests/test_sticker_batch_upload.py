"""Batch sticker upload: sequential seq allocation."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_STICKERS = _ROOT / "companion" / "stickers"
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


# upload.py imports ImagePayload from harness.media — stub media only
_ensure_pkg("companion", _ROOT / "companion")
_ensure_pkg("companion.harness", _HARNESS)
_ensure_pkg("companion.stickers", _STICKERS)

media_stub = types.ModuleType("companion.harness.media")


class ImagePayload:
    def __init__(self, data: bytes, mime: str = "image/png", ext: str = ".png", source: str = "message"):
        self.data = data
        self.mime = mime
        self.ext = ext
        self.source = source


media_stub.ImagePayload = ImagePayload  # type: ignore[attr-defined]
sys.modules["companion.harness.media"] = media_stub

upload = _load_as("companion.stickers.upload", _STICKERS / "upload.py")


class BatchUploadSeqTests(unittest.TestCase):
    def test_sequential_saves_increment_seq(self) -> None:
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 80
        with tempfile.TemporaryDirectory() as tmp:
            ids = []
            for _ in range(3):
                info = upload.save_sticker_file(
                    root_dir=tmp,
                    character_id="Aemeath",
                    tag="mock",
                    payload=ImagePayload(png),
                )
                ids.append(info["sticker_id"])
            self.assertEqual(
                ids,
                ["Aemeath_mock_01", "Aemeath_mock_02", "Aemeath_mock_03"],
            )
            names = sorted(Path(tmp).iterdir())
            self.assertEqual(len(names), 3)


class SplitTagUrlTests(unittest.TestCase):
    def test_multi_urls(self) -> None:
        # Import parser without loading main.py (astrbot).
        from companion.tools.link_intent import extract_urls

        raw = "tired https://a.example/x.png https://b.example/y.gif"
        urls = extract_urls(raw, limit=32)
        self.assertEqual(len(urls), 2)
        leftover = raw
        for u in urls:
            leftover = leftover.replace(u, " ")
        tag = leftover.strip().split()[0]
        self.assertEqual(tag, "tired")


if __name__ == "__main__":
    unittest.main()

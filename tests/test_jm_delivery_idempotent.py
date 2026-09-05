"""jmcomic 送达幂等。"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_JM = Path(r"d:\1\main_bot\data\plugins\jmcomic")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


delivery = _load("jmcomic_delivery_under_test", _JM / "delivery.py")


class DeliveryIdempotencyTests(unittest.TestCase):
    def setUp(self) -> None:
        delivery._delivered_at.clear()
        delivery._inflight.clear()

    def test_mark_and_recent(self) -> None:
        self.assertFalse(delivery.recently_delivered("group:1", "100"))
        delivery.mark_delivered("group:1", "100")
        self.assertTrue(delivery.recently_delivered("group:1", "100"))
        self.assertFalse(delivery.recently_delivered("group:2", "100"))

    def test_outcome_marker(self) -> None:
        self.assertTrue(delivery.outcome_looks_delivered("漫画 1 已上传到群文件，请查收！"))
        self.assertFalse(delivery.outcome_looks_delivered("上传群文件失败"))


if __name__ == "__main__":
    unittest.main()

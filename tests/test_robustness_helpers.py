"""Robustness helpers: ACK outro, tool shrink, retry jitter."""

from __future__ import annotations

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
_TOOLS = _ROOT / "companion" / "tools"
_PROVIDER = _ROOT / "companion" / "provider"


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
_ensure_pkg("companion.tools", _TOOLS)
_ensure_pkg("companion.provider", _PROVIDER)

# stub ack before loop (loop imports ack + bridge)
ack = _load_as("companion.tools.ack", _TOOLS / "ack.py")

# Minimal bridge stub so loop can import SINGLE_SHOT_TOOLS
_bridge = types.ModuleType("companion.tools.bridge")
_bridge.SINGLE_SHOT_TOOLS = frozenset({"setu_send_image"})
_bridge.ToolBridge = object
sys.modules["companion.tools.bridge"] = _bridge

_router = types.ModuleType("companion.provider.router")
_router.ProviderRouter = object
sys.modules["companion.provider.router"] = _router

loop = _load_as("companion.tools.loop", _TOOLS / "loop.py")
openai_compat = _load_as("companion.provider.openai_compat", _PROVIDER / "openai_compat.py")


class AckOutroTests(unittest.TestCase):
    def test_failed_gives_visible_line(self) -> None:
        trace = [
            {
                "tool_calls": [
                    {
                        "ack": {
                            "ok": False,
                            "delivered": False,
                            "summary": "工具 setu_send_image 执行超时",
                        }
                    }
                ]
            }
        ]
        line = loop.ack_aware_outro(trace)
        self.assertIn("超时", line)

    def test_delivered_stays_silent(self) -> None:
        trace = [
            {
                "tool_calls": [
                    {"ack": {"ok": True, "delivered": True, "summary": "已发送"}}
                ]
            }
        ]
        self.assertEqual(loop.ack_aware_outro(trace), "")


class ShrinkToolsTests(unittest.TestCase):
    def test_drops_media(self) -> None:
        tools = [
            {"function": {"name": "setu_send_image"}},
            {"function": {"name": "schedule_reminder"}},
            {"function": {"name": "jmcomic_download"}},
        ]
        out = loop._shrink_tools_after_failover(tools)
        names = [(t.get("function") or {}).get("name") for t in out]
        self.assertEqual(names, ["schedule_reminder"])


class RetryJitterTests(unittest.TestCase):
    def test_backoff_grows(self) -> None:
        with patch.object(openai_compat.random, "uniform", return_value=0.0):
            a1 = openai_compat._retry_after_sec(RuntimeError("x"), attempt=1, default=1.0)
            a2 = openai_compat._retry_after_sec(RuntimeError("x"), attempt=2, default=1.0)
        self.assertGreaterEqual(a2, a1)
        self.assertGreaterEqual(a1, 0.5)


class BuildAckBadArgsTests(unittest.TestCase):
    def test_build_ack_ok_false(self) -> None:
        raw = ack.build_tool_ack(
            "setu_send_image",
            "参数 JSON 无法解析。请修正后重试；本次未执行。",
            ok=False,
            delivered=False,
        )
        parsed = ack.parse_tool_ack(raw)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertFalse(parsed.get("ok"))
        self.assertFalse(parsed.get("delivered"))


if __name__ == "__main__":
    unittest.main()

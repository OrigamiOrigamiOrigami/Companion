"""TurnGate FIFO + PrivateDebouncer seam tests (no astrbot)."""

from __future__ import annotations

import asyncio
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
turn_gate = _load_as("companion.harness.turn_gate", _HARNESS / "turn_gate.py")
private_debounce = _load_as(
    "companion.harness.private_debounce", _HARNESS / "private_debounce.py"
)
TurnGate = turn_gate.TurnGate
PrivateDebouncer = private_debounce.PrivateDebouncer


class TurnGateFifoTests(unittest.IsolatedAsyncioTestCase):
    async def test_second_waits_then_runs(self) -> None:
        gate = TurnGate()
        order: list[str] = []

        async def first() -> None:
            st = await gate.acquire_fifo("ch", queue_max=3, timeout_sec=5)
            self.assertEqual(st, "ok")
            order.append("a-run")
            await asyncio.sleep(0.05)
            await gate.release("ch")
            order.append("a-done")

        async def second() -> None:
            await asyncio.sleep(0.01)
            flagged = {"q": False}

            async def on_q() -> None:
                flagged["q"] = True

            st = await gate.acquire_fifo(
                "ch", queue_max=3, timeout_sec=5, on_enqueued=on_q
            )
            self.assertEqual(st, "ok")
            self.assertTrue(flagged["q"])
            order.append("b-run")
            await gate.release("ch")

        await asyncio.gather(first(), second())
        self.assertEqual(order, ["a-run", "a-done", "b-run"])

    async def test_overflow_drops_oldest(self) -> None:
        gate = TurnGate()
        self.assertEqual(await gate.acquire_fifo("ch", queue_max=1, timeout_sec=5), "ok")

        async def waiter() -> str:
            return await gate.acquire_fifo("ch", queue_max=1, timeout_sec=5)

        t_old = asyncio.create_task(waiter())
        await asyncio.sleep(0.02)
        t_new = asyncio.create_task(waiter())
        await asyncio.sleep(0.02)
        self.assertEqual(await t_old, "overflow")
        await gate.release("ch")
        self.assertEqual(await t_new, "ok")
        await gate.release("ch")

    async def test_timeout(self) -> None:
        gate = TurnGate()
        await gate.acquire_fifo("ch", queue_max=3, timeout_sec=5)
        st = await gate.acquire_fifo("ch", queue_max=3, timeout_sec=0.05)
        self.assertEqual(st, "timeout")
        await gate.release("ch")


class DebounceTests(unittest.IsolatedAsyncioTestCase):
    async def test_merge_and_supersede(self) -> None:
        d = PrivateDebouncer()
        e1, e2 = object(), object()

        async def first():
            return await d.coalesce(key="u", event=e1, text="一", window_ms=80)

        async def second():
            await asyncio.sleep(0.02)
            return await d.coalesce(key="u", event=e2, text="二", window_ms=80)

        r1, r2 = await asyncio.gather(first(), second())
        self.assertIsNone(r1)
        self.assertIsNotNone(r2)
        assert r2 is not None
        self.assertIs(r2[0], e2)
        self.assertEqual(r2[1], "一\n二")

    def test_adaptive_clamp(self) -> None:
        self.assertEqual(PrivateDebouncer.resolve_window_ms({"debounce_ms": 5000, "adaptive_debounce": True}), 3000)
        self.assertEqual(PrivateDebouncer.resolve_window_ms({"debounce_ms": 500, "adaptive_debounce": True}), 1500)
        self.assertEqual(PrivateDebouncer.resolve_window_ms({"debounce_ms": 2000, "adaptive_debounce": False}), 2000)


if __name__ == "__main__":
    unittest.main()

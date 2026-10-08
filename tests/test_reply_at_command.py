"""回复指令让位：加速/点歌等前缀（含参数）。"""

from __future__ import annotations

from companion.harness.decide import decide
from companion.harness.reply_at_command import (
    looks_like_reply_command,
    strip_addressing,
    should_silence_reply_at_command,
)
from companion.harness.types import InnerState, Perception


_CFG = {
    "decide": {
        "silence_reply_at_commands": True,
        "reply_at_command_keywords": ["加速", "减速", "点歌", "识图"],
        "silence_parser_links": True,
    },
    "group": {"speech_triggers": {"soft_mention": True}, "silence_prior": "mid"},
    "presence": {"night_hard_always_llm": True},
}

_WAKE = ["飞行雪绒", "爱弥斯", "小爱"]


def _p(**kwargs) -> Perception:
    base = dict(
        trigger="hard_mention",
        user_id="1",
        group_id="9",
        channel="group:9",
        text="",
        is_private=False,
        hard_mentioned=True,
        soft_mentioned=False,
        name_addressed=False,
        is_reply=True,
    )
    base.update(kwargs)
    return Perception(**base)


def test_strip_and_accel_with_arg():
    assert strip_addressing("@飞行雪绒 加速 8", _WAKE) == "加速 8"
    assert looks_like_reply_command("加速 8", ["加速", "减速"]) is True
    assert looks_like_reply_command("加速8", ["加速"]) is True
    assert looks_like_reply_command("今天好累", ["加速"]) is False


def test_silence_reply_at_accel():
    assert should_silence_reply_at_command(
        is_reply=True,
        woken=True,
        text="@飞行雪绒 加速 8",
        wake_words=_WAKE,
        config=_CFG,
    )
    d = decide(
        _p(text="@飞行雪绒 加速 8", hard_mentioned=True, is_reply=True),
        InnerState(),
        _CFG,
        wake_words=_WAKE,
    )
    assert d.action == "SILENCE"
    assert d.reason == "reply_at_command"


def test_chat_reply_at_still_full():
    d = decide(
        _p(text="@飞行雪绒 今天好累", hard_mentioned=True, is_reply=True),
        InnerState(),
        _CFG,
        wake_words=_WAKE,
    )
    assert d.action == "FULL"
    assert d.reason == "hard_mention"


def test_no_reply_no_silence():
    assert not should_silence_reply_at_command(
        is_reply=False,
        woken=True,
        text="@飞行雪绒 加速",
        wake_words=_WAKE,
        config=_CFG,
    )


if __name__ == "__main__":
    test_strip_and_accel_with_arg()
    test_silence_reply_at_accel()
    test_chat_reply_at_still_full()
    test_no_reply_no_silence()
    print("ok")

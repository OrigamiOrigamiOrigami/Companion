from companion.tools.continuation_intent import (
    continuation_tool_hint,
    is_another_one_intent,
    media_family_from_tools,
)


def test_another_one_detects_common_phrases():
    assert is_another_one_intent("再来一个")
    assert is_another_one_intent("@飞行雪绒(3954002695) 再来一个")
    assert is_another_one_intent("换一本")
    assert not is_another_one_intent("还没好吗")
    assert not is_another_one_intent("你好")


def test_media_family_from_tools():
    assert media_family_from_tools(["jmcomic_search", "jmcomic_download"]) == "jmcomic"
    assert media_family_from_tools(["setu_send_image"]) == "setu"
    assert media_family_from_tools(["web_search"]) is None


def test_continuation_tool_hint_requires_family():
    assert "jmcomic_search" in continuation_tool_hint("jmcomic")
    assert "setu_send_image" in continuation_tool_hint("setu")
    assert continuation_tool_hint(None) == ""

from companion.harness.outbound_sanitize import (
    finalize_outbound_bubbles,
    sanitize_outbound_text,
)


def test_strip_called_bracket_preface():
    assert sanitize_outbound_text("[Called: jmcomic_download]") == ""
    assert sanitize_outbound_text("[Calling: setu_send_image]") == ""
    assert sanitize_outbound_text("Called: jmcomic_search") == ""


def test_keep_speech_around_called_marker():
    assert sanitize_outbound_text("好，正在下 [Called: jmcomic_download]") == "好，正在下"
    assert sanitize_outbound_text("等一下嘛~\n[Called: jmcomic_download]") == "等一下嘛~"


def test_finalize_drops_called_only_bubble():
    out = finalize_outbound_bubbles(
        ["[Called: jmcomic_download]"],
        fallback="咦，刚才好像卡住了。",
        skip=["好，正在下"],
    )
    assert out == []

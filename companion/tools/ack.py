from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

# 执行后可能把媒体/结果直接发到聊天里的工具（delivered 须单独推断，不能默认 true）
DELIVERED_TOOLS = frozenset(
    {
        "setu_send_image",
        "jmcomic_download",
        "image_search_saucenao",
        "image_search_ascii2d",
        "image_search_google",
        "play_song_by_name",
    }
)

_FAIL_MARKERS = (
    "执行超时",
    "执行失败",
    "不可用或未注册",
    "bound method",
    "还在跑",
    "没装",
    "未注册",
    "找不到符合",
    "获取图片失败",
    "获取涩图失败",
    "图片下载失败",
    "图片发送失败",
    "发送失败",
    "下载失败",
    "连接失败",
    "访问被拒绝",
    "超过上限",
    "拒绝下载",
    "不支持搜索",
    "不能为空",
    "无法识别",
    "无法从输入",
    "处理命令出错",
    "发生了未知错误",
    "R-18G",
    "R18G",
    "网络好像不太顺畅",
    "可能被风控",
)

# 仅「下载任务已启动」不代表预览/文件已到聊天
_JM_DELIVERED_MARKERS = (
    "预览已发",
    "已发送",
    "请查收",
    "已有缓存，正在上传",
    "搜索结果发给你",
    "搜索结果",
    "已查询漫画",
)

_SETU_DELIVERED_MARKERS = (
    "图发过去",
    "图找到了",
    "发你啦",
    "发过去",
)

_IMAGE_SEARCH_DELIVERED_MARKERS = (
    "发你",
    "发过去",
    "检索结果",
    "结果发",
)


@dataclass
class ToolExecResult:
    """适配器工具执行原始结果。"""

    text: str
    plugin_sent: bool = False  # 空 CommandResult chain，插件已 event.send
    plugin_raw: str = ""  # 插件原始回执（ACK 包装前）
    effective: dict[str, Any] = field(default_factory=dict)  # 实际用于搜索/下载的参数

    @classmethod
    def coerce(cls, raw: Any) -> ToolExecResult:
        if isinstance(raw, ToolExecResult):
            return raw
        body = str(raw or "").strip()
        return cls(text=body, plugin_raw=body)


def build_tool_ack(
    tool: str,
    raw: str | ToolExecResult,
    *,
    ok: bool | None = None,
    delivered: bool | None = None,
    plugin_sent: bool | None = None,
) -> str:
    """结构化工具 ACK，供 LLM 可靠判断成功与否。"""
    exec_result = ToolExecResult.coerce(raw)
    text = exec_result.text
    if plugin_sent is None:
        plugin_sent = exec_result.plugin_sent

    if ok is None:
        ok = not tool_failed(text)
    if delivered is None:
        delivered = _infer_delivered(tool, text, ok=ok, plugin_sent=plugin_sent)

    summary = _summarize(tool, text, ok=ok, delivered=delivered)
    detail = text[:800] if (not ok or not delivered) else ""
    payload = {
        "ok": ok,
        "tool": tool,
        "summary": summary,
        "delivered": delivered,
        "detail": detail,
    }
    return json.dumps(payload, ensure_ascii=False)


def parse_tool_ack(text: str) -> dict[str, Any] | None:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if isinstance(data, dict) and "ok" in data:
        return data
    return None


def tool_failed(text: str) -> bool:
    parsed = parse_tool_ack(text)
    if parsed is not None:
        return not bool(parsed.get("ok"))
    body = (text or "").strip()
    if not body:
        return True
    return _has_fail_marker(body)


def _has_fail_marker(text: str) -> bool:
    body = (text or "").strip()
    if not body:
        return False
    if "不存在" in body and "漫画" in body:
        return True
    return any(m in body for m in _FAIL_MARKERS)


def _infer_delivered(tool: str, raw: str, *, ok: bool, plugin_sent: bool) -> bool:
    if not ok:
        return False
    text = (raw or "").strip()

    if tool == "setu_send_image":
        if plugin_sent:
            return True
        return _has_any_marker(text, _SETU_DELIVERED_MARKERS)

    if tool == "jmcomic_download":
        return _has_any_marker(text, _JM_DELIVERED_MARKERS)

    if tool.startswith("jmcomic_"):
        return _has_any_marker(text, _JM_DELIVERED_MARKERS)

    if tool.startswith("image_search_"):
        if plugin_sent:
            return True
        return _has_any_marker(text, _IMAGE_SEARCH_DELIVERED_MARKERS)

    if tool == "play_song_by_name":
        return plugin_sent or bool(text and not _has_fail_marker(text))

    if tool in DELIVERED_TOOLS:
        return plugin_sent

    return False


def _has_any_marker(text: str, markers: tuple[str, ...]) -> bool:
    return any(m in (text or "") for m in markers)


def _summarize(tool: str, raw: str, *, ok: bool, delivered: bool) -> str:
    if not ok:
        return raw[:200] if raw else f"{tool} 未成功"
    if delivered:
        if tool.startswith("setu_"):
            return "图已发到聊天"
        if tool == "jmcomic_download":
            if "已有缓存，正在上传" in raw:
                return "本地已有缓存，PDF 正在上传"
            if "已查询漫画" in raw:
                return "预览/详情已发到聊天，PDF 后台下载中"
            return "预览或文件已发到聊天"
        if tool.startswith("image_search_"):
            return "识图结果已发到聊天"
        if tool == "play_song_by_name":
            return "歌曲已开始播放"
    # ok 但未确认送达
    if tool == "setu_send_image":
        return "已尝试发图，但未确认图出现在聊天；勿断言已发出"
    if tool == "jmcomic_download":
        if "下载任务已启动" in raw or "后台" in raw:
            return "下载任务已开始，预览/文件未必已到聊天；勿断言已发出"
        return "命令已执行，预览/文件未必已到聊天；勿断言已发出"
    if tool.startswith("jmcomic_"):
        return "搜索/下载命令已执行，结果未必已到聊天"
    if raw:
        return raw[:200]
    return f"{tool} 已完成"

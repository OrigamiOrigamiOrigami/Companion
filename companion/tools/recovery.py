"""Tool Loop 恢复：未闭合判定与 nudge（工具无关）。"""

from __future__ import annotations

from typing import Any

from .ack import parse_tool_ack


def tool_result_content_or_placeholder(content: str, tool_name: str) -> str:
    """层 1：禁止空白 tool_result 回灌模型。"""
    body = (content or "").strip()
    if body:
        ack = parse_tool_ack(body)
        if ack is not None:
            summary = str(ack.get("summary") or "").strip()
            if not summary:
                ack = dict(ack)
                ack["summary"] = f"（{tool_name}：无输出，已执行）"
                import json

                return json.dumps(ack, ensure_ascii=False)
            return body
        return body
    from .ack import build_tool_ack

    return build_tool_ack(
        tool_name,
        "（无输出，已执行）",
        ok=True,
        delivered=False,
        done=True,
        needs_followup=False,
    )


def enrich_ack_followup(tool: str, ack: dict[str, Any] | None) -> dict[str, Any] | None:
    """把已知多步模式映射进通用字段（不新增特例分支到 loop 决策）。"""
    if not ack:
        return ack
    out = dict(ack)
    if out.get("needs_followup") is True:
        out.setdefault("done", False)
        return out
    if out.get("done") is False:
        out.setdefault("needs_followup", True)
        return out

    summary = str(out.get("summary") or "")
    # jm 搜到列表 → 还需 download
    if tool == "jmcomic_search" and bool(out.get("ok")) and (
        "请选 ID" in summary or "有结果" in summary
    ):
        out["needs_followup"] = True
        out["done"] = False
        out.setdefault(
            "next_hint",
            "从搜索结果选一个 ID 调用 jmcomic_download，不要只口语收尾。",
        )
        return out
    return out


def ack_is_open(ack: dict[str, Any] | None) -> bool:
    if not ack:
        return False
    if ack.get("needs_followup") is True:
        return True
    if ack.get("done") is False:
        return True
    return False


def trace_has_open_followup(trace: list[dict[str, Any]]) -> bool:
    """本回合工具轨迹里是否仍有未闭合 ACK。"""
    for entry in reversed(trace or []):
        for tc in entry.get("tool_calls") or []:
            ack = tc.get("ack")
            if not isinstance(ack, dict):
                ack = parse_tool_ack(str(tc.get("result") or ""))
            ack = enrich_ack_followup(str(tc.get("name") or ""), ack)
            if ack_is_open(ack):
                return True
    return False


def build_recovery_nudge(*, open_followup: bool, used_tools: list[str]) -> str:
    """层 2：无 tool_calls 但任务未闭合时的系统 nudge。"""
    hint = ""
    if open_followup:
        hint = (
            "上一工具 ACK 仍标记 needs_followup/未完成：请继续调工具收尾，"
            "不要只口语或表情结束。"
        )
    else:
        hint = "本回合工具链尚未完成：请继续调用所需工具，不要假装已做完。"
    if used_tools:
        hint += f" 已用过：{', '.join(used_tools[-6:])}。"
    hint += " 若 ACK.next_hint 有说明，优先按它执行。"
    return hint

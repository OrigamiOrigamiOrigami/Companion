from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from ..harness.types import Decision, ExpressResult, InnerState, Perception

logger = logging.getLogger("astrbot")

_PROMPT_KEEP = 10


class TurnLogger:
    """每次 companion 有效回复落盘：原始问题 + LLM 原始完整返回。

    另存最近 N 轮「完整提示词 + 完整响应」到 ``data/log/prompts/``（格式化 JSON）。
    """

    def __init__(self, data_dir: str):
        self.log_dir = os.path.join(data_dir, "log")
        self.prompt_dir = os.path.join(self.log_dir, "prompts")
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.prompt_dir, exist_ok=True)

    def log_turn(
        self,
        *,
        trigger: str,
        perception: Perception,
        decision: Decision,
        state: InnerState,
        result: ExpressResult,
        character_id: str,
    ) -> None:
        record = self._build_record(
            trigger=trigger,
            perception=perception,
            decision=decision,
            state=state,
            result=result,
            character_id=character_id,
        )
        try:
            self._append(record)
            self._write_prompt_snapshot(record)
            logger.info(
                "companion 回合已记录 频道=%s 用户=%s 降级=%s 工具=%s",
                perception.channel,
                perception.user_id,
                result.degraded,
                ",".join(result.tools_used) or "无",
            )
            if result.tool_invocations:
                for inv in result.tool_invocations:
                    logger.info(
                        "companion 工具审计 名称=%s 请求=%s 实际=%s ack=%s",
                        inv.get("tool"),
                        inv.get("llm_request"),
                        inv.get("effective") or inv.get("llm_request"),
                        inv.get("ack"),
                    )
        except Exception as e:
            logger.warning("companion 回合日志写入失败: %s", e)

    def _build_record(
        self,
        *,
        trigger: str,
        perception: Perception,
        decision: Decision,
        state: InnerState,
        result: ExpressResult,
        character_id: str,
    ) -> dict[str, Any]:
        question_parts: list[str] = []
        if (perception.text or "").strip():
            question_parts.append(perception.text.strip())
        if (perception.media_note or "").strip():
            question_parts.append(f"（{perception.media_note.strip()}）")
        question = "\n".join(question_parts) or "（无文字）"

        return {
            "ts": time.time(),
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "character_id": character_id,
            "trigger": trigger,
            "channel": perception.channel,
            "user_id": perception.user_id,
            "group_id": perception.group_id,
            "decision": decision.action,
            "decision_reason": decision.reason,
            "allow_tools": decision.allow_tools,
            "form": state.active_form,
            "familiarity": state.familiarity,
            "input": {
                "text": perception.text,
                "media_note": perception.media_note,
                "has_image": perception.has_image,
                "has_visual": perception.has_visual,
                "question": question,
            },
            "prompt_messages": _sanitize_obj(result.prompt_messages or []),
            "raw_response": result.raw_response,
            "parsed_bubbles": result.bubbles,
            "preface_bubbles": result.preface_bubbles,
            "tool_order": result.tool_order,
            "tools_used": result.tools_used,
            "tool_invocations": _sanitize_obj(result.tool_invocations or []),
            "degraded": result.degraded,
            "error": result.error,
            "llm_trace": _sanitize_trace(result.llm_trace),
            "sticker_wanted": result.sticker_wanted,
            "poke_wanted": result.poke_wanted,
            "sticker_intent": result.sticker_intent,
            "sticker_match_stage": result.sticker_match_stage,
            "sticker_score": result.sticker_score,
            "sticker_id": result.sticker_id,
        }

    def _append(self, record: dict[str, Any]) -> None:
        day = time.strftime("%Y-%m-%d", time.localtime(record["ts"]))
        path = os.path.join(self.log_dir, f"{day}.jsonl")
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _write_prompt_snapshot(self, record: dict[str, Any]) -> None:
        """格式化写入单轮 JSON，只保留最近 _PROMPT_KEEP 个文件。"""
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(record["ts"]))
        ms = int((record["ts"] % 1) * 1000)
        name = f"{stamp}_{ms:03d}.json"
        path = os.path.join(self.prompt_dir, name)
        snapshot = {
            "time": record.get("time"),
            "character_id": record.get("character_id"),
            "channel": record.get("channel"),
            "user_id": record.get("user_id"),
            "trigger": record.get("trigger"),
            "decision": record.get("decision"),
            "decision_reason": record.get("decision_reason"),
            "input": record.get("input"),
            "prompt_messages": record.get("prompt_messages") or [],
            "raw_response": record.get("raw_response") or "",
            "llm_trace": record.get("llm_trace") or [],
            "parsed_bubbles": record.get("parsed_bubbles") or [],
            "tools_used": record.get("tools_used") or [],
            "tool_invocations": record.get("tool_invocations") or [],
            "sticker_wanted": record.get("sticker_wanted"),
            "sticker_intent": record.get("sticker_intent"),
            "sticker_match_stage": record.get("sticker_match_stage"),
            "sticker_id": record.get("sticker_id"),
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
            f.write("\n")
        self._trim_prompt_dir()

    def _trim_prompt_dir(self) -> None:
        try:
            files = [
                os.path.join(self.prompt_dir, n)
                for n in os.listdir(self.prompt_dir)
                if n.endswith(".json")
            ]
        except OSError:
            return
        files.sort(key=lambda p: os.path.getmtime(p), reverse=True)
        for old in files[_PROMPT_KEEP:]:
            try:
                os.remove(old)
            except OSError:
                pass


def _sanitize_trace(trace: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not trace:
        return []
    out: list[dict[str, Any]] = []
    for item in trace:
        out.append(_sanitize_obj(item))
    return out


def _sanitize_obj(obj: Any) -> Any:
    if isinstance(obj, dict):
        cleaned: dict[str, Any] = {}
        for k, v in obj.items():
            if k in ("image_url", "url") and isinstance(v, str) and v.startswith("data:"):
                cleaned[k] = "[base64 omitted]"
                continue
            cleaned[k] = _sanitize_obj(v)
        return cleaned
    if isinstance(obj, list):
        return [_sanitize_obj(x) for x in obj]
    if isinstance(obj, str) and obj.startswith("data:image"):
        return "[base64 omitted]"
    return obj

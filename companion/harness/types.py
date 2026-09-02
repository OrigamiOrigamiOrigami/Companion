from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Perception:
    trigger: str
    user_id: str
    group_id: Optional[str]
    channel: str
    text: str
    is_private: bool
    hard_mentioned: bool
    soft_mentioned: bool
    name_addressed: bool = False
    sender_name: str = ""
    rest_keyword: bool = False
    image_count: int = 0
    face_count: int = 0
    reply_image_count: int = 0
    record_count: int = 0
    media_note: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def has_visual(self) -> bool:
        return (self.image_count + self.face_count + self.reply_image_count) > 0

    @property
    def has_image(self) -> bool:
        return (self.image_count + self.reply_image_count) > 0


@dataclass
class InnerState:
    mood: str = "neutral"
    energy: str = "mid"
    loneliness: str = "mid"
    familiarity: str = "stranger"
    active_form: str = "default"
    form_dwell: int = 0
    pink_score: int = 0
    black_score: int = 0
    last_user_care_at: float = 0.0
    open_loops: list[str] = field(default_factory=list)


@dataclass
class Decision:
    action: str  # SILENCE | SHORT | FULL
    reason: str
    allow_tools: bool = False


@dataclass
class ToolPlan:
    """本回合工具与文本的发送节奏。"""
    order: str  # chat | text_first | tool_first
    reason: str = ""
    hint: str = ""


@dataclass
class ExpressResult:
    bubbles: list[str]
    sticker_wanted: bool = False
    sticker_intent: str = "none"
    sticker_path: Optional[str] = None
    sticker_id: Optional[str] = None
    sticker_match_stage: str = ""
    sticker_score: float = 0.0
    degraded: bool = False
    tools_used: list[str] = field(default_factory=list)
    tool_invocations: list[dict[str, Any]] = field(default_factory=list)
    raw_response: str = ""
    llm_trace: list[dict[str, Any]] = field(default_factory=list)
    # 本回合送给模型的完整 messages（审计用）
    prompt_messages: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""
    preface_bubbles: list[str] = field(default_factory=list)
    tool_order: str = ""
    poke_wanted: bool = False
    voice_emotion: str = ""

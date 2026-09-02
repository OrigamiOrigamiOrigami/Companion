from __future__ import annotations

from typing import Any


def get_llm_tool_manager(context: Any) -> Any | None:
    if context is None:
        return None
    if hasattr(context, "get_llm_tool_manager"):
        try:
            return context.get_llm_tool_manager()
        except Exception:
            return None
    pm = getattr(context, "provider_manager", None)
    if pm is not None and hasattr(pm, "llm_tools"):
        return pm.llm_tools
    return None

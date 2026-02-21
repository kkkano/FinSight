# -*- coding: utf-8 -*-
"""
Conditional interrupt node for human-in-the-loop confirmation.

Uses LangGraph ``interrupt()`` when current run requires user confirmation.
"""

from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from backend.graph.confirmation_policy import normalize_confirmation_mode, should_require_confirmation
from backend.graph.state import GraphState

logger = logging.getLogger(__name__)


def confirmation_gate(state: GraphState) -> dict[str, Any]:
    """Conditionally interrupt the graph to ask for user confirmation."""
    require = state.get("require_confirmation")
    output_mode = state.get("output_mode", "chat")
    confirmation_mode = normalize_confirmation_mode(state.get("confirmation_mode"), default="auto")

    should_confirm = should_require_confirmation(
        require_confirmation=require,
        confirmation_mode=confirmation_mode,
        output_mode=output_mode,
    )
    if not should_confirm:
        return {}

    plan_ir = state.get("plan_ir") or {}
    options = state.get("confirmation_options") or ["确认执行", "调整参数", "取消"]

    logger.info(
        "[confirmation_gate] interrupt for confirmation output_mode=%s confirmation_mode=%s",
        output_mode,
        confirmation_mode,
    )

    user_response = interrupt(
        {
            "prompt": "执行计划确认",
            "options": options,
            "plan_summary": plan_ir.get("rationale", ""),
            "required_agents": plan_ir.get("required_agents", []),
        }
    )

    logger.info("[confirmation_gate] resumed with user response: %s", user_response)
    return {
        "user_confirmation": user_response,
        "require_confirmation": False,
        "confirmation_mode": confirmation_mode,
    }


__all__ = ["confirmation_gate"]

# -*- coding: utf-8 -*-
"""
Conditional interrupt node for human-in-the-loop confirmation.

Uses the official LangGraph ``interrupt()`` function. Only pauses execution
when the current run requires user confirmation (e.g. full report mode).
Brief / chat mode passes through without interruption.

Resume: the caller sends ``Command(resume=<value>)`` via ``GraphRunner.resume()``.
"""
from __future__ import annotations

import logging
from typing import Any

from langgraph.types import interrupt

from backend.graph.state import GraphState

logger = logging.getLogger(__name__)


def confirmation_gate(state: GraphState) -> dict[str, Any]:
    """Conditionally interrupt the graph to ask for user confirmation.

    Trigger rules (any one suffices):
    - ``state["require_confirmation"]`` is explicitly ``True``
    - ``state["output_mode"] == "investment_report"`` (full report, default confirm)

    Skip rules (override the above):
    - ``state["require_confirmation"]`` is explicitly ``False``
    - ``state["output_mode"]`` is ``"chat"`` or ``"brief"``

    When interrupted, the return value of ``interrupt()`` is the user's
    response, stored in ``state["user_confirmation"]``.
    """
    require = state.get("require_confirmation")
    output_mode = state.get("output_mode", "chat")

    # Explicit skip
    if require is False:
        return {}

    # Determine if confirmation is needed
    should_confirm = (
        require is True
        or output_mode == "investment_report"
    )

    if not should_confirm:
        return {}

    plan_ir = state.get("plan_ir") or {}
    options = state.get("confirmation_options") or ["确认执行", "调整参数", "取消"]

    logger.info(
        "[confirmation_gate] Interrupting for confirmation (output_mode=%s)",
        output_mode,
    )

    user_response = interrupt({
        "prompt": "执行计划确认",
        "options": options,
        "plan_summary": plan_ir.get("rationale", ""),
        "required_agents": plan_ir.get("required_agents", []),
    })

    logger.info("[confirmation_gate] Resumed with user response: %s", user_response)

    return {
        "user_confirmation": user_response,
        "require_confirmation": False,
    }


__all__ = ["confirmation_gate"]

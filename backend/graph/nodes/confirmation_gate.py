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


def _resolve_gate_reason(
    *,
    require_confirmation: Any,
    confirmation_mode: str,
    output_mode: Any,
) -> tuple[str, str]:
    output_mode_text = str(output_mode or "").strip().lower()
    if require_confirmation is True:
        return (
            "explicit_required",
            "当前请求显式要求执行前确认。",
        )
    if confirmation_mode == "required":
        return (
            "mode_required",
            "当前确认策略为 required，执行前必须确认。",
        )
    if output_mode_text == "investment_report":
        return (
            "investment_report_auto_required",
            "当前为投资报告模式，系统会在执行前要求确认计划。",
        )
    return (
        "policy_required",
        "当前策略要求执行前确认。",
    )


def _build_option_metadata(options: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    option_effects: dict[str, str] = {}
    option_intents: dict[str, str] = {}
    if not options:
        return option_effects, option_intents

    # Positional defaults for canonical 3-option flow.
    option_intents[options[0]] = "confirm_execute"
    option_effects[options[0]] = "按当前计划立即继续执行，并开始生成结果。"

    if len(options) >= 2:
        option_intents[options[1]] = "adjust_parameters"
        option_effects[options[1]] = "你可以补充修改指令，系统会按新要求继续执行。"

    if len(options) >= 3:
        option_intents[options[2]] = "cancel_execution"
        option_effects[options[2]] = "终止本次执行，不会继续生成结果。"

    for option in options[3:]:
        option_intents[option] = "custom"
        option_effects[option] = "按该选项继续流程。"
    return option_effects, option_intents


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
    gate_reason_code, gate_reason = _resolve_gate_reason(
        require_confirmation=require,
        confirmation_mode=confirmation_mode,
        output_mode=output_mode,
    )
    option_effects, option_intents = _build_option_metadata(options)

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
            "gate_reason_code": gate_reason_code,
            "gate_reason": gate_reason,
            "option_effects": option_effects,
            "option_intents": option_intents,
            "output_mode": output_mode,
            "confirmation_mode": confirmation_mode,
        }
    )

    logger.info("[confirmation_gate] resumed with user response: %s", user_response)
    return {
        "user_confirmation": user_response,
        "require_confirmation": False,
        "confirmation_mode": confirmation_mode,
    }


__all__ = ["confirmation_gate"]

# -*- coding: utf-8 -*-
"""Planner 结果摘要与 Agent 选择诊断。"""
from __future__ import annotations

from typing import Any

from backend.graph.capability_registry import REPORT_AGENT_CANDIDATES
from backend.graph.planning.policy_enforcement import (
    _HIGH_COST_AGENTS,
    _estimate_step_cost_latency,
    _is_deep_hint,
)
from backend.graph.state import GraphState


def _dedupe_agent_names(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in items:
        name = str(raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


def _extract_selected_agents(plan_dict: dict[str, Any]) -> list[str]:
    steps = plan_dict.get("steps")
    if not isinstance(steps, list):
        return []
    names: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if str(step.get("kind") or "") != "agent":
            continue
        name = str(step.get("name") or "").strip()
        if name:
            names.append(name)
    return _dedupe_agent_names(names)


def _candidate_agents_for_plan(state: GraphState) -> list[str]:
    policy = state.get("policy") if isinstance(state.get("policy"), dict) else {}
    allowed = policy.get("allowed_agents") if isinstance(policy, dict) else None
    if isinstance(allowed, list):
        candidates = [str(item or "").strip() for item in allowed]
        deduped = _dedupe_agent_names(candidates)
        if deduped:
            return deduped
    return list(REPORT_AGENT_CANDIDATES)


def _build_plan_steps_summary(plan_dict: dict[str, Any]) -> list[dict[str, Any]]:
    raw_steps = plan_dict.get("steps")
    if not isinstance(raw_steps, list):
        return []
    summary: list[dict[str, Any]] = []
    for step in raw_steps[:24]:
        if not isinstance(step, dict):
            continue
        summary.append(
            {
                "id": str(step.get("id") or "").strip() or "unknown",
                "kind": str(step.get("kind") or "").strip() or "unknown",
                "name": str(step.get("name") or "").strip() or "unknown",
                "task_ids": [
                    str(value or "").strip()
                    for value in (step.get("task_ids") if isinstance(step.get("task_ids"), list) else [])
                    if str(value or "").strip()
                ],
                "parallel_group": (
                    str(step.get("parallel_group") or "").strip()
                    if step.get("parallel_group") is not None
                    else None
                ),
                "optional": bool(step.get("optional")),
            }
        )
    return summary


def _build_planner_reasoning_brief(
    *,
    state: GraphState,
    selected_agents: list[str],
    skipped_agents: list[str],
    plan_steps_count: int,
    fallback: bool,
    fallback_reason: str | None = None,
) -> str:
    output_mode = str(state.get("output_mode") or "brief").strip() or "brief"
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    source = str((ui_context or {}).get("source") or "").strip() or "unknown"
    selected_preview = ", ".join(selected_agents[:5]) if selected_agents else "none"
    skipped_preview = ", ".join(skipped_agents[:5]) if skipped_agents else "none"
    if fallback:
        reason = str(fallback_reason or "planner_fallback").strip()
        return (
            f"Planner fallback mode ({reason}); output_mode={output_mode}; source={source}; "
            f"selected={selected_preview}; skipped={skipped_preview}; steps={plan_steps_count}."
        )
    return (
        f"Planner completed; output_mode={output_mode}; source={source}; "
        f"selected={selected_preview}; skipped={skipped_preview}; steps={plan_steps_count}."
    )


def _skip_reason_for_agent(
    agent_name: str,
    *,
    state: GraphState,
    selected_agents: list[str],
) -> str:
    if agent_name in selected_agents:
        return "selected"
    query = str(state.get("query") or "")
    output_mode = str(state.get("output_mode") or "brief").strip().lower()
    if agent_name == "deep_search_agent" and not _is_deep_hint(query, state):
        return "deepsearch_not_requested"
    if output_mode != "investment_report":
        return "not_needed_for_output_mode"
    if agent_name in _HIGH_COST_AGENTS:
        return "budget_or_depth_limited"
    return "not_selected_by_planner"


def _build_agent_selection_diagnostics(
    *,
    state: GraphState,
    selected_agents: list[str],
    skipped_agents: list[str],
) -> dict[str, Any]:
    query = str(state.get("query") or "")
    has_deep_hint = _is_deep_hint(query, state)
    selected_set = set(selected_agents)
    budget_priority: list[dict[str, Any]] = []
    for index, agent in enumerate(selected_agents, start=1):
        effort, latency_ms = _estimate_step_cost_latency({"kind": "agent", "name": agent})
        budget_priority.append(
            {
                "agent": agent,
                "rank": index,
                "estimated_effort": effort,
                "estimated_latency_ms": latency_ms,
            }
        )

    return {
        "selected_agents": selected_agents,
        "skipped_agents": [
            {
                "agent": agent,
                "reason": _skip_reason_for_agent(
                    agent,
                    state=state,
                    selected_agents=selected_agents,
                ),
            }
            for agent in skipped_agents
            if agent not in selected_set
        ],
        "deepsearch_reason": "requested" if has_deep_hint else "not_requested",
        "budget_priority": budget_priority,
    }


__all__ = [
    "_build_agent_selection_diagnostics",
    "_build_plan_steps_summary",
    "_build_planner_reasoning_brief",
    "_candidate_agents_for_plan",
    "_dedupe_agent_names",
    "_extract_selected_agents",
    "_skip_reason_for_agent",
]

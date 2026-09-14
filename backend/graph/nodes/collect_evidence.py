# -*- coding: utf-8 -*-
"""执行前约束、确定性计划与证据采集边界。"""
from __future__ import annotations

from typing import Any

from backend.graph.execution.plan_pipeline import execute_plan_node
from backend.graph.nodes.policy_gate import policy_gate
from backend.graph.planning.rule_planner import rule_based_planner
from backend.graph.state import GraphState


async def collect_evidence(state: GraphState) -> dict[str, Any]:
    """仅对 research lane 执行外部 I/O；direct/clarify 必须为零 I/O。"""
    understanding = state.get("understanding") if isinstance(state.get("understanding"), dict) else {}
    route = str(understanding.get("route") or "clarify").strip().lower()
    trace = dict(state.get("trace") or {})
    if route != "research":
        trace["collect_evidence"] = {"status": "skipped", "reason": f"route:{route}"}
        return {"artifacts": dict(state.get("artifacts") or {}), "trace": trace}

    policy_result = policy_gate(state)
    working: dict[str, Any] = {**state, **policy_result}
    plan_result = rule_based_planner(working)  # type: ignore[arg-type]
    working.update(plan_result)

    planner_trace = dict(working.get("trace") or {})
    planner_trace["planner_runtime"] = {
        "mode": "deterministic_rules",
        "fallback": False,
        "llm_calls": 0,
    }
    working["trace"] = planner_trace

    execution_result = await execute_plan_node(working)  # type: ignore[arg-type]
    final_trace = dict(execution_result.get("trace") or planner_trace)
    final_trace["collect_evidence"] = {
        "status": "done",
        "plan_steps": len((working.get("plan_ir") or {}).get("steps") or []),
        "evidence_count": len((execution_result.get("artifacts") or {}).get("evidence_pool") or []),
    }
    return {
        "policy": working.get("policy"),
        "plan_ir": working.get("plan_ir"),
        "artifacts": execution_result.get("artifacts") or {},
        "trace": final_trace,
    }


__all__ = ["collect_evidence"]

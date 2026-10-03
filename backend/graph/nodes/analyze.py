# -*- coding: utf-8 -*-
"""证据分析边界：事实查询确定性渲染，研究请求最多一次分析模型。"""
from __future__ import annotations

from typing import Any

from backend.graph.event_bus import emit_event
from backend.graph.nodes.synthesize import synthesize
from backend.graph.state import GraphState
from backend.services.llm_usage import LLMAttribution, get_token_accumulator, reset_llm_attribution, set_llm_attribution


_RESEARCH_ANALYST_OPERATIONS = frozenset({
    "analysis",
    "earnings_impact",
    "investment_opinion",
    "news_impact",
    "qa",
})


def _needs_research_analyst(state: GraphState) -> bool:
    if str(state.get("output_mode") or "").strip().lower() == "investment_report":
        return True
    operation = state.get("operation") if isinstance(state.get("operation"), dict) else {}
    if str(operation.get("name") or "") in {"compare", "macro_brief"}:
        tasks = state.get("tasks") if isinstance(state.get("tasks"), list) else []
        for task in tasks:
            required = task.get("required_evidence") or [] if isinstance(task, dict) else []
            if set(required) & {"fundamental_snapshot", "risk_profile", "news_context", "filing_context"}:
                return True
    return str(operation.get("name") or "").strip().lower() in _RESEARCH_ANALYST_OPERATIONS


async def analyze(state: GraphState) -> dict[str, Any]:
    understanding = state.get("understanding") if isinstance(state.get("understanding"), dict) else {}
    route = str(understanding.get("route") or "clarify").strip().lower()
    trace = dict(state.get("trace") or {})
    if route != "research":
        trace["analysis"] = {"status": "skipped", "llm_calls": 0, "reason": f"route:{route}"}
        return {"artifacts": dict(state.get("artifacts") or {}), "trace": trace}

    analyst = _needs_research_analyst(state)
    trace["analysis"] = {"mode": "research" if analyst else "deterministic"}
    state = {**state, "trace": trace}
    accumulator = get_token_accumulator()
    before = accumulator.summary() if accumulator is not None else None
    if analyst:
        await emit_event({"type": "research_analyst_start", "role": "research_analyst", "status": "start"})
    attribution_token = set_llm_attribution(
        LLMAttribution(agent="research_analyst", layer="analysis")
    )
    try:
        result = await synthesize(state)
    finally:
        reset_llm_attribution(attribution_token)

    result_trace = dict(result.get("trace") or trace)
    result_trace["analysis"] = {
        "status": "done",
        "role": "research_analyst" if analyst else "deterministic_renderer",
        "verifier_allowed": str(state.get("output_mode") or "") == "investment_report",
    }
    if not analyst:
        result_trace["analysis"]["llm_calls"] = 0
    if before is not None:
        after = accumulator.summary()
        def attempts(summary):
            attribution = summary.get("usage_by_attribution")
            if isinstance(attribution, list) and attribution:
                return sum(int(item.get("calls") or 0) for item in attribution if isinstance(item, dict))
            return int(summary.get("llm_token_calls") or 0)
        result_trace["analysis"]["business_llm_calls"] = max(0, attempts(after) - attempts(before))
        result_trace["analysis"]["failed_llm_calls"] = max(0, int(after.get("failed_llm_calls") or 0) - int(before.get("failed_llm_calls") or 0))
    if analyst:
        await emit_event({"type": "research_analyst_done", "role": "research_analyst", "status": "done"})
    return {**result, "trace": result_trace}


__all__ = ["analyze"]

# -*- coding: utf-8 -*-
"""证据分析边界：事实查询确定性渲染，研究请求最多一次分析模型。"""
from __future__ import annotations

from typing import Any

from backend.graph.event_bus import emit_event
from backend.graph.nodes.synthesize import _stub_render_vars, synthesize
from backend.graph.state import GraphState
from backend.services.llm_usage import LLMAttribution, reset_llm_attribution, set_llm_attribution


_RESEARCH_ANALYST_OPERATIONS = frozenset({
    "analysis",
    "earnings_impact",
    "investment_opinion",
    "news_impact",
    "portfolio_impact",
    "qa",
})


def _needs_research_analyst(state: GraphState) -> bool:
    if str(state.get("output_mode") or "").strip().lower() == "investment_report":
        return True
    operation = state.get("operation") if isinstance(state.get("operation"), dict) else {}
    return str(operation.get("name") or "").strip().lower() in _RESEARCH_ANALYST_OPERATIONS


async def analyze(state: GraphState) -> dict[str, Any]:
    understanding = state.get("understanding") if isinstance(state.get("understanding"), dict) else {}
    route = str(understanding.get("route") or "clarify").strip().lower()
    trace = dict(state.get("trace") or {})
    if route != "research":
        trace["analysis"] = {"status": "skipped", "llm_calls": 0, "reason": f"route:{route}"}
        return {"artifacts": dict(state.get("artifacts") or {}), "trace": trace}

    if not _needs_research_analyst(state):
        artifacts = dict(state.get("artifacts") or {})
        artifacts["render_vars"] = _stub_render_vars(state)
        trace["analysis"] = {
            "status": "done",
            "role": "deterministic_renderer",
            "llm_calls": 0,
        }
        return {"artifacts": artifacts, "trace": trace}

    await emit_event({
        "type": "research_analyst_start",
        "role": "research_analyst",
        "status": "start",
    })
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
        "role": "research_analyst",
        "business_llm_calls": 1,
        "verifier_allowed": str(state.get("output_mode") or "") == "investment_report",
    }
    await emit_event({
        "type": "research_analyst_done",
        "role": "research_analyst",
        "status": "done",
    })
    return {**result, "trace": result_trace}


__all__ = ["analyze"]

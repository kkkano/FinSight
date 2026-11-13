# -*- coding: utf-8 -*-
"""证据分析边界：按逐任务合同区分事实查询和研究解释。"""
from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from backend.graph.event_bus import emit_event
from backend.graph.nodes.synthesize import synthesize
from backend.graph.state import GraphState
from backend.graph.synthesis.analysis_requirements import analysis_task_modes, task_needs_analysis
from backend.services.llm_usage import LLMAttribution, get_token_accumulator, reset_llm_attribution, set_llm_attribution
from backend.services.llm_retry import LLMCallContext, ainvoke_configured_llm, classify_llm_error
from backend.services.llm_response import final_completion_text
from backend.utils.env import env_int


def _needs_research_analyst(state: GraphState) -> bool:
    modes = analysis_task_modes(state)
    if modes:
        return "research" in modes.values()
    return task_needs_analysis(state, report=str(state.get("output_mode") or "").lower() == "investment_report")


async def _answer_direct_request(state: GraphState, trace: dict[str, Any]) -> dict[str, Any]:
    artifacts = dict(state.get("artifacts") or {})
    request = artifacts["direct_answer_request"]
    context = LLMCallContext.create(stage="direct_answer", agent="direct_answer", layer="analysis")
    attribution = set_llm_attribution(LLMAttribution(agent="direct_answer", layer="analysis"))
    try:
        response = await ainvoke_configured_llm(
            [SystemMessage(content="直接用简体中文回答用户的金融概念问题。遵守用户的范围与否定约束；虚构示例必须标明虚构。不调用工具、不声称查询过行情或实时资料。"),
             HumanMessage(content=str(request.get("query") or state.get("query") or ""))],
            context=context, temperature=0.1, acquire_token=True,
            max_tokens=env_int("LANGGRAPH_SYNTHESIZE_MAX_TOKENS", 65536),
            request_timeout=env_int("LANGGRAPH_SYNTHESIZE_TIMEOUT_SEC", 1200),
            acquire_timeout_seconds=env_int("LANGGRAPH_SYNTHESIZE_ACQUIRE_TIMEOUT_SEC", 120),
        )
        markdown = final_completion_text(response).strip()
        artifacts.update({"draft_markdown": markdown, "chat_responded": True})
        trace["analysis"] = {"status": "done", "role": "direct_answer", "business_llm_calls": context.budget.provider_attempts_used}
    except Exception as exc:
        code = classify_llm_error(exc).code
        artifacts.update({
            "draft_markdown": "本轮概念解释暂未生成成功，请稍后重试。", "chat_responded": True,
            "result_quality": {"state": "block", "answer_status": "unavailable", "publishable": False, "reasons": [{"code": code, "severity": "block"}]},
            "quality_blocked": True, "publishable": False,
        })
        trace["analysis"] = {"status": "failed", "role": "direct_answer", "error_code": code, "business_llm_calls": context.budget.provider_attempts_used}
    finally:
        reset_llm_attribution(attribution)
    return {"artifacts": artifacts, "trace": trace}


async def analyze(state: GraphState) -> dict[str, Any]:
    understanding = state.get("understanding") if isinstance(state.get("understanding"), dict) else {}
    route = str(understanding.get("route") or "clarify").strip().lower()
    trace = dict(state.get("trace") or {})
    if route != "research":
        artifacts = state.get("artifacts") or {}
        if route == "direct" and isinstance(artifacts.get("direct_answer_request"), dict) and not str(artifacts.get("draft_markdown") or "").strip():
            return await _answer_direct_request(state, trace)
        trace["analysis"] = {"status": "skipped", "llm_calls": 0, "reason": f"route:{route}"}
        return {"artifacts": dict(state.get("artifacts") or {}), "trace": trace}

    analyst = _needs_research_analyst(state)
    task_modes = analysis_task_modes(state)
    trace["analysis"] = {"mode": "research" if analyst else "deterministic", "task_modes": task_modes}
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
        "task_modes": task_modes,
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

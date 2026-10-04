# -*- coding: utf-8 -*-
"""请求理解节点：一次性完成闲聊、标的、任务和阻塞项识别。"""
from __future__ import annotations

import os
from typing import Any

from backend.config.ticker_mapping import extract_tickers, normalize_ticker
from backend.graph.request_constraints import concept_without_retrieval
from backend.graph.investment_intent import query_requests_investment_opinion
from backend.graph.intent.deterministic_engine import _emit_understanding_trace, route_request_deterministic
from backend.graph.event_bus import emit_event
from backend.graph.intent.frame import intent_frame_from_legacy
from backend.graph.intent.predicates import _history_tickers_from_messages
from backend.graph.state import GraphState
from backend.graph.semantic_requirements import extract_semantic_requirements, requires_semantic_extraction
from backend.graph.request_compiler import compile_semantic_contract, deterministic_fallback_contract


def _bind_task_render_identity(result: dict[str, Any]) -> dict[str, Any]:
    """任务种子只在此出口编译一次，所有下游消费同一合同。"""
    from backend.graph.request_compiler import finalize_request_contract

    understanding = result.get("understanding") or {}
    ready = result.get("tasks") or understanding.get("tasks") or []
    blocked = result.get("blocked_tasks") or understanding.get("blocked_tasks") or []
    query = str(understanding.get("original_query") or result.get("query") or "")
    if query_requests_investment_opinion(query) and not blocked and not any(task.get("tickers") for task in ready):
        blocked = [{
            "id": "blocked_1", "subject_type": "company", "subject_label": "未指定分析对象",
            "tickers": [], "operation": {"name": "investment_opinion", "confidence": 0.0},
            "priority": 50, "reason": "task_missing_subject", "error_code": "task_missing_subject",
            "question": "请补充需要分析的股票或基金代码。", "suggestions": [], "fallback_allowed": False,
        }]
        if not ready:
            understanding["route"] = "clarify"
            understanding["user_visible_summary"] = "需要补充投资标的"
            result["understanding"] = understanding
            result["clarify"] = {"needed": True, "reason": "task_missing_subject", "question": blocked[0]["question"], "suggestions": []}
            result["artifacts"] = {**dict(result.get("artifacts") or {}), "draft_markdown": blocked[0]["question"]}
    result["tasks"] = ready
    result["blocked_tasks"] = blocked
    return finalize_request_contract(result)

async def route_request(state: GraphState) -> dict[str, Any]:
    """规则绑定主体；复杂请求由当前模型确认原始要求，再做唯一合同投影。"""
    resolver_enabled = str(os.getenv("FINSIGHT_FINANCIAL_TERM_RESOLVER", "on")).strip().lower() != "off"
    if resolver_enabled:
        from backend.graph.intent.financial_terms import (
            build_financial_term_direct_result,
            resolve_financial_term_definition,
        )

        options = state.get("options") if isinstance(state.get("options"), dict) else {}
        ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
        forced_agent = bool(options.get("agents")) or bool(ui_context.get("agents_override"))
        match = resolve_financial_term_definition(
            str(state.get("query") or ""), str(state.get("output_mode") or "chat"), forced_agent=forced_agent,
        )
        if match is not None:
            return build_financial_term_direct_result(state, match)

    query = str(state.get("query") or "")
    if str(state.get("output_mode") or "chat") != "investment_report" and concept_without_retrieval(
        query, extract_tickers(query).get("tickers") or [],
        has_subject_context=bool(_history_tickers_from_messages(state, query)),
    ):
        from backend.graph.intent.decision import ContextBinding, ConversationDecision
        from backend.graph.intent.direct_reply import _direct_conversation_result
        from backend.graph.request_frame import compile_request_frame

        result = _direct_conversation_result(
            query=query, output_mode=str(state.get("output_mode") or "chat"),
            decision=ConversationDecision(execution_route="direct_answer", context_binding=ContextBinding(), domain_intent="finance_concept", confidence=0.9, needs_tools=False, reason="概念解释不需要行情或研究证据"),
            reply="", context_refs=[], artifacts=dict(state.get("artifacts") or {}), trace=dict(state.get("trace") or {}),
            request_frame=compile_request_frame(query=query,tickers=[],output_mode="chat"),
        )
        result["artifacts"]["direct_answer_request"] = {"query": query, "instructions": "直接解释用户的概念问题；需要例子时标明数字为虚构并保证计算自洽。不查询行情，不编造当前公司事实。"}
        result["chat_responded"] = False
    else:
        semantic_required = requires_semantic_extraction(query, output_mode=str(state.get("output_mode") or "chat"))
        result = await route_request_deterministic(state, emit_understanding=not semantic_required)
        if semantic_required:
            await emit_event({"type": "trace", "visibility": "user", "stage": "understanding", "status": "start",
                              "title": "正在确认研究范围", "summary": "正在核对原始要求、时间范围与所需输入。"})
            semantic, diagnostics = await extract_semantic_requirements(state, result)
            if semantic is not None:
                try:
                    result = compile_semantic_contract(result, semantic, diagnostics, input_context=state)
                except (ValueError, TypeError, KeyError) as exc:
                    diagnostics.update(status="unconfirmed", error_code="request_contract_unconfirmed", validation_code=str(exc), raw_semantic=semantic)
                    semantic = None
            if semantic is None:
                result = deterministic_fallback_contract(_bind_task_render_identity(result), diagnostics)
            await _emit_understanding_trace(result["understanding"])
        else:
            result = _bind_task_render_identity(result)
    understanding = result.get("understanding") if isinstance(result.get("understanding"), dict) else {}
    frame = intent_frame_from_legacy(understanding)
    frame.source = "selected_model_semantic_extraction" if understanding.get("requirements_status") == "confirmed" else "deterministic_rules"
    understanding["intent_frame"] = frame.model_dump()
    return result


__all__ = ["route_request"]

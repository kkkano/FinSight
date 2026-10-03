# -*- coding: utf-8 -*-
"""请求理解节点：一次性完成闲聊、标的、任务和阻塞项识别。"""
from __future__ import annotations

import os
from typing import Any

from backend.config.ticker_mapping import normalize_ticker
from backend.graph.investment_intent import query_requests_investment_opinion
from backend.graph.intent.deterministic_engine import route_request_deterministic
from backend.graph.intent.frame import intent_frame_from_legacy
from backend.graph.state import GraphState


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
    result["tasks"] = ready
    result["blocked_tasks"] = blocked
    return finalize_request_contract(result)

async def route_request(state: GraphState) -> dict[str, Any]:
    """规则优先地生成请求、任务与渲染身份，全程不调用 LLM。"""
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

    result = _bind_task_render_identity(await route_request_deterministic(state))
    understanding = result.get("understanding") if isinstance(result.get("understanding"), dict) else {}
    frame = intent_frame_from_legacy(understanding)
    frame.source = "deterministic_rules"
    understanding["intent_frame"] = frame.model_dump()
    return result


__all__ = ["route_request"]

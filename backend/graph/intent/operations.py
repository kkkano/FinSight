# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/understand_request.py（WP3 Task3，零行为变更）。
"""请求理解节点：一次性完成闲聊、标的、任务和阻塞项识别。"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import replace
from typing import Any

from langchain_core.messages import AIMessage

from backend.config.ticker_mapping import CN_TO_TICKER, COMPANY_MAP, dedup_tickers, extract_tickers, normalize_ticker
from backend.graph.earnings_intent import (
    query_requests_earnings_performance,
    query_requests_earnings_price_impact,
)
from backend.graph.event_bus import emit_event
from backend.graph.intent_contract import (
    derive_intent_contract,
    evidence_focused_operation,
    intent_contract_mode,
    legacy_operation_for_contract,
    requires_per_ticker_research,
    synthesis_compare_operation,
)
from backend.graph.investment_intent import (
    query_requests_comparative_investment_opinion,
    query_requests_investment_opinion,
)
from backend.graph.intent.router import (
    ContextBinding,
    ConversationDecision,
    _effective_current_turn_tickers,
    _task_hints_require_execution,
    generate_contextual_reply,
    route_conversation,
)
from backend.graph.nodes.decide_output_mode import decide_output_mode
from backend.graph.nodes.parse_operation import parse_operation
from backend.graph.nodes.query_intent import has_financial_intent, is_casual_chat, is_greeting
from backend.graph.memory_scope import current_report_context, current_thread_focus
from backend.graph.request_facets import derive_request_facets
from backend.graph.request_frame import compile_request_frame, compile_request_frames
from backend.graph.understanding_v2 import (
    build_understanding_v2,
    chat_multi_ticker_research_limit,
    has_comparison_relation,
    infer_facets,
    relation_operation_params,
    support_operations_for_relation,
)
from backend.graph.request_task_contract import (
    build_reply_contract,
    query_explicitly_requests_links,
    query_explicitly_requests_sources,
    reply_contract_disallows_news,
    wants_no_news_or_links,
)
from backend.graph.state import GraphState
from backend.graph.intent.predicates import (
    _contains_any,
    _explicit_multi_ticker_compare_requested,
    _is_lightweight_representative_compare,
)

logger = logging.getLogger(__name__)


from backend.graph.intent.keywords import (  # noqa: F401 —— 关键词单一来源（WP2-T2）
    _ALERT_HINTS,
    _ASSET_DEICTIC_HINTS,
    _COMPARE_HINTS,
    _FALLBACK_HINTS,
    _FORBIDDEN_DIRECT_REPLY_MARKERS,
    _GLOBAL_CHAT_VIEWS,
    _HOLDINGS_HINTS,
    _IMPACT_HINTS,
    _INDEX_TICKERS,
    _LIGHTWEIGHT_COMPARE_HINTS,
    _MACRO_HINTS,
    _NEWS_HINTS,
    _NON_ASSET_TOKENS,
    _PORTFOLIO_HINTS,
    _PRICE_HINTS,
    _PRIVATE_INSIDER_INFO_HINTS,
    _PUBLIC_INSIDER_DISCLOSURE_HINTS,
    _REPORT_PEER_CONTEXT_HINTS,
    _RESEARCH_CONFIRMATION_ACTION_TERMS,
    _RESEARCH_CONFIRMATION_ASK_TERMS,
    _ROUTER_GENERIC_COMPANY_OPERATIONS,
    _ROUTER_SPECIFIC_COMPANY_OPERATIONS,
    _SOCIAL_PREFIX_RE,
    _TECHNICAL_HINTS,
    _THEME_HINTS,
    _URL_RE,
    _VAGUE_SUBJECT_HINTS,
    _VALUATION_CONCEPT_HINTS,
    _VALUATION_JUDGMENT_HINTS,
)




def _operation(name: str, confidence: float = 0.75, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "confidence": confidence, "params": params or {}}

def _operation_with_report_peers(operation: dict[str, Any], peer_tickers: list[str]) -> dict[str, Any]:
    if not peer_tickers:
        return operation
    params = dict(operation.get("params") or {})
    params["peer_tickers"] = list(peer_tickers)
    params.setdefault("comparison_context", "covered_as_competitive_context")
    return {**operation, "params": params}

def _company_operations(
    query: str,
    *,
    tickers: list[str],
    allow_multi_ticker_default_compare: bool = True,
    output_mode: str = "",
) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    report_mode = str(output_mode or "").strip().lower() == "investment_report"
    if len(tickers) >= 2 and _is_lightweight_representative_compare(query):
        return [_operation("qa", 0.7)]
    if len(tickers) >= 2 and _explicit_multi_ticker_compare_requested(query, tickers):
        operations.append(_operation("compare", 0.86))
        return operations
    if not report_mode and query_requests_earnings_price_impact(query):
        operations.append(
            _operation(
                "earnings_impact",
                0.86,
                {
                    "event_type": "earnings",
                    "target_metric": "stock_price",
                    "required_dimensions": ["financials", "earnings", "price", "news", "risk"],
                },
            )
        )
        return operations
    if not report_mode and query_requests_earnings_performance(query):
        operations.append(_operation("earnings_performance", 0.84))
        return operations
    if not report_mode and _contains_any(query, _VALUATION_CONCEPT_HINTS) and _contains_any(query, _VALUATION_JUDGMENT_HINTS):
        operations.append(_operation("valuation_sanity", 0.84, {"target_metric": "valuation"}))
        return operations
    explicit_technical = _contains_any(query, _TECHNICAL_HINTS)
    if explicit_technical:
        operations.append(_operation("technical", 0.82))
    if not explicit_technical and query_requests_investment_opinion(query):
        operations.append(_operation("investment_opinion", 0.86))
        return operations
    if not explicit_technical and _contains_any(query, _PRICE_HINTS):
        operations.append(_operation("price", 0.82))
    if _contains_any(query, _NEWS_HINTS):
        news_params: dict[str, Any] = {"topic": "news"}
        if query_explicitly_requests_links(query):
            news_params["include_links"] = True
        operations.append(_operation("fetch", 0.78, news_params))
    if _contains_any(query, _IMPACT_HINTS):
        operations.append(_operation("analyze_impact", 0.78))
    if not explicit_technical and _contains_any(query, _TECHNICAL_HINTS):
        operations.append(_operation("technical", 0.82))
    if _contains_any(query, _ALERT_HINTS):
        operations.append(_operation("alert_set", 0.88))
    if operations:
        return operations

    subject = {"subject_type": "company", "tickers": tickers}
    parsed = parse_operation({"query": query, "subject": subject})
    operation = parsed.get("operation") or _operation("qa", 0.45)
    decision_trace = (parsed.get("trace") or {}).get("operation_decision") or {}
    if (
        len(tickers) >= 2
        and not allow_multi_ticker_default_compare
        and decision_trace.get("source") == "multi_ticker_default"
    ):
        return [_operation("price", max(float(operation.get("confidence") or 0.0), 0.62))]
    return [operation]

def _domain_intent_operation(domain_intent: str, confidence: float) -> dict[str, Any]:
    mapping = {
        "quote": "price",
        "news": "fetch",
        "analysis": "qa",
        "report_discussion": "qa",
        "doc_qa": "qa",
        "portfolio": "portfolio_impact",
    }
    return _operation(mapping.get(str(domain_intent or ""), "qa"), confidence)

def _router_guided_analysis_operation(decision: ConversationDecision) -> dict[str, Any]:
    """Use the LLM router's typed decision as the source of truth for analysis.

    Generic new-topic analysis with an explicit company is not automatically a
    long research plan. If the router says the answer needs tools, gather the
    light current context that a conversational user expects; if it says tools
    are not needed, keep it as contextual QA.
    """
    if decision.needs_tools:
        return _operation("daily_brief", max(decision.confidence, 0.7))
    return _operation("qa", max(decision.confidence, 0.68))

def _specific_company_operations(operations: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [
        operation
        for operation in (operations or [])
        if isinstance(operation, dict)
        and str(operation.get("name") or "").strip().lower() in _ROUTER_SPECIFIC_COMPANY_OPERATIONS
    ]

def _router_directed_company_operations(
    decision: ConversationDecision | None,
    *,
    fallback_operations: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]] | None:
    """Project the LLM router's typed intent into executable company tasks.

    The router already evaluates the full current turn and context. This small
    bridge keeps later legacy fallbacks from turning "quote these tickers" into
    a generic multi-ticker comparison.
    """
    if decision is None:
        return None
    if decision.execution_route == "alert" or decision.domain_intent == "alert":
        source_ops = [
            operation
            for operation in (fallback_operations or [])
            if isinstance(operation, dict)
            and str(operation.get("name") or "").strip()
            in {"fetch", "price", "news_impact", "analyze_impact", "technical"}
        ]
        if source_ops:
            return [*source_ops, _operation("alert_set", max(decision.confidence, 0.78))]
        return [_operation("alert_set", max(decision.confidence, 0.78))]
    if decision.context_binding.source not in {"none", ""}:
        return None
    specific_fallbacks = _specific_company_operations(fallback_operations)
    if specific_fallbacks:
        return specific_fallbacks
    if decision.domain_intent in {"quote", "news", "report_discussion", "doc_qa", "portfolio"}:
        primary = _domain_intent_operation(decision.domain_intent, decision.confidence)
        primary_name = str(primary.get("name") or "").strip()
        supplemental_ops = [
            operation
            for operation in (fallback_operations or [])
            if isinstance(operation, dict)
            and str(operation.get("name") or "").strip() in {"price", "fetch", "news_impact", "analyze_impact", "technical"}
            and str(operation.get("name") or "").strip() != primary_name
        ]
        return [primary, *supplemental_ops]
    if decision.domain_intent == "analysis":
        fallback_names = {
            str((operation or {}).get("name") or "").strip()
            for operation in (fallback_operations or [])
            if isinstance(operation, dict)
        }
        if fallback_names - {"", "qa"}:
            return None
        if decision.relation == "compare":
            return None
        return [_router_guided_analysis_operation(decision)]
    return None

def _macro_operation(query: str) -> dict[str, Any]:
    q = str(query or "").lower()
    if any(token in q for token in ("为什么", "为何", "怎么", "如何", "why", "mechanism")):
        return _operation("qa", 0.72)
    if any(h in query for h in ("降息没", "有没有降息", "概率", "变了吗", "事实", "核查")):
        return _operation("fact_check", 0.76)
    if _contains_any(query, _IMPACT_HINTS) or "估值" in query:
        return _operation("analyze_impact", 0.78)
    if _contains_any(query, _NEWS_HINTS):
        return _operation("fetch", 0.72, {"topic": "macro_news"})
    return _operation("macro_brief", 0.68)

def _macro_subject_label(query: str) -> str:
    q = str(query or "").lower()
    indicators = [
        ("cpi", "CPI"),
        ("ppi", "PPI"),
        ("fomc", "FOMC"),
        ("fed", "美联储"),
        ("美联储", "美联储"),
        ("联储", "美联储"),
        ("降息", "利率路径"),
        ("加息", "利率路径"),
        ("利率", "利率路径"),
        ("通胀", "通胀"),
        ("收益率", "国债收益率"),
        ("国债", "国债收益率"),
        ("纳指", "纳指"),
        ("大型科技股", "大型科技股"),
        ("科技股", "科技股"),
    ]
    labels: list[str] = []
    for token, label in indicators:
        if token in q and label not in labels:
            labels.append(label)
    return " / ".join(labels[:3]) if labels else "宏观环境"

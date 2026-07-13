# -*- coding: utf-8 -*-
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




















































































































































async def understand_request(state: GraphState) -> dict[str, Any]:
    """分发壳（WP2 Task 3）：FINSIGHT_INTENT_FRAME=off|shadow|on。

    off——完全走 legacy 关键词瀑布，仅用于显式回滚；
    shadow——新管线跑一遍只记 trace 影子，行为仍取 legacy（对拍用）；
    on（默认）——结构化新管线；任何未预期异常自动兜底回 legacy（安全阀）。
    """
    mode = str(os.getenv("FINSIGHT_INTENT_FRAME", "on")).strip().lower()
    if mode in {"shadow", "on"}:
        try:
            from backend.graph.intent.pipeline import build_intent_result

            frame, result = await build_intent_result(state)
        except Exception:
            logger.exception("[understand_request] intent pipeline failed; falling back to legacy")
            frame, result = None, None
        if mode == "on" and result is not None:
            await _emit_understanding_trace(result.get("understanding") or {})
            return result
        if mode == "shadow" and frame is not None:
            legacy = await _legacy_understand_request(state)
            try:
                trace = legacy.setdefault("trace", {})
                if isinstance(trace, dict):
                    trace["intent_frame_shadow"] = frame.model_dump()
            except Exception:
                logger.debug("shadow trace attach failed", exc_info=True)
            return legacy
    return await _legacy_understand_request(state)


__all__ = ["understand_request"]

# ---- WP3-T3 兼容 shim：内部实现已物理归位 backend/graph/intent/ 包 ----
# 旧 import 路径与 pipeline._ur() 的模块属性访问由以下再导出兜住（WP3-T8 统一删除）。
# monkeypatch 注意：patch 本模块属性不会传导到 intent.* 的调用点，请 patch 符号新家
#（route_conversation/generate_contextual_reply 的引擎级 patch 打到 intent.legacy_engine）。
from backend.graph.intent.predicates import (  # noqa: F401
    _binding_context_ref,
    _build_subject,
    _can_use_active_symbol_fallback,
    _contains_any,
    _context_tickers_from_binding,
    _direct_decision_contract_requires_evidence,
    _direct_decision_must_project_tasks,
    _explicit_multi_ticker_compare_requested,
    _explicit_report_mode,
    _extract_tickers_from_text,
    _extract_urls,
    _force_grounded_research_decision,
    _has_conversation_subject_anchor,
    _has_holdings_intent,
    _has_prior_dialogue,
    _history_tickers_from_messages,
    _holder_cik_or_name_from_query,
    _holdings_intent_params,
    _holdings_portfolio_context_available,
    _is_explicit_brief_request,
    _is_lightweight_representative_compare,
    _is_private_insider_information_request,
    _is_scoped_active_symbol_context,
    _normalize_selection,
    _portfolio_context_available,
    _portfolio_tickers_from_context,
    _positions_from_ui_context,
    _query_can_fallback_to_direct_finance_answer,
    _query_explicitly_requests_price_data,
    _query_frames_extra_tickers_as_report_context,
    _query_requests_company_side_data,
    _request_frame_blocks_direct_answer,
    _request_frame_is_authoritative_direct_answer,
    _request_frame_requires_execution,
    _selection_subject_type,
    _selection_urls,
    _split_primary_report_tickers,
    _strip_urls,
    _subject_type_for_decision,
    _subject_type_for_ticker,
    _time_scope,
)
from backend.graph.intent.operations import (  # noqa: F401
    _company_operations,
    _domain_intent_operation,
    _macro_operation,
    _macro_subject_label,
    _operation,
    _operation_with_report_peers,
    _router_directed_company_operations,
    _router_guided_analysis_operation,
    _specific_company_operations,
)
from backend.graph.intent.direct_reply import (  # noqa: F401
    _context_router_clarify_block,
    _direct_conversation_result,
    _direct_reply,
    _ensure_direct_reply_names_bound_tickers,
    _natural_clarify_question,
    _sanitize_direct_chat_reply,
    _social_prefix,
)
from backend.graph.intent.task_builders import (  # noqa: F401
    _FRAME_FRAGMENT_SPLIT_RE,
    _add_context_bound_research_task,
    _add_explicit_url_tasks,
    _add_holdings_intent_tasks,
    _add_per_ticker_company_tasks,
    _add_router_task_hints,
    _add_router_task_hints_contract,
    _add_task,
    _add_unbound_research_task,
    _apply_reply_contract_to_tasks,
    _prune_url_only_company_context_tasks,
    _router_hint_frame_query,
    _sanitize_blocked_task_questions,
)
from backend.graph.intent.legacy_engine import (  # noqa: F401
    _emit_understanding_trace,
    _legacy_understand_request,
)

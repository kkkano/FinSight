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
from backend.graph.intent.frame import intent_frame_from_legacy
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


def _bind_task_render_identity(result: dict[str, Any]) -> dict[str, Any]:
    """在 intent 出口封装任务身份；不读取计划、证据或执行结果。"""
    understanding = result.get("understanding") if isinstance(result.get("understanding"), dict) else {}
    ready = result.get("tasks") if isinstance(result.get("tasks"), list) else understanding.get("tasks")
    blocked = result.get("blocked_tasks") if isinstance(result.get("blocked_tasks"), list) else understanding.get("blocked_tasks")
    ready = [item for item in (ready or []) if isinstance(item, dict)]
    blocked = [item for item in (blocked or []) if isinstance(item, dict)]
    query = str(understanding.get("original_query") or result.get("query") or "")
    has_bound_opinion = any(
        str((item.get("operation") or {}).get("name") or "") == "investment_opinion"
        and bool(item.get("tickers"))
        for item in ready
        if isinstance(item.get("operation"), dict)
    )
    has_blocked_opinion = any(
        str(
            (item.get("operation") or {}).get("name")
            if isinstance(item.get("operation"), dict)
            else item.get("operation") or ""
        ).strip() == "investment_opinion"
        or str(item.get("error_code") or item.get("reason") or "").strip() == "task_missing_subject"
        for item in blocked
    )
    if query_requests_investment_opinion(query) and not has_bound_opinion and not has_blocked_opinion:
        blocked.append({
            "id": f"blocked_{len(blocked) + 1}",
            "title": "需要补充分析标的",
            "subject_type": "company",
            "subject_label": "未指定分析对象",
            "tickers": [],
            "operation": {"name": "investment_opinion", "confidence": 0.0},
            "priority": 50,
            "reason": "task_missing_subject",
            "error_code": "task_missing_subject",
            "question": "请补充需要分析的股票或基金代码。",
            "suggestions": [],
            "fallback_allowed": False,
        })
    frames = result.get("request_frames") if isinstance(result.get("request_frames"), list) else []
    frames = [item for item in frames if isinstance(item, dict)]
    if not frames and isinstance(result.get("request_frame"), dict):
        frames = [result["request_frame"]]

    def _frame_for_task(task: dict[str, Any], ordinal: int) -> dict[str, Any]:
        explicit_id = str(task.get("request_frame_id") or "").strip()
        if explicit_id:
            explicit = [frame for frame in frames if str(frame.get("frame_id") or "").strip() == explicit_id]
            if len(explicit) == 1:
                return explicit[0]
        task_tickers = {
            normalize_ticker(str(value))
            for value in (task.get("tickers") if isinstance(task.get("tickers"), list) else [])
            if normalize_ticker(str(value))
        }
        task_subject = str(task.get("subject_type") or "unknown").strip().lower()
        operation = task.get("operation") if isinstance(task.get("operation"), dict) else {}
        task_operation = str(operation.get("name") or task.get("operation") or "qa").strip()
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for index, frame in enumerate(frames):
            subject = frame.get("subject") if isinstance(frame.get("subject"), dict) else {}
            frame_tickers = {
                normalize_ticker(str(value))
                for value in (subject.get("tickers") if isinstance(subject.get("tickers"), list) else [])
                if normalize_ticker(str(value))
            }
            frame_subject = str(subject.get("type") or "unknown").strip().lower()
            legacy_operation = frame.get("legacy_operation") if isinstance(frame.get("legacy_operation"), dict) else {}
            frame_operation = str(legacy_operation.get("name") or "").strip()
            relation = str(frame.get("relation") or "").strip().lower()
            render = frame.get("render_contract") if isinstance(frame.get("render_contract"), dict) else {}
            compare = relation in {"compare", "rank"} or render.get("shape") == "compare"
            score = 0
            if task_tickers and frame_tickers and task_tickers <= frame_tickers:
                score += 8 if compare else 5
            elif task_tickers or frame_tickers:
                continue
            if task_subject == frame_subject:
                score += 4
            elif task_subject == "macro" or frame_subject == "macro":
                continue
            if frame_operation and task_operation == frame_operation:
                score += 3
            if compare and task_operation == "compare":
                score += 2
            if score:
                scored.append((-score, index, frame))
        if scored:
            return sorted(scored, key=lambda item: (item[0], item[1]))[0][2]
        if len(frames) == 1:
            return frames[0]
        return {
            "frame_id": f"request_frame_{ordinal}",
            "relation": "single",
            "subject": {"type": task_subject, "tickers": sorted(task_tickers)},
            "render_contract": {"shape": "answer"},
        }

    for order_index, task in enumerate([*ready, *blocked]):
        frame = _frame_for_task(task, order_index)
        frame_id = str(task.get("request_frame_id") or frame.get("frame_id") or f"request_frame_{order_index}").strip()
        render = frame.get("render_contract") if isinstance(frame.get("render_contract"), dict) else {}
        relation = str(frame.get("relation") or "").strip().lower()
        operation = task.get("operation") if isinstance(task.get("operation"), dict) else {}
        operation_name = str(operation.get("name") or task.get("operation") or "qa").strip()
        render_kind = "compare" if relation in {"compare", "rank"} or render.get("shape") == "compare" or operation_name == "compare" else "single"
        tickers = []
        for ticker in task.get("tickers") if isinstance(task.get("tickers"), list) else []:
            normalized = normalize_ticker(str(ticker))
            if normalized and normalized not in tickers:
                tickers.append(normalized)
        subject_label = str(task.get("subject_label") or task.get("subject_type") or "未指定分析对象").strip() or "未指定分析对象"
        task.update({
            "title": str(task.get("title") or subject_label).strip() or subject_label,
            "subject_label": subject_label,
            "tickers": tickers,
            "priority": max(0, int(task.get("priority"))) if isinstance(task.get("priority"), int) else 50,
            "order_index": order_index,
            "request_frame_id": frame_id,
            "render_kind": render_kind,
            "render_group_id": str(task.get("render_group_id") or frame_id).strip() or frame_id,
        })
        if order_index >= len(ready):
            task.setdefault("error_code", str(task.get("reason") or "task_blocked").strip() or "task_blocked")
    understanding["tasks"] = ready
    understanding["blocked_tasks"] = blocked
    result["understanding"] = understanding
    result["tasks"] = ready
    result["blocked_tasks"] = blocked
    return result


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

    mode = str(os.getenv("FINSIGHT_INTENT_FRAME", "on")).strip().lower()
    if mode in {"shadow", "on"}:
        try:
            from backend.graph.intent.pipeline import build_intent_result

            frame, result = await build_intent_result(state)
        except Exception:
            logger.exception("[understand_request] intent pipeline failed; falling back to legacy")
            frame, result = None, None
        if mode == "on" and result is not None:
            result = _bind_task_render_identity(result)
            frame = intent_frame_from_legacy(result.get("understanding") or {})
            frame.source = "llm_router"
            result["understanding"]["intent_frame"] = frame.model_dump()
            await _emit_understanding_trace(result.get("understanding") or {})
            return result
        if mode == "shadow" and frame is not None:
            legacy = _bind_task_render_identity(await _legacy_understand_request(state))
            try:
                trace = legacy.setdefault("trace", {})
                if isinstance(trace, dict):
                    trace["intent_frame_shadow"] = frame.model_dump()
            except Exception:
                logger.debug("shadow trace attach failed", exc_info=True)
            return legacy
    return _bind_task_render_identity(await _legacy_understand_request(state))


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

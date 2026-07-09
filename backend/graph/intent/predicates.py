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




def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    for hint in hints:
        needle = str(hint or "").strip().lower()
        if not needle:
            continue
        if re.fullmatch(r"[a-z0-9]{1,3}", needle):
            if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", lowered):
                return True
            continue
        if needle in lowered:
            return True
    return False

def _is_private_insider_information_request(query: str) -> bool:
    lowered = str(query or "").lower()
    if not any(token in lowered for token in _PRIVATE_INSIDER_INFO_HINTS):
        return False
    return not any(token in lowered for token in _PUBLIC_INSIDER_DISCLOSURE_HINTS)

def _has_holdings_intent(query: str) -> bool:
    if _is_private_insider_information_request(query):
        return False
    if query_requests_investment_opinion(query):
        return False
    return _contains_any(query, _HOLDINGS_HINTS)

def _holder_cik_or_name_from_query(query: str) -> str:
    if _contains_any(query, ("buffett", "berkshire", "巴菲特", "伯克希尔")):
        return "Berkshire Hathaway"
    return ""

def _holdings_intent_params(query: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    holder = _holder_cik_or_name_from_query(query)
    if holder:
        params["holder_cik_or_name"] = holder
    if _contains_any(query, ("form 4", "form4", "insider", "内部人交易")):
        params["focus"] = "insider_transactions"
    elif _contains_any(query, ("13f", "institutional holdings", "机构持仓", "名人持仓", "名义持仓", "增持", "减持", "加仓")):
        params["focus"] = "institutional_holdings"
    return params

def _is_lightweight_representative_compare(query: str) -> bool:
    return _contains_any(query, _THEME_HINTS) and _contains_any(query, _LIGHTWEIGHT_COMPARE_HINTS)

def _is_explicit_brief_request(query: str) -> bool:
    text = str(query or "")
    return any(token in text for token in ("30秒", "先别做长报告", "不要长篇", "快速"))

def _extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in _URL_RE.finditer(str(text or "")):
        url = match.group(0).rstrip(".,，。;；:：!?！？")
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls[:3]

def _strip_urls(text: str) -> str:
    return _URL_RE.sub(" ", str(text or ""))

def _is_scoped_active_symbol_context(ui_context: dict[str, Any]) -> bool:
    view = str((ui_context or {}).get("view") or "").strip().lower()
    return bool(view) and view not in _GLOBAL_CHAT_VIEWS

def _has_conversation_subject_anchor(memory_context: dict[str, Any]) -> bool:
    if not isinstance(memory_context, dict):
        return False
    if current_report_context(memory_context):
        return True
    last_focus = current_thread_focus(memory_context)
    if isinstance(last_focus, dict) and (last_focus.get("ticker") or last_focus.get("query")):
        return True
    return False

def _has_prior_dialogue(state: GraphState, current_query: str) -> bool:
    messages = state.get("messages")
    if not isinstance(messages, list):
        return False
    current = str(current_query or "").strip()
    for msg in messages:
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        text = str(content or "").strip()
        if text and text != current:
            return True
    return False

def _history_tickers_from_messages(state: GraphState, current_query: str) -> list[str]:
    messages = state.get("messages")
    if not isinstance(messages, list):
        return []
    current = str(current_query or "").strip()
    tickers: list[str] = []
    for msg in reversed(messages[-8:]):
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        text = str(content or "").strip()
        if not text or text == current:
            continue
        tickers.extend(_extract_tickers_from_text(text))
    return dedup_tickers(tickers)

def _can_use_active_symbol_fallback(ui_context: dict[str, Any], memory_context: dict[str, Any]) -> bool:
    if not isinstance(ui_context.get("active_symbol"), str) or not ui_context["active_symbol"].strip():
        return False
    if _is_scoped_active_symbol_context(ui_context):
        return True
    return not _has_conversation_subject_anchor(memory_context)

def _explicit_report_mode(state: GraphState, output_mode: str) -> bool:
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    analysis_depth = str((ui_context or {}).get("analysis_depth") or "").strip().lower()
    return output_mode == "investment_report" or analysis_depth == "deep_research"

def _explicit_multi_ticker_compare_requested(query: str, tickers: list[str] | None = None) -> bool:
    if _is_lightweight_representative_compare(query):
        return False
    return _contains_any(query, _COMPARE_HINTS) or query_requests_comparative_investment_opinion(query, tickers or [])

def _query_frames_extra_tickers_as_report_context(query: str) -> bool:
    return _contains_any(query, _REPORT_PEER_CONTEXT_HINTS)

def _split_primary_report_tickers(
    query: str,
    tickers: list[str],
    *,
    state: GraphState,
    output_mode: str,
) -> tuple[list[str], list[str]]:
    if (
        len(tickers) < 2
        or not _explicit_report_mode(state, output_mode)
        or _explicit_multi_ticker_compare_requested(query, tickers)
        or not _query_frames_extra_tickers_as_report_context(query)
    ):
        return tickers, []
    return [tickers[0]], tickers[1:]

def _subject_type_for_ticker(ticker: str) -> str:
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        return "unknown"
    if symbol.endswith("=F"):
        return "commodity"
    if symbol.startswith("^") or symbol in _INDEX_TICKERS:
        return "index"
    return "company"

def _selection_subject_type(selection_types: list[str]) -> str:
    if not selection_types:
        return "research_doc"
    if len(selection_types) == 1:
        first = selection_types[0]
        if first == "news":
            return "news_item"
        if first == "filing":
            return "filing"
        if first in {"url", "web", "article"}:
            return "research_doc"
        return "research_doc"
    if all(t == "news" for t in selection_types):
        return "news_set"
    if all(t == "filing" for t in selection_types):
        return "filing"
    return "research_doc"

def _time_scope(query: str) -> dict[str, Any]:
    q = query.lower()
    if "昨天" in q or "yesterday" in q:
        return {"kind": "yesterday", "label": "昨天"}
    if "今天" in q or "今日" in q or "today" in q:
        return {"kind": "today", "label": "今天"}
    if "这周" in q or "本周" in q or "this week" in q:
        return {"kind": "this_week", "label": "本周"}
    if "最近" in q or "recent" in q:
        return {"kind": "recent", "label": "最近"}
    if "最新" in q or "latest" in q:
        return {"kind": "latest", "label": "最新"}
    return {"kind": "unspecified", "label": ""}

def _subject_type_for_decision(decision: ConversationDecision) -> str:
    if decision.context_binding.source == "portfolio":
        return "portfolio"
    if decision.context_binding.source == "selection":
        return "research_doc"
    if decision.domain_intent in {"news", "analysis"}:
        return "theme"
    return "unknown"

def _query_explicitly_requests_price_data(query: str) -> bool:
    text = str(query or "")
    if wants_no_news_or_links(text):
        return False
    lowered = text.lower()
    return bool(
        re.search(r"\b(?:what|which|where)\s+(?:is|are)?\s*(?:the\s+)?(?:current\s+)?(?:stock\s+)?(?:price|quote)\b", lowered)
        or re.search(r"\b(?:current|real-time|realtime|latest)\s+(?:stock\s+)?(?:price|quote)\b", lowered)
        or re.search(r"\b(?:price|prices|quote)\s+now\b", lowered)
        or re.search(r"\b(?:current|latest|recent|today'?s?)\s+(?:stock\s+)?performance\b", lowered)
        or re.search(r"\bperformance\s+(?:now|today|recently)\b", lowered)
        or re.search(r"\bhow\s+much\s+(?:is|are)\b", lowered)
        or re.search(r"\b(?:trading|trade)\s+at\b", lowered)
        or _contains_any(
            text,
            (
                "最新股价",
                "实时股价",
                "当前股价",
                "现在股价",
                "股价多少",
                "价格多少",
                "现在多少钱",
                "当前价格",
                "实时报价",
                "报价",
                "行情",
                "最新表现",
                "近期表现",
                "今天表现",
                "今日表现",
                "涨了多少",
                "跌了多少",
                "涨幅",
                "跌幅",
            ),
        )
    )

def _direct_decision_contract_requires_evidence(
    query: str,
    decision: ConversationDecision,
    *,
    current_tickers: list[str] | None = None,
) -> bool:
    tickers = dedup_tickers(
        list(current_tickers or [])
        or [
            str(ticker)
            for ticker in (extract_tickers(_strip_urls(query)).get("tickers") or [])
            if str(ticker).strip()
        ]
    )
    if not tickers:
        return False
    contract = derive_intent_contract(
        query=query,
        tickers=tickers,
        output_mode="chat",
        comparison_requested=False,
        domain_intent=decision.domain_intent,
        subject_type="company",
        frame_id="direct_projection_probe",
    )
    facets = {str(facet) for facet in (contract.get("facets") or []) if str(facet).strip()}
    return bool("external_entity_impact" in facets and contract.get("required_evidence"))

def _direct_decision_must_project_tasks(
    query: str,
    decision: ConversationDecision,
    *,
    current_tickers: list[str] | None = None,
    request_frame: dict[str, Any] | None = None,
) -> bool:
    """Prevent an LLM direct route from swallowing explicit tool/data requests."""
    if _request_frame_blocks_direct_answer(request_frame):
        return True
    if wants_no_news_or_links(query):
        return False
    return bool(
        _extract_urls(query)
        or query_explicitly_requests_sources(query)
        or _contains_any(query, _NEWS_HINTS)
        or _contains_any(query, _TECHNICAL_HINTS)
        or query_requests_investment_opinion(query)
        or _query_explicitly_requests_price_data(query)
        or _contains_any(query, _PORTFOLIO_HINTS)
        or decision.needs_tools
        or _task_hints_require_execution(decision.task_hints, query, allow_subject_label_refs=True)
        or (
            intent_contract_mode() == "enforce"
            and _direct_decision_contract_requires_evidence(query, decision, current_tickers=current_tickers)
        )
        or (decision.domain_intent == "quote" and _query_explicitly_requests_price_data(query))
        or decision.domain_intent in {"news", "doc_qa", "portfolio", "alert"}
    )

def _request_frame_requires_execution(request_frame: dict[str, Any] | None) -> bool:
    if not isinstance(request_frame, dict):
        return False
    evidence = request_frame.get("evidence_obligations")
    results = request_frame.get("required_results")
    action = request_frame.get("workflow_action")
    return bool(
        (isinstance(evidence, list) and evidence)
        or (isinstance(results, list) and results)
        or isinstance(action, dict)
    )

def _request_frame_is_authoritative_direct_answer(
    request_frame: dict[str, Any] | None,
    query: str = "",
) -> bool:
    if not isinstance(request_frame, dict):
        return False
    if _request_frame_requires_execution(request_frame):
        return False
    if str(request_frame.get("lane") or "").strip().lower() != "answer":
        return False
    query = str(query or request_frame.get("query") or "")
    if _contains_any(query, _VAGUE_SUBJECT_HINTS):
        return False
    lowered = query.lower()
    return bool(
        re.search(r"\b(why|how|what is|define|explain|mechanism)\b", lowered)
        or "为什么" in query
        or "为何" in query
        or "怎么" in query
        or "如何" in query
        or "什么是" in query
        or "解释" in query
        or "机制" in query
        or "原理" in query
    )

def _request_frame_blocks_direct_answer(request_frame: dict[str, Any] | None) -> bool:
    if not _request_frame_requires_execution(request_frame):
        return False
    if not isinstance(request_frame, dict):
        return False
    results = request_frame.get("required_results")
    action = request_frame.get("workflow_action")
    if (isinstance(results, list) and results) or isinstance(action, dict):
        return True
    relation = str(request_frame.get("relation") or "").strip().lower()
    render_contract = request_frame.get("render_contract")
    render_shape = (
        str(render_contract.get("shape") or "").strip().lower()
        if isinstance(render_contract, dict)
        else ""
    )
    if relation in {"compare", "rank", "impact"} or render_shape == "compare":
        return True
    evidence = {
        str(item).strip()
        for item in (request_frame.get("evidence_obligations") or [])
        if str(item).strip()
    }
    return bool(
        evidence
        & {
            "macro_context",
            "holdings_ownership",
            "earnings_estimates",
            "fundamental_snapshot",
            "filing_context",
            "transcript_context",
            "event_calendar",
        }
    )

def _force_grounded_research_decision(decision: ConversationDecision) -> ConversationDecision:
    return replace(
        decision,
        execution_route="research",
        needs_tools=True,
        confidence=max(decision.confidence, 0.74),
        reason=decision.reason or "explicit current-data/tool request must project tasks",
    )

def _query_requests_company_side_data(query: str) -> bool:
    text = _strip_urls(str(query or ""))
    if wants_no_news_or_links(text):
        return False
    return bool(
        _query_explicitly_requests_price_data(text)
        or _contains_any(text, _NEWS_HINTS)
        or _contains_any(text, _TECHNICAL_HINTS)
        or _contains_any(text, _PORTFOLIO_HINTS)
    )

def _query_can_fallback_to_direct_finance_answer(query: str) -> bool:
    text = _strip_urls(str(query or "")).strip()
    if not text:
        return False
    if _extract_urls(text) or query_explicitly_requests_sources(text) or query_explicitly_requests_links(text):
        return False
    if _query_explicitly_requests_price_data(text) or _contains_any(text, _TECHNICAL_HINTS) or query_requests_investment_opinion(text) or _contains_any(text, _PORTFOLIO_HINTS):
        return False
    if not wants_no_news_or_links(text) and _contains_any(text, _NEWS_HINTS):
        return False
    return bool(has_financial_intent(text) or _contains_any(text, _THEME_HINTS))

def _normalize_selection(ui_context: dict[str, Any]) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    raw = ui_context.get("selections")
    if not raw and isinstance(ui_context.get("selection"), dict):
        raw = [ui_context["selection"]]
    selections = raw if isinstance(raw, list) else []
    payload = [item for item in selections if isinstance(item, dict)]
    ids: list[str] = []
    types: list[str] = []
    seen_ids: set[str] = set()
    for item in payload:
        item_id = str(item.get("id") or "").strip()
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "report":
            item_type = "doc"
        if item_id and item_id not in seen_ids:
            seen_ids.add(item_id)
            ids.append(item_id)
        if item_type:
            types.append(item_type)
    return ids, types, payload

def _selection_urls(ui_context: dict[str, Any]) -> list[str]:
    raw = ui_context.get("selections")
    if not raw and isinstance(ui_context.get("selection"), dict):
        raw = [ui_context["selection"]]
    selections = raw if isinstance(raw, list) else []
    urls: list[str] = []
    seen: set[str] = set()
    for item in selections:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip().rstrip(".,，。；;!?！？")
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls[:3]

def _portfolio_context_available(query: str, ui_context: dict[str, Any]) -> bool:
    if "我持有" in query or "持有" in query and bool(extract_tickers(query).get("tickers")):
        return True
    for key in ("portfolio", "positions", "holdings"):
        value = ui_context.get(key)
        if isinstance(value, (list, tuple, dict)) and len(value) > 0:
            return True
    return False

def _extract_tickers_from_text(text: str) -> list[str]:
    if not str(text or "").strip():
        return []
    return dedup_tickers(
        [
            str(t)
            for t in (extract_tickers(str(text)).get("tickers") or [])
            if str(t).strip() and str(t).strip().upper() not in _NON_ASSET_TOKENS
        ]
    )

def _portfolio_tickers_from_context(ui_context: dict[str, Any]) -> list[str]:
    raw_items: list[Any] = []
    for key in ("portfolio", "positions", "holdings"):
        value = ui_context.get(key)
        if isinstance(value, dict):
            raw_items.extend(value.keys())
            raw_items.extend(value.values())
        elif isinstance(value, (list, tuple)):
            raw_items.extend(value)

    candidates: list[str] = []
    for item in raw_items:
        if isinstance(item, dict):
            candidates.extend(
                str(item.get(key) or "")
                for key in ("ticker", "symbol", "asset", "id")
                if item.get(key)
            )
        elif isinstance(item, str):
            candidates.append(item)

    tickers: list[str] = []
    for candidate in candidates:
        tickers.extend(_extract_tickers_from_text(candidate) or [normalize_ticker(candidate)])
    return dedup_tickers([ticker for ticker in tickers if ticker])

def _positions_from_ui_context(ui_context: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized visible portfolio positions without inventing holdings."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for key in ("positions", "holdings", "portfolio"):
        value = ui_context.get(key)
        if isinstance(value, dict):
            iterable: list[Any] = []
            for raw_key, raw_value in value.items():
                if isinstance(raw_value, dict):
                    item = dict(raw_value)
                    item.setdefault("ticker", raw_key)
                    iterable.append(item)
                else:
                    iterable.append({"ticker": raw_key, "weight": raw_value})
        elif isinstance(value, (list, tuple)):
            iterable = list(value)
        else:
            continue

        for item in iterable:
            if isinstance(item, dict):
                ticker = normalize_ticker(str(item.get("ticker") or item.get("symbol") or item.get("asset") or item.get("id") or ""))
                if not ticker or ticker in seen:
                    continue
                normalized = dict(item)
                normalized["ticker"] = ticker
                rows.append(normalized)
                seen.add(ticker)
            elif isinstance(item, str):
                ticker = normalize_ticker(item)
                if ticker and ticker not in seen:
                    rows.append({"ticker": ticker})
                    seen.add(ticker)
    return rows

def _holdings_portfolio_context_available(
    query: str,
    ui_context: dict[str, Any],
    tickers: list[str],
) -> bool:
    if _portfolio_context_available(query, ui_context):
        return True
    lowered = str(query or "").lower()
    if tickers and ("我的" in query or "my " in lowered) and _contains_any(query, ("组合", "portfolio")):
        return True
    return False

def _binding_context_ref(binding: Any, *, value: Any = "") -> dict[str, Any]:
    return {
        "source": "conversation_context",
        "key": getattr(binding, "source", "none"),
        "label": getattr(binding, "subject_hint", "") or getattr(binding, "source", "conversation_context"),
        "value": value or getattr(binding, "reason", ""),
    }

def _context_tickers_from_binding(
    *,
    binding: Any,
    ui_context: dict[str, Any],
    memory_context: dict[str, Any],
) -> list[str]:
    source = str(getattr(binding, "source", "") or "")
    candidates: list[str] = []
    subject_hint = str(getattr(binding, "subject_hint", "") or "")
    if subject_hint:
        candidates.append(subject_hint)

    if source == "active_symbol":
        candidates.append(str(ui_context.get("active_symbol") or ""))
    elif source == "last_report":
        report = current_report_context(memory_context) or {}
        candidates.append(str(report.get("ticker") or ""))
        candidates.append(str(report.get("title") or ""))

    tickers: list[str] = []
    for candidate in candidates:
        if not candidate.strip():
            continue
        extracted = _extract_tickers_from_text(candidate)
        tickers.extend(extracted or [normalize_ticker(candidate)])
    return dedup_tickers([ticker for ticker in tickers if re.match(r"^[A-Z0-9^][A-Z0-9.\-=]{0,14}$", ticker)])


def _build_subject(
    primary: dict[str, Any] | None,
    selection_payload: list[dict[str, Any]],
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not primary:
        return {
            "subject_type": "unknown",
            "tickers": [],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
            "binding_tier": "understanding_none",
        }
    merged_tickers = dedup_tickers(
        [
            str(ticker)
            for task in (tasks or [])
            if isinstance(task, dict)
            for ticker in (task.get("tickers") or [])
            if str(ticker or "").strip()
        ]
    )
    if not merged_tickers:
        merged_tickers = list(primary.get("tickers") or [])
    return {
        "subject_type": primary.get("subject_type") or "unknown",
        "tickers": merged_tickers,
        "selection_ids": list(primary.get("selection_ids") or []),
        "selection_types": list(primary.get("selection_types") or []),
        "selection_payload": selection_payload if primary.get("selection_ids") else [],
        "binding_tier": "understanding",
        "is_comparison": (primary.get("operation") or {}).get("name") == "compare",
    }

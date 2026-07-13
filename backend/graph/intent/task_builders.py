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
from backend.graph.intent.direct_reply import _natural_clarify_question
from backend.graph.intent.operations import (
    _company_operations,
    _domain_intent_operation,
    _operation,
    _router_guided_analysis_operation,
    _specific_company_operations,
)
from backend.graph.intent.predicates import (
    _binding_context_ref,
    _contains_any,
    _context_tickers_from_binding,
    _explicit_multi_ticker_compare_requested,
    _extract_urls,
    _has_holdings_intent,
    _holdings_intent_params,
    _holdings_portfolio_context_available,
    _portfolio_context_available,
    _portfolio_tickers_from_context,
    _positions_from_ui_context,
    _query_requests_company_side_data,
    _selection_subject_type,
    _selection_urls,
    _subject_type_for_decision,
    _subject_type_for_ticker,
    _time_scope,
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




_FRAME_FRAGMENT_SPLIT_RE = re.compile(
    r"[\u3001,\uff0c;\uff1b\u3002.!?\uff1f\uff01]+"
    r"|\b(?:and|then|also)\b"
    r"|(?:\u7136\u540e|\u518d|\u4ee5\u53ca|\u5e76\u4e14)",
    re.IGNORECASE,
)

def _router_hint_frame_query(
    *,
    query: str,
    subject_type: str,
    subject_label: str,
    tickers: list[str],
    params: dict[str, Any],
    operation_name: str,
    comparison_requested: bool,
) -> str:
    """Recover the query text for one router frame before compiling a contract.

    Router task operations are only weak fallback signals.  The contract must be
    compiled from the user's frame text whenever that text can be recovered.
    """
    raw_query = str(query or "").strip()
    if not raw_query or comparison_requested:
        return raw_query

    fragments = [part.strip() for part in _FRAME_FRAGMENT_SPLIT_RE.split(raw_query) if part.strip()]
    labels = [str(subject_label or "").strip(), *[str(ticker or "").strip() for ticker in tickers]]
    for ticker in tickers:
        normalized = normalize_ticker(str(ticker or ""))
        if not normalized:
            continue
        mapped_name = COMPANY_MAP.get(normalized)
        if isinstance(mapped_name, str):
            labels.append(mapped_name)
        for alias, value in COMPANY_MAP.items():
            if str(value).upper() == normalized:
                labels.append(str(alias))
        for alias, value in CN_TO_TICKER.items():
            if normalize_ticker(str(value)) == normalized:
                labels.append(str(alias))
    labels = [label for label in labels if label]

    matched: list[str] = []
    for fragment in fragments:
        fragment_upper = fragment.upper()
        if any(label.upper() in fragment_upper for label in labels):
            matched.append(fragment)

    if not matched and subject_type in {"macro", "theme"}:
        for fragment in fragments:
            if _contains_any(fragment, _MACRO_HINTS + _IMPACT_HINTS):
                matched.append(fragment)

    if matched:
        return " ".join(matched)

    topic = params.get("topic") if isinstance(params.get("topic"), str) else ""
    evidence_focus = params.get("evidence_focus") if isinstance(params.get("evidence_focus"), str) else ""
    facets = params.get("facets") if isinstance(params.get("facets"), list) else []
    parts = [subject_label, topic, evidence_focus, *[str(facet) for facet in facets if str(facet).strip()]]
    if operation_name not in {"qa", "compare"}:
        parts.append(operation_name)
    frame_query = " ".join(str(part) for part in parts if str(part or "").strip()).strip()
    return frame_query or raw_query

def _apply_reply_contract_to_tasks(tasks: list[dict[str, Any]], reply_contract: dict[str, Any]) -> None:
    """Apply hard UX constraints before policy/planner see the task list."""
    if not reply_contract_disallows_news({"reply_contract": reply_contract}):
        return
    for task in tasks:
        if not isinstance(task, dict):
            continue
        operation = task.get("operation")
        if not isinstance(operation, dict):
            continue
        op_name = str(operation.get("name") or "").strip()
        if op_name not in {"fetch", "news_impact", "daily_brief", "morning_brief"}:
            continue
        params = dict(operation.get("params") or {})
        topic = str(params.get("topic") or "").strip().lower()
        if op_name == "fetch" and topic and topic != "news":
            continue
        try:
            confidence = float(operation.get("confidence") or 0.0)
        except Exception:
            confidence = 0.0
        task["operation"] = {
            **operation,
            "name": "qa",
            "confidence": max(confidence, 0.68),
            "params": {k: v for k, v in params.items() if k not in {"topic", "include_links"}},
        }
        constraints = list(task.get("constraints") or [])
        if "no_news_or_links" not in constraints:
            constraints.append("no_news_or_links")
        task["constraints"] = constraints

def _add_per_ticker_company_tasks(
    tasks: list[dict[str, Any]],
    *,
    tickers: list[str],
    operations: list[dict[str, Any]],
    query: str,
    priority: int,
    reason: str,
) -> None:
    for ticker in tickers:
        subject_type = _subject_type_for_ticker(ticker)
        for operation in operations:
            _add_task(
                tasks,
                subject_type=subject_type,
                operation=operation,
                query=query,
                tickers=[ticker],
                subject_label=ticker,
                priority=priority,
                reason=reason,
            )

def _add_unbound_research_task(
    *,
    tasks: list[dict[str, Any]],
    decision: ConversationDecision,
    query: str,
) -> None:
    """Convert an LLM research decision without a ticker into a generic task.

    This keeps the planner gate generic. The LLM router decides that evidence or
    tools are needed; the task only carries that intent forward without adding a
    new keyword table.
    """
    subject_type = _subject_type_for_decision(decision)
    subject_label = decision.context_binding.subject_hint or query[:80]
    _add_task(
        tasks,
        subject_type=subject_type,
        subject_label=subject_label,
        operation=_domain_intent_operation(decision.domain_intent, decision.confidence),
        query=query,
        priority=50,
        reason="conversation_router_unbound_research",
        params={"context_binding": decision.context_binding.model_dump()},
    )

def _add_explicit_url_tasks(
    *,
    tasks: list[dict[str, Any]],
    query: str,
    current_tickers: list[str],
) -> bool:
    urls = _extract_urls(query)
    if not urls:
        return False
    existing_urls: set[str] = set()
    for task in tasks:
        op = task.get("operation") if isinstance(task.get("operation"), dict) else {}
        params = op.get("params") if isinstance(op.get("params"), dict) else {}
        value = str(params.get("url") or "").strip()
        if value:
            existing_urls.add(value)
        raw_urls = params.get("urls")
        if isinstance(raw_urls, list):
            existing_urls.update(str(item or "").strip() for item in raw_urls if str(item or "").strip())
    added = False
    scoped_tickers = dedup_tickers(list(current_tickers or []))
    for idx, url in enumerate(urls, 1):
        if url in existing_urls:
            continue
        _add_task(
            tasks,
            subject_type="research_doc",
            subject_label=url,
            operation=_operation("qa", 0.68, {"url": url}),
            query=query,
            tickers=scoped_tickers,
            priority=17 + idx,
            reason="explicit_url_reference",
            params={"url": url},
        )
        added = True
    return added

def _add_router_task_hints(
    *,
    tasks: list[dict[str, Any]],
    context_refs: list[dict[str, Any]],
    decision: ConversationDecision,
    query: str,
    current_tickers: list[str],
    output_mode: str = "",
    selection_ids: list[str] | None = None,
    selection_types: list[str] | None = None,
) -> bool:
    """Project LLM-decomposed atomic requests into tasks.

    This is the generic path for compound turns. The LLM router owns the
    semantic split; this function only validates enum-like fields and preserves
    explicit ticker/subject payloads.
    """
    added = False
    bound_tickers: list[str] = []
    if decision.context_binding.source != "selection":
        for task in tasks:
            raw_tickers = task.get("tickers")
            if not isinstance(raw_tickers, list):
                continue
            bound_tickers.extend(normalize_ticker(str(ticker)) for ticker in raw_tickers if str(ticker).strip())
    scoped_current_tickers = dedup_tickers(list(current_tickers or []) + bound_tickers)

    def _has_task(operation_name: str, ticker: str) -> bool:
        wanted = normalize_ticker(str(ticker))
        for task in tasks:
            op = (task.get("operation") or {}).get("name") if isinstance(task.get("operation"), dict) else None
            if str(op or "").strip().lower() != operation_name:
                continue
            if wanted in [normalize_ticker(str(item)) for item in (task.get("tickers") or [])]:
                return True
        return False

    def _add_support_task(
        *,
        ticker: str,
        subject_type: str,
        operation_name: str,
        params: dict[str, Any] | None,
        priority: int,
    ) -> None:
        if _has_task(operation_name, ticker):
            return
        _add_task(
            tasks,
            subject_type=subject_type,
            subject_label=ticker,
            operation=_operation(operation_name, max(decision.confidence, 0.68), params or {}),
            query=query,
            tickers=[ticker],
            priority=priority,
            reason="conversation_router_task_hint_support",
            params=params or {},
        )

    for idx, hint in enumerate(decision.task_hints or (), 1):
        if not isinstance(hint, dict):
            continue
        operation_name = str(hint.get("operation") or "qa").strip().lower()
        if operation_name == "alert_set":
            continue
        subject_type = str(hint.get("subject_type") or "unknown").strip().lower()
        subject_label = str(hint.get("subject_label") or "").strip()
        hint_tickers = [
            normalize_ticker(str(ticker))
            for ticker in (hint.get("tickers") if isinstance(hint.get("tickers"), list) else [])
            if str(ticker).strip()
        ]
        if not hint_tickers and subject_label:
            hint_tickers = [
                normalize_ticker(str(ticker))
                for ticker in (extract_tickers(subject_label).get("tickers") or [])
                if str(ticker).strip()
            ]
        if not hint_tickers and subject_type in {"company", "index", "crypto", "fund"} and len(scoped_current_tickers) == 1:
            hint_tickers = [scoped_current_tickers[0]]
        if (
            decision.context_binding.source
            in {"active_symbol", "last_turn", "recent_focus", "last_report", "unresolved_clarification"}
            and scoped_current_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
        ):
            if hint_tickers:
                scoped = [ticker for ticker in hint_tickers if ticker in set(scoped_current_tickers)]
                if not scoped:
                    continue
                hint_tickers = scoped
            else:
                hint_tickers = list(scoped_current_tickers)

        if (
            operation_name == "qa"
            and decision.needs_tools
            and hint_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
        ):
            projected_operation = _domain_intent_operation(decision.domain_intent, decision.confidence)
            projected_name = str(projected_operation.get("name") or "").strip().lower()
            if projected_name and projected_name != "qa":
                operation_name = projected_name
            elif decision.domain_intent == "analysis":
                operation_name = str(_router_guided_analysis_operation(decision).get("name") or "qa").strip().lower()

        params = dict(hint.get("params") or {}) if isinstance(hint.get("params"), dict) else {}
        if (
            operation_name in _ROUTER_GENERIC_COMPANY_OPERATIONS
            and hint_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
        ):
            fallback_operations = _company_operations(
                query,
                tickers=dedup_tickers(hint_tickers),
                output_mode=output_mode,
            )
            specific_operations = _specific_company_operations(fallback_operations)
            if specific_operations:
                selected_operation = specific_operations[0]
                operation_name = str(selected_operation.get("name") or operation_name).strip().lower()
                selected_params = dict(selected_operation.get("params") or {})
                selected_params.update(params)
                params = selected_params
        if operation_name == "fetch" and not params.get("topic"):
            params["topic"] = "news"
        if operation_name in {"fetch", "news_impact", "daily_brief"} and query_explicitly_requests_links(query):
            params.setdefault("include_links", True)
        if subject_type == "unknown" and _contains_any(f"{subject_label} {query}", _THEME_HINTS):
            subject_type = "theme"
        if decision.context_binding.source != "none":
            params.setdefault("context_binding", decision.context_binding.model_dump())
        task_selection_ids = list(selection_ids or []) if subject_type in {"news_item", "news_set", "filing", "research_doc"} else []
        task_selection_types = list(selection_types or []) if task_selection_ids else []

        if (
            operation_name == "fetch"
            and decision.domain_intent == "analysis"
            and hint_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
        ):
            for ticker in dedup_tickers(hint_tickers):
                _add_support_task(
                    ticker=ticker,
                    subject_type=subject_type,
                    operation_name="price",
                    params={},
                    priority=15,
                )
                added = True

        if (
            operation_name == "price"
            and hint_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
            and query_explicitly_requests_links(query)
            and _contains_any(query, _NEWS_HINTS)
        ):
            for ticker in dedup_tickers(hint_tickers):
                _add_support_task(
                    ticker=ticker,
                    subject_type=subject_type,
                    operation_name="fetch",
                    params={"topic": "news", "include_links": True},
                    priority=16,
                )
                added = True

        if (
            operation_name in {"analyze_impact", "news_impact", "daily_brief"}
            and hint_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
        ):
            for ticker in dedup_tickers(hint_tickers):
                _add_support_task(
                    ticker=ticker,
                    subject_type=subject_type,
                    operation_name="price",
                    params={},
                    priority=15,
                )
                _add_support_task(
                    ticker=ticker,
                    subject_type=subject_type,
                    operation_name="fetch",
                    params={"topic": "news"},
                    priority=16,
                )
                added = True

        if operation_name == "compare" and len(hint_tickers) >= 2:
            aspects = {
                str(item).strip().lower()
                for item in (params.get("aspects") if isinstance(params.get("aspects"), list) else [])
                if str(item).strip()
            }
            wants_price = not aspects or bool(aspects & {"price", "quote", "price_change", "change", "涨跌幅", "价格"})
            wants_news = not aspects or bool(aspects & {"news", "headline", "latest_news", "新闻", "消息"})
            for ticker in dedup_tickers(hint_tickers):
                if wants_price:
                    _add_support_task(
                        ticker=ticker,
                        subject_type=subject_type,
                        operation_name="price",
                        params={},
                        priority=15,
                    )
                    added = True
                if wants_news:
                    _add_support_task(
                        ticker=ticker,
                        subject_type=subject_type,
                        operation_name="fetch",
                        params={"topic": "news"},
                        priority=16,
                    )
                    added = True

        atomic_tickers = dedup_tickers(hint_tickers)
        if (
            operation_name in {"price", "technical"}
            and len(atomic_tickers) > 1
            and subject_type in {"company", "index", "crypto", "fund"}
        ):
            for ticker in atomic_tickers:
                _add_task(
                    tasks,
                    subject_type=subject_type,
                    subject_label=ticker,
                    operation=_operation(operation_name, max(decision.confidence, 0.68), params),
                    query=query,
                    tickers=[ticker],
                    selection_ids=task_selection_ids,
                    selection_types=task_selection_types,
                    priority=18 + idx,
                    reason="conversation_router_task_hint",
                    params=params,
                )
            added = True
            continue

        if (
            atomic_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
            and all(_has_task(operation_name, ticker) for ticker in atomic_tickers)
        ):
            continue

        _add_task(
            tasks,
            subject_type=subject_type,
            subject_label=subject_label or ", ".join(hint_tickers) or subject_type,
            operation=_operation(operation_name, max(decision.confidence, 0.68), params),
            query=query,
            tickers=atomic_tickers,
            selection_ids=task_selection_ids,
            selection_types=task_selection_types,
            priority=18 + idx,
            reason="conversation_router_task_hint",
            params=params,
        )
        added = True

    if added:
        context_refs.append(
            {
                "source": "conversation_router",
                "key": "task_hints",
                "label": "LLM拆分的原子请求",
                "value": len([hint for hint in (decision.task_hints or ()) if isinstance(hint, dict)]),
            }
        )
    return added

def _add_router_task_hints_contract(
    *,
    tasks: list[dict[str, Any]],
    context_refs: list[dict[str, Any]],
    decision: ConversationDecision,
    query: str,
    output_mode: str = "chat",
    current_tickers: list[str],
    selection_ids: list[str] | None = None,
    selection_types: list[str] | None = None,
    intent_contracts: list[dict[str, Any]] | None = None,
    request_frames: list[dict[str, Any]] | None = None,
    project_residual_hints: bool = False,
) -> bool:
    """Compile router hint frames through the evidence-first intent contract."""
    added = False
    bound_tickers: list[str] = []
    if decision.context_binding.source != "selection":
        for task in tasks:
            raw_tickers = task.get("tickers")
            if isinstance(raw_tickers, list):
                bound_tickers.extend(normalize_ticker(str(ticker)) for ticker in raw_tickers if str(ticker).strip())
    scoped_current_tickers = dedup_tickers(list(current_tickers or []) + bound_tickers)

    def _hint_domain_intent(operation_name: str) -> str:
        if operation_name == "price":
            return "quote"
        if operation_name in {"fetch", "daily_brief", "news_impact"}:
            return "news"
        if operation_name == "technical":
            return "technical"
        if operation_name == "investment_opinion":
            return "investment_opinion"
        if operation_name == "holdings":
            return "holdings"
        if operation_name in {"macro_brief", "fact_check"}:
            return "macro"
        return decision.domain_intent

    def _add_projected_task(
        *,
        contract: dict[str, Any],
        subject_type: str,
        subject_label: str,
        tickers: list[str],
        priority: int,
        params: dict[str, Any] | None = None,
        task_selection_ids: list[str] | None = None,
        task_selection_types: list[str] | None = None,
    ) -> None:
        operation = legacy_operation_for_contract(contract, subject_type=subject_type)
        op_params = dict(operation.get("params") or {})
        if params:
            op_params.update(params)
        operation = {**operation, "params": op_params}
        _add_task(
            tasks,
            subject_type=subject_type,
            subject_label=subject_label or ", ".join(tickers) or subject_type,
            operation=operation,
            query=query,
            tickers=tickers,
            selection_ids=task_selection_ids,
            selection_types=task_selection_types,
            priority=priority,
            reason="intent_contract_projection",
            params=op_params,
        )

    def _add_news_support_from_contract(
        *,
        tickers: list[str],
        subject_type: str,
        subject_label: str,
        priority: int,
        frame_id: str,
        task_selection_ids: list[str] | None = None,
        task_selection_types: list[str] | None = None,
    ) -> None:
        news_contract = derive_intent_contract(
            query=query,
            tickers=tickers,
            output_mode=output_mode,
            comparison_requested=False,
            domain_intent="news",
            subject_type=subject_type,
            frame_id=frame_id,
        )
        if intent_contracts is not None:
            intent_contracts.append(dict(news_contract))
        if request_frames is not None:
            request_frames.append(
                compile_request_frame(
                    query=query,
                    tickers=tickers,
                    output_mode=output_mode,
                    comparison_requested=False,
                    domain_intent="news",
                    subject_type=subject_type,
                    frame_id=frame_id,
                )
            )
        news_params: dict[str, Any] = {"topic": "news"}
        if query_explicitly_requests_links(query):
            news_params["include_links"] = True
        _add_projected_task(
            contract=news_contract,
            subject_type=subject_type,
            subject_label=subject_label,
            tickers=tickers,
            priority=priority,
            params=news_params,
            task_selection_ids=task_selection_ids,
            task_selection_types=task_selection_types,
        )

    router_compare_requested = bool(
        len(scoped_current_tickers) >= 2
        and (decision.relation == "compare" or _explicit_multi_ticker_compare_requested(query))
    )
    if router_compare_requested:
        first_hint = next((hint for hint in (decision.task_hints or ()) if isinstance(hint, dict)), {})
        subject_type = str(first_hint.get("subject_type") or "company").strip().lower()
        subject_label = str(first_hint.get("subject_label") or ", ".join(scoped_current_tickers)).strip()
        contract = derive_intent_contract(
            query=query,
            tickers=scoped_current_tickers,
            output_mode=output_mode,
            comparison_requested=True,
            domain_intent=decision.domain_intent,
            subject_type=subject_type,
            frame_id="router_compare",
        )
        if intent_contracts is not None:
            intent_contracts.append(dict(contract))
        if request_frames is not None:
            request_frames.append(
                compile_request_frame(
                    query=query,
                    tickers=scoped_current_tickers,
                    output_mode=output_mode,
                    comparison_requested=True,
                    domain_intent=decision.domain_intent,
                    subject_type=subject_type,
                    frame_id="router_compare",
                )
            )
        contract_tickers = list(contract.get("primary_tickers") or scoped_current_tickers)
        if requires_per_ticker_research(contract):
            compare_operation = synthesis_compare_operation(contract)
            _add_task(
                tasks,
                subject_type=subject_type,
                subject_label=subject_label or ", ".join(contract_tickers),
                operation=compare_operation,
                query=query,
                tickers=contract_tickers,
                priority=18,
                reason="intent_contract_synthesis_compare",
                params=dict(compare_operation.get("params") or {}),
            )
            _add_per_ticker_company_tasks(
                tasks,
                tickers=contract_tickers,
                operations=[evidence_focused_operation(contract)],
                query=query,
                priority=22,
                reason="intent_contract_per_ticker_evidence",
            )
        else:
            _add_projected_task(
                contract=contract,
                subject_type=subject_type,
                subject_label=subject_label or ", ".join(contract_tickers),
                tickers=contract_tickers,
                priority=18,
            )
        context_refs.append(
            {
                "source": "conversation_router",
                "key": "task_hints",
                "label": "router compare frame compiled through intent_contract",
                "value": len([hint for hint in (decision.task_hints or ()) if isinstance(hint, dict)]),
            }
        )
        if not project_residual_hints:
            return True
        # WP2-T11 修复：compare 早退曾把 router 的非公司 hints（macro/theme 等）整体丢弃；
        # 旧路径靠关键词瀑布事后加塞掩盖，新意图管线无瀑布，需在此续投残余 hints。
        added = True
        hints_to_project = [
            hint
            for hint in (decision.task_hints or ())
            if isinstance(hint, dict)
            and str(hint.get("subject_type") or "").strip().lower()
            not in {"company", "index", "crypto", "fund"}
        ]
    else:
        hints_to_project = list(decision.task_hints or ())

    for idx, hint in enumerate(hints_to_project, 1):
        if not isinstance(hint, dict):
            continue
        operation_name = str(hint.get("operation") or "qa").strip().lower()
        if operation_name == "alert_set":
            continue
        subject_type = str(hint.get("subject_type") or "unknown").strip().lower()
        subject_label = str(hint.get("subject_label") or "").strip()
        hint_tickers = [
            normalize_ticker(str(ticker))
            for ticker in (hint.get("tickers") if isinstance(hint.get("tickers"), list) else [])
            if str(ticker).strip()
        ]
        if not hint_tickers and subject_label:
            hint_tickers = [
                normalize_ticker(str(ticker))
                for ticker in (extract_tickers(subject_label).get("tickers") or [])
                if str(ticker).strip()
            ]
        if not hint_tickers and subject_type in {"company", "index", "crypto", "fund"} and len(scoped_current_tickers) == 1:
            hint_tickers = [scoped_current_tickers[0]]
        if (
            decision.context_binding.source
            in {"active_symbol", "last_turn", "recent_focus", "last_report", "unresolved_clarification"}
            and scoped_current_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
        ):
            if hint_tickers:
                scoped = [ticker for ticker in hint_tickers if ticker in set(scoped_current_tickers)]
                if not scoped:
                    continue
                hint_tickers = scoped
            else:
                hint_tickers = list(scoped_current_tickers)

        params = dict(hint.get("params") or {}) if isinstance(hint.get("params"), dict) else {}
        if operation_name == "fetch" and not params.get("topic"):
            params["topic"] = "news"
        if operation_name in {"fetch", "news_impact", "daily_brief"} and query_explicitly_requests_links(query):
            params.setdefault("include_links", True)
        if subject_type == "unknown" and _contains_any(f"{subject_label} {query}", _THEME_HINTS):
            subject_type = "theme"
        if decision.context_binding.source != "none":
            params.setdefault("context_binding", decision.context_binding.model_dump())

        task_selection_ids = list(selection_ids or []) if subject_type in {"news_item", "news_set", "filing", "research_doc"} else []
        task_selection_types = list(selection_types or []) if task_selection_ids else []
        atomic_tickers = dedup_tickers(hint_tickers)
        comparison_requested = bool(
            len(atomic_tickers) >= 2
            and (
                operation_name == "compare"
                or decision.relation == "compare"
                or _explicit_multi_ticker_compare_requested(query)
            )
        )
        frame_query = _router_hint_frame_query(
            query=query,
            subject_type=subject_type,
            subject_label=subject_label,
            tickers=atomic_tickers,
            params=params,
            operation_name=operation_name,
            comparison_requested=comparison_requested,
        )
        contract = derive_intent_contract(
            query=frame_query,
            tickers=atomic_tickers,
            output_mode=output_mode,
            comparison_requested=comparison_requested,
            domain_intent=decision.domain_intent,
            subject_type=subject_type,
            frame_id=f"router_hint_{idx}",
        )
        contract_domain_intent = decision.domain_intent
        if not contract.get("required_evidence") and operation_name not in {"qa", "compare"}:
            contract_domain_intent = _hint_domain_intent(operation_name)
            contract = derive_intent_contract(
                query=frame_query,
                tickers=atomic_tickers,
                output_mode=output_mode,
                comparison_requested=comparison_requested,
                domain_intent=contract_domain_intent,
                subject_type=subject_type,
                frame_id=f"router_hint_{idx}",
            )
        if intent_contracts is not None:
            intent_contracts.append(dict(contract))

        if comparison_requested and requires_per_ticker_research(contract):
            contract_tickers = list(contract.get("primary_tickers") or atomic_tickers)
            compare_operation = synthesis_compare_operation(contract)
            _add_task(
                tasks,
                subject_type=subject_type,
                subject_label=subject_label or ", ".join(contract_tickers),
                operation=compare_operation,
                query=query,
                tickers=contract_tickers,
                priority=18 + idx,
                reason="intent_contract_synthesis_compare",
                params=dict(compare_operation.get("params") or {}),
            )
            _add_per_ticker_company_tasks(
                tasks,
                tickers=contract_tickers,
                operations=[evidence_focused_operation(contract)],
                query=query,
                priority=22 + idx,
                reason="intent_contract_per_ticker_evidence",
            )
            added = True
            continue

        if len(atomic_tickers) > 1 and subject_type in {"company", "index", "crypto", "fund"} and not comparison_requested:
            for ticker in atomic_tickers:
                single_domain_intent = decision.domain_intent
                single_contract = derive_intent_contract(
                    query=frame_query,
                    tickers=[ticker],
                    output_mode=output_mode,
                    comparison_requested=False,
                    domain_intent=decision.domain_intent,
                    subject_type=subject_type,
                    frame_id=f"router_hint_{idx}_{ticker}",
                )
                if not single_contract.get("required_evidence") and operation_name not in {"qa", "compare"}:
                    single_domain_intent = _hint_domain_intent(operation_name)
                    single_contract = derive_intent_contract(
                        query=frame_query,
                        tickers=[ticker],
                        output_mode=output_mode,
                        comparison_requested=False,
                        domain_intent=single_domain_intent,
                        subject_type=subject_type,
                        frame_id=f"router_hint_{idx}_{ticker}",
                    )
                if intent_contracts is not None:
                    intent_contracts.append(dict(single_contract))
                if request_frames is not None:
                    request_frames.append(
                        compile_request_frame(
                            query=frame_query,
                            tickers=[ticker],
                            output_mode=output_mode,
                            comparison_requested=False,
                            domain_intent=single_domain_intent,
                            subject_type=subject_type,
                            frame_id=f"router_hint_{idx}_{ticker}",
                        )
                    )
                _add_projected_task(
                    contract=single_contract,
                    subject_type=subject_type,
                    subject_label=ticker,
                    tickers=[ticker],
                    priority=18 + idx,
                    params=params,
                    task_selection_ids=task_selection_ids,
                    task_selection_types=task_selection_types,
                )
                if (
                    operation_name == "price"
                    and query_explicitly_requests_links(query)
                    and _contains_any(query, _NEWS_HINTS)
                ):
                    _add_news_support_from_contract(
                        tickers=[ticker],
                        subject_type=subject_type,
                        subject_label=ticker,
                        priority=19 + idx,
                        frame_id=f"router_hint_{idx}_{ticker}_news",
                        task_selection_ids=task_selection_ids,
                        task_selection_types=task_selection_types,
                    )
            added = True
            continue

        if request_frames is not None:
            request_frames.append(
                compile_request_frame(
                    query=frame_query,
                    tickers=atomic_tickers,
                    output_mode=output_mode,
                    comparison_requested=comparison_requested,
                    domain_intent=contract_domain_intent,
                    subject_type=subject_type,
                    frame_id=f"router_hint_{idx}",
                )
            )
        _add_projected_task(
            contract=contract,
            subject_type=subject_type,
            subject_label=subject_label or ", ".join(atomic_tickers) or subject_type,
            tickers=atomic_tickers,
            priority=18 + idx,
            params=params,
            task_selection_ids=task_selection_ids,
            task_selection_types=task_selection_types,
        )
        if (
            operation_name == "price"
            and atomic_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
            and query_explicitly_requests_links(query)
            and _contains_any(query, _NEWS_HINTS)
        ):
            _add_news_support_from_contract(
                tickers=atomic_tickers,
                subject_type=subject_type,
                subject_label=subject_label or ", ".join(atomic_tickers),
                priority=19 + idx,
                frame_id=f"router_hint_{idx}_news",
                task_selection_ids=task_selection_ids,
                task_selection_types=task_selection_types,
            )
        added = True

    if added:
        context_refs.append(
            {
                "source": "conversation_router",
                "key": "task_hints",
                "label": "router frames compiled through intent_contract",
                "value": len([hint for hint in (decision.task_hints or ()) if isinstance(hint, dict)]),
            }
        )
    return added

def _prune_url_only_company_context_tasks(
    tasks: list[dict[str, Any]],
    *,
    query: str,
    explicit_urls: list[str],
) -> list[dict[str, Any]]:
    """Keep explicit URL reading focused on the URL unless side data was requested."""
    if not explicit_urls or _query_requests_company_side_data(query):
        return tasks
    has_url_task = any(
        isinstance((task.get("operation") or {}).get("params"), dict)
        and (
            (task.get("operation") or {}).get("params", {}).get("url")
            or (task.get("operation") or {}).get("params", {}).get("urls")
        )
        for task in tasks
        if isinstance(task, dict)
    )
    if not has_url_task:
        return tasks
    pruned: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        op_name = str((task.get("operation") or {}).get("name") or "").strip()
        subject_type = str(task.get("subject_type") or "").strip().lower()
        reason = str(task.get("reason") or "").strip()
        if (
            reason == "conversation_router_intent"
            and subject_type in {"company", "index", "crypto", "fund"}
            and op_name in {"qa", "daily_brief", "fetch", "analyze_impact", "news_impact"}
        ):
            continue
        pruned.append(task)
    return pruned

def _sanitize_blocked_task_questions(query: str, blocked_tasks: list[dict[str, Any]]) -> None:
    for task in blocked_tasks:
        if not isinstance(task, dict):
            continue
        task["question"] = _natural_clarify_question(query, str(task.get("question") or ""))

def _add_task(
    tasks: list[dict[str, Any]],
    *,
    subject_type: str,
    operation: dict[str, Any],
    query: str,
    tickers: list[str] | None = None,
    subject_label: str = "",
    selection_ids: list[str] | None = None,
    selection_types: list[str] | None = None,
    priority: int = 50,
    reason: str = "rule_match",
    constraints: list[str] | None = None,
    params: dict[str, Any] | None = None,
) -> None:
    task_id = f"task_{len(tasks) + 1}"
    tasks.append(
        {
            "id": task_id,
            "subject_type": subject_type,
            "subject_label": subject_label,
            "tickers": tickers or [],
            "selection_ids": selection_ids or [],
            "selection_types": selection_types or [],
            "operation": operation,
            "time_scope": _time_scope(query),
            "priority": priority,
            "status": "ready",
            "reason": reason,
            "constraints": constraints or [],
            "params": params or {},
        }
    )

def _add_holdings_intent_tasks(
    tasks: list[dict[str, Any]],
    *,
    query: str,
    tickers: list[str],
    ui_context: dict[str, Any],
) -> bool:
    if not _has_holdings_intent(query):
        return False

    params = _holdings_intent_params(query)
    operation = _operation("holdings", 0.84, params)
    if _holdings_portfolio_context_available(query, ui_context, tickers):
        portfolio_tickers = tickers or _portfolio_tickers_from_context(ui_context)
        _add_task(
            tasks,
            subject_type="portfolio",
            subject_label="当前组合",
            operation=operation,
            query=query,
            tickers=portfolio_tickers,
            priority=18,
            reason="holdings_intent_portfolio",
            params={**params, "positions": _positions_from_ui_context(ui_context)},
        )
        return True

    if tickers:
        for ticker in tickers[:6]:
            _add_task(
                tasks,
                subject_type=_subject_type_for_ticker(ticker),
                subject_label=ticker,
                operation=operation,
                query=query,
                tickers=[ticker],
                priority=20,
                reason="holdings_intent_company",
                params=params,
            )
        return True

    holder = params.get("holder_cik_or_name")
    if holder:
        _add_task(
            tasks,
            subject_type="company",
            subject_label=str(holder),
            operation=operation,
            query=query,
            tickers=[],
            priority=20,
            reason="holdings_intent_institution",
            params=params,
        )
        return True

    return False

def _add_context_bound_research_task(
    *,
    tasks: list[dict[str, Any]],
    context_refs: list[dict[str, Any]],
    decision: ConversationDecision,
    query: str,
    ui_context: dict[str, Any],
    memory_context: dict[str, Any],
    current_tickers: list[str] | None,
    selection_ids: list[str],
    selection_types: list[str],
) -> bool:
    """Map a contextual router decision into executable work.

    The switch is by context source, not by bespoke follow-up kind. A follow-up
    can bind to a report, active symbol, selected document, portfolio, or recent
    focus while still sharing one route schema.
    """
    binding = decision.context_binding
    source = binding.source

    if source == "selection" and selection_ids:
        subject_type = _selection_subject_type(selection_types)
        if subject_type == "research_doc" and decision.domain_intent == "news":
            subject_type = "news_item" if len(selection_ids) == 1 else "news_set"
        operation_name = "summarize" if decision.relation == "summarize" else "qa"
        if decision.domain_intent in {"news", "analysis"} and decision.relation != "summarize":
            operation_name = "analyze_impact" if decision.needs_tools else "qa"
        params = {"context_binding": binding.model_dump()}
        urls = _selection_urls(ui_context)
        if len(urls) == 1:
            params["url"] = urls[0]
        elif len(urls) > 1:
            params["urls"] = urls
        selection_tickers = dedup_tickers(list(current_tickers or []))
        if not selection_tickers and isinstance(ui_context.get("active_symbol"), str):
            active = normalize_ticker(str(ui_context.get("active_symbol") or ""))
            if active:
                selection_tickers = [active]
        _add_task(
            tasks,
            subject_type=subject_type,
            operation=_operation(operation_name, decision.confidence, params),
            query=query,
            tickers=selection_tickers,
            selection_ids=selection_ids,
            selection_types=selection_types,
            priority=15,
            reason="context_router_binding",
            params=params,
        )
        context_refs.append(_binding_context_ref(binding, value=selection_ids))
        return True

    if source == "portfolio":
        portfolio_tickers = _portfolio_tickers_from_context(ui_context)
        positions = _positions_from_ui_context(ui_context)
        if portfolio_tickers or _portfolio_context_available(query, ui_context):
            _add_task(
                tasks,
                subject_type="portfolio",
                subject_label="当前持仓",
                operation=_domain_intent_operation(decision.domain_intent, decision.confidence),
                query=query,
                tickers=portfolio_tickers,
                priority=20,
                reason="context_router_binding",
                params={"context_binding": binding.model_dump(), "positions": positions},
            )
            context_refs.append(_binding_context_ref(binding, value=portfolio_tickers or "portfolio"))
            return True
        return False

    tickers = _context_tickers_from_binding(
        binding=binding,
        ui_context=ui_context,
        memory_context=memory_context,
    )
    if tickers:
        for ticker in tickers[:3]:
            _add_task(
                tasks,
                subject_type=_subject_type_for_ticker(ticker),
                operation=_domain_intent_operation(decision.domain_intent, decision.confidence),
                query=query,
                tickers=[ticker],
                subject_label=ticker,
                priority=25,
                reason="context_router_binding",
                params={"context_binding": binding.model_dump()},
            )
        context_refs.append(_binding_context_ref(binding, value=tickers))
        return True

    return False

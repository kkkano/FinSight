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
from backend.graph.intent.direct_reply import (
    _context_router_clarify_block,
    _direct_conversation_result,
    _direct_reply,
    _social_prefix,
)
from backend.graph.intent.operations import (
    _company_operations,
    _domain_intent_operation,
    _macro_operation,
    _macro_subject_label,
    _operation,
    _operation_with_report_peers,
    _router_directed_company_operations,
)
from backend.graph.intent.predicates import (
    _binding_context_ref,
    _build_subject,
    _can_use_active_symbol_fallback,
    _contains_any,
    _direct_decision_must_project_tasks,
    _explicit_multi_ticker_compare_requested,
    _explicit_report_mode,
    _extract_urls,
    _force_grounded_research_decision,
    _has_prior_dialogue,
    _history_tickers_from_messages,
    _is_explicit_brief_request,
    _is_lightweight_representative_compare,
    _normalize_selection,
    _portfolio_context_available,
    _portfolio_tickers_from_context,
    _positions_from_ui_context,
    _query_can_fallback_to_direct_finance_answer,
    _query_requests_company_side_data,
    _request_frame_is_authoritative_direct_answer,
    _request_frame_requires_execution,
    _selection_subject_type,
    _split_primary_report_tickers,
    _strip_urls,
    _subject_type_for_ticker,
)
from backend.graph.intent.task_builders import (
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
    _sanitize_blocked_task_questions,
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




async def _emit_understanding_trace(understanding: dict[str, Any]) -> None:
    await emit_event(
        {
            "type": "trace",
            "visibility": "user",
            "stage": "understanding",
            "status": "done",
            "title": "已理解请求",
            "summary": understanding.get("user_visible_summary") or "",
            "tasks": [
                {
                    "id": task.get("id"),
                    "subject_type": task.get("subject_type"),
                    "tickers": task.get("tickers") or [],
                    "operation": (task.get("operation") or {}).get("name"),
                    "time_scope": (task.get("time_scope") or {}).get("kind"),
                }
                for task in (understanding.get("tasks") or [])[:8]
            ],
            "blocked_tasks": [
                {"id": task.get("id"), "reason": task.get("reason")}
                for task in (understanding.get("blocked_tasks") or [])[:4]
            ],
        }
    )

async def _legacy_understand_request(state: GraphState) -> dict[str, Any]:
    query = (state.get("query") or "").strip()
    ui_context = dict(state.get("ui_context") or {}) if isinstance(state.get("ui_context"), dict) else {}
    output_mode = (decide_output_mode(state).get("output_mode") or "chat")

    tasks: list[dict[str, Any]] = []
    blocked_tasks: list[dict[str, Any]] = []
    context_refs: list[dict[str, Any]] = []
    fallback_assumptions: list[str] = []
    memory_context = state.get("memory_context") if isinstance(state.get("memory_context"), dict) else {}
    artifacts = dict(state.get("artifacts") or {})
    state = {**state, "ui_context": ui_context, "artifacts": artifacts}
    trace = dict(state.get("trace") or {})
    selection_ids, selection_types, selection_payload = _normalize_selection(ui_context)
    social_prefix = _social_prefix(query)
    query_for_tickers = _strip_urls(query)
    ticker_meta = extract_tickers(query_for_tickers)
    tickers = dedup_tickers(
        [str(t) for t in (ticker_meta.get("tickers") or []) if str(t).strip().upper() not in _NON_ASSET_TOKENS]
    )
    conversation_decision: ConversationDecision | None = None
    contract_mode = intent_contract_mode()
    contract_enforced = contract_mode == "enforce"
    contract_shadow = contract_mode == "shadow"
    intent_contract: dict[str, Any] | None = None
    intent_contracts: list[dict[str, Any]] = []
    context_router_research_bound = False
    request_frames: list[dict[str, Any]] = []
    compiled_request_frame: dict[str, Any] = (
        compile_request_frame(
            query=query,
            tickers=tickers,
            output_mode=output_mode,
            subject_type="company",
            frame_id="primary_request",
        )
        if query
        else {}
    )
    request_frame: dict[str, Any] = compiled_request_frame if contract_enforced else {}
    if compiled_request_frame and contract_shadow:
        trace["request_frame_shadow"] = compiled_request_frame
    if request_frame:
        trace["request_frame"] = request_frame
    deterministic_request_frames = (
        compile_request_frames(
            query=query,
            tickers=tickers,
            output_mode=output_mode,
        )
        if query
        else []
    )
    if deterministic_request_frames and contract_shadow:
        trace["request_frames_shadow"] = deterministic_request_frames
    if not contract_enforced:
        deterministic_request_frames = []

    if not query:
        blocked_tasks.append(
            {
                "id": "blocked_1",
                "subject_type": "unknown",
                "subject_label": "",
                "operation": _operation("qa", 0.0),
                "reason": "empty_query",
                "question": "请先输入你的问题。",
                "suggestions": ["输入股票代码、公司名称、宏观主题，或选择新闻/财报后提问"],
                "fallback_allowed": False,
            }
        )

    workflow_action = request_frame.get("workflow_action") if isinstance(request_frame, dict) else None
    if (
        query
        and not blocked_tasks
        and isinstance(workflow_action, dict)
        and workflow_action.get("name") == "backtest"
    ):
        slots = workflow_action.get("slots") if isinstance(workflow_action.get("slots"), dict) else {}
        action_ticker = normalize_ticker(str(slots.get("ticker") or (tickers[0] if tickers else "")))
        operation = dict(request_frame.get("legacy_operation") or _operation("backtest", 0.9))
        params = dict(operation.get("params") or {})
        operation["params"] = params
        _add_task(
            tasks,
            subject_type="company",
            subject_label=action_ticker,
            operation=operation,
            query=query,
            tickers=[action_ticker] if action_ticker else [],
            priority=8,
            reason="request_frame_action",
            params=params,
        )
        conversation_decision = ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint=action_ticker),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.9,
            needs_tools=True,
            reason="request_frame workflow action requires deterministic execution",
        )
        trace["conversation_router"] = conversation_decision.model_dump()
        context_router_research_bound = True
        request_frames.append(request_frame)

    if query and not blocked_tasks and is_casual_chat(query):
        # Keep this local path only for obvious social turns. Broader open-chat
        # questions still go through the LLM router before planner.
        decision = ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(),
            relation="new_topic",
            domain_intent="smalltalk",
            confidence=1.0,
            needs_tools=False,
            reason="纯社交问候，直接回答",
        )
        result = _direct_conversation_result(
            query=query,
            output_mode=output_mode,
            decision=decision,
            reply=_direct_reply(query),
            context_refs=context_refs,
            artifacts=artifacts,
            trace=trace,
            memory_context=memory_context,
            request_frame=request_frame,
        )
        await _emit_understanding_trace(result["understanding"])
        return result

    if (
        query
        and not blocked_tasks
        and not _explicit_report_mode(state, output_mode)
        and (output_mode == "brief" or _is_explicit_brief_request(query) or bool(_extract_urls(query)))
        and tickers
        and not selection_ids
        and not _has_prior_dialogue(state, query)
    ):
        conversation_decision = ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(
                source="none",
                confidence=0.0,
                reason="brief turn has explicit current-turn subject and no prior context to bind",
                subject_hint=", ".join(tickers[:3]),
            ),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.72,
            needs_tools=True,
            reason="explicit brief request can be decomposed by request understanding without context binding",
        )
        trace["conversation_router"] = conversation_decision.model_dump()

    explicit_urls = _extract_urls(query)
    if (
        query
        and explicit_urls
        and not blocked_tasks
        and not _explicit_report_mode(state, output_mode)
        and conversation_decision is None
    ):
        conversation_decision = ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(
                source="none",
                confidence=0.0,
                reason="current user turn contains explicit URL(s), so the URL must be fetched before answering",
                subject_hint=explicit_urls[0],
            ),
            relation="new_topic",
            domain_intent="doc_qa",
            confidence=0.9,
            needs_tools=True,
            reason="explicit URL reference requires source-grounded document retrieval",
        )
        trace["conversation_router"] = conversation_decision.model_dump()

    if query and not blocked_tasks and not _explicit_report_mode(state, output_mode) and conversation_decision is None:
        conversation_decision = await route_conversation(state, tickers=tickers, selection_ids=selection_ids)
        if conversation_decision is not None:
            if tickers and conversation_decision.context_binding.source == "none":
                tickers = _effective_current_turn_tickers(query, tickers, conversation_decision)
            trace["conversation_router"] = conversation_decision.model_dump()
            if conversation_decision.execution_route in {"direct_answer", "out_of_scope"}:
                if _direct_decision_must_project_tasks(query, conversation_decision, current_tickers=tickers, request_frame=request_frame):
                    conversation_decision = _force_grounded_research_decision(conversation_decision)
                    trace["conversation_router"] = conversation_decision.model_dump()
                else:
                    direct_context_refs = list(context_refs)
                    binding = conversation_decision.context_binding
                    if binding.source != "none":
                        direct_context_refs.append(
                            {
                                "source": "conversation_context",
                                "key": binding.source,
                                "label": binding.subject_hint or binding.source,
                                "value": binding.reason,
                            }
                        )
                    reply = await generate_contextual_reply(state, conversation_decision)
                    result = _direct_conversation_result(
                        query=query,
                        output_mode=output_mode,
                        decision=conversation_decision,
                        reply=reply,
                        context_refs=direct_context_refs,
                        artifacts=artifacts,
                        trace=trace,
                        memory_context=memory_context,
                        request_frame=request_frame,
                    )
                    await _emit_understanding_trace(result["understanding"])
                    return result
            if (
                conversation_decision.execution_route == "research"
            ):
                if conversation_decision.context_binding.source != "none":
                    context_router_research_bound = _add_context_bound_research_task(
                        tasks=tasks,
                        context_refs=context_refs,
                        decision=conversation_decision,
                        query=query,
                        ui_context=ui_context,
                        memory_context=memory_context,
                        current_tickers=tickers,
                        selection_ids=selection_ids,
                        selection_types=selection_types,
                    )
                if conversation_decision.task_hints:
                    if contract_enforced:
                        hint_bound = _add_router_task_hints_contract(
                            tasks=tasks,
                            context_refs=context_refs,
                            decision=conversation_decision,
                            query=query,
                            output_mode=output_mode,
                            current_tickers=tickers,
                            selection_ids=selection_ids,
                            selection_types=selection_types,
                            intent_contracts=intent_contracts,
                            request_frames=request_frames,
                        )
                    else:
                        hint_bound = _add_router_task_hints(
                            tasks=tasks,
                            context_refs=context_refs,
                            decision=conversation_decision,
                            query=query,
                            current_tickers=tickers,
                            output_mode=output_mode,
                            selection_ids=selection_ids,
                            selection_types=selection_types,
                        )
                    context_router_research_bound = context_router_research_bound or hint_bound
                    if contract_enforced and request_frames:
                        request_frame = request_frames[0]
            if conversation_decision.execution_route == "clarify":
                blocked_tasks.append(_context_router_clarify_block(conversation_decision))
                tickers = []
                selection_ids = []

    context_binding_source = (
        conversation_decision.context_binding.source
        if conversation_decision is not None
        else "none"
    )

    if contract_enforced and not request_frames and deterministic_request_frames:
        request_frames.extend(deterministic_request_frames)
        request_frame = request_frames[0]
        trace["request_frame"] = request_frame
        trace["request_frames"] = request_frames

    if not blocked_tasks and context_binding_source != "selection":
        _add_explicit_url_tasks(tasks=tasks, query=query, current_tickers=tickers)

    if (
        not blocked_tasks
        and
        (not context_router_research_bound or context_binding_source == "selection")
        and not tickers
        and _can_use_active_symbol_fallback(ui_context, memory_context)
        and has_financial_intent(query)
    ):
        tickers = [normalize_ticker(str(ui_context["active_symbol"]))]
        context_refs.append({"source": "ui_context", "key": "active_symbol", "label": "当前标的", "value": tickers[0]})

    # P2 weak fallback — query lacks tickers AND lacks financial intent, but
    # contains a vague subject deixis ("这只票", "this stock", ...) and
    # ui_context.active_symbol is present. Bind the active symbol and surface
    # the assumption to the user so they can correct it in one turn.
    if (
        not blocked_tasks
        and
        (not context_router_research_bound or context_binding_source == "selection")
        and
        not tickers
        and _can_use_active_symbol_fallback(ui_context, memory_context)
        and _contains_any(query, _VAGUE_SUBJECT_HINTS)
        and (
            _contains_any(query, _ASSET_DEICTIC_HINTS)
            or has_financial_intent(query)
            or _contains_any(query, _NEWS_HINTS + _PRICE_HINTS + _IMPACT_HINTS + _TECHNICAL_HINTS)
        )
    ):
        active = normalize_ticker(str(ui_context["active_symbol"]))
        if active:
            tickers = [active]
            context_refs.append(
                {
                    "source": "ui_context",
                    "key": "active_symbol",
                    "label": "当前标的(弱兜底)",
                    "value": active,
                }
            )
            fallback_assumptions.append(
                f"按你正在看的 {active} 处理，如不是请告诉我具体哪只。"
            )

    holdings_intent_handled = False
    if not blocked_tasks and (not context_router_research_bound or context_binding_source == "selection"):
        holdings_intent_handled = _add_holdings_intent_tasks(
            tasks,
            query=query,
            tickers=tickers,
            ui_context=ui_context,
        )

    if not blocked_tasks and not context_router_research_bound and selection_ids and context_binding_source != "selection":
        selection_tickers = tickers
        if (
            not selection_tickers
            and isinstance(ui_context.get("active_symbol"), str)
            and ui_context["active_symbol"].strip()
        ):
            selection_tickers = [normalize_ticker(str(ui_context["active_symbol"]))]
        subject_type = _selection_subject_type(selection_types)
        parsed = parse_operation(
            {
                "query": query,
                "subject": {
                    "subject_type": subject_type,
                    "tickers": selection_tickers,
                    "selection_ids": selection_ids,
                    "selection_types": selection_types,
                },
            }
        )
        _add_task(
            tasks,
            subject_type=subject_type,
            operation=parsed.get("operation") or _operation("summarize", 0.65),
            query=query,
            tickers=selection_tickers,
            selection_ids=selection_ids,
            selection_types=selection_types,
            priority=10,
            reason="ui_selection",
        )

    if (
        not blocked_tasks
        and not holdings_intent_handled
        and (not context_router_research_bound or context_binding_source == "selection")
        and tickers
    ):
        report_tickers, report_peer_tickers = _split_primary_report_tickers(
            query,
            tickers,
            state=state,
            output_mode=output_mode,
        )
        scoped_tickers = report_tickers or tickers
        multi_ticker_report = len(scoped_tickers) >= 2 and _explicit_report_mode(state, output_mode)
        comparison_requested = (
            _explicit_multi_ticker_compare_requested(query, scoped_tickers)
            or (
                has_comparison_relation(query, scoped_tickers)
                and not _is_lightweight_representative_compare(query)
            )
        )
        multi_ticker_compare = len(scoped_tickers) >= 2 and (
            comparison_requested
            or multi_ticker_report
        )
        company_intent_contract: dict[str, Any] | None = None
        company_request_frame: dict[str, Any] | None = None
        if contract_enforced or contract_shadow:
            company_intent_contract = derive_intent_contract(
                query=query,
                tickers=scoped_tickers,
                output_mode=output_mode,
                comparison_requested=multi_ticker_compare,
                domain_intent=(conversation_decision.domain_intent if conversation_decision is not None else ""),
                lightweight_requested=_is_explicit_brief_request(query) or _is_lightweight_representative_compare(query),
                subject_type="company",
                frame_id="primary_company",
            )
            company_request_frame = compile_request_frame(
                query=query,
                tickers=scoped_tickers,
                output_mode=output_mode,
                comparison_requested=multi_ticker_compare,
                domain_intent=(conversation_decision.domain_intent if conversation_decision is not None else ""),
                subject_type="company",
                frame_id="primary_company",
            )
            if contract_enforced:
                intent_contract = company_intent_contract
                request_frame = company_request_frame
                trace["request_frame"] = request_frame
                if not request_frames:
                    request_frames.append(request_frame)
                intent_contracts.append(dict(intent_contract))
                trace["intent_contract"] = intent_contract
            else:
                trace.setdefault("request_frame_shadow", company_request_frame)
                trace.setdefault("intent_contract_shadow", company_intent_contract)
        if multi_ticker_compare:
            contract_tickers = list(
                ((company_intent_contract or {}).get("primary_tickers") or scoped_tickers)
                if contract_enforced and isinstance(company_intent_contract, dict)
                else scoped_tickers
            )
            if contract_enforced and isinstance(company_intent_contract, dict) and requires_per_ticker_research(company_intent_contract):
                _add_task(
                    tasks,
                    subject_type="company",
                    operation=synthesis_compare_operation(company_intent_contract),
                    query=query,
                    tickers=contract_tickers,
                    priority=20,
                    reason="intent_contract_synthesis_compare",
                )
                _add_per_ticker_company_tasks(
                    tasks,
                    tickers=contract_tickers,
                    operations=[evidence_focused_operation(company_intent_contract)],
                    query=query,
                    priority=24,
                    reason="intent_contract_per_ticker_evidence",
                )
            else:
                _add_task(
                    tasks,
                    subject_type="company",
                    operation=_operation("compare", 0.86),
                    query=query,
                    tickers=contract_tickers,
                    priority=20,
                    reason="multi_ticker_report" if multi_ticker_report and not comparison_requested else "multi_ticker_compare",
                )
                extra_operations: list[dict[str, Any]] = []
                if _contains_any(query, _PRICE_HINTS) or multi_ticker_report:
                    extra_operations.append(_operation("price", 0.82))
                if _contains_any(query, _NEWS_HINTS) or multi_ticker_report:
                    extra_operations.append(_operation("fetch", 0.78, {"topic": "news"}))
                if (
                    _contains_any(query, _IMPACT_HINTS)
                    and (multi_ticker_report or len(tickers) == 1)
                    and not re.search(r"(哪个|谁).{0,8}(风险|risk)", query, re.IGNORECASE)
                ):
                    extra_operations.append(_operation("analyze_impact", 0.78))
                for ticker in contract_tickers:
                    subject_type = _subject_type_for_ticker(ticker)
                    for operation in extra_operations:
                        _add_task(
                            tasks,
                            subject_type=subject_type,
                            operation=operation,
                            query=query,
                            tickers=[ticker],
                            subject_label=ticker,
                            priority=26,
                            reason="compare_subtask",
                        )
        else:
            fallback_operations = _company_operations(
                query,
                tickers=scoped_tickers,
                allow_multi_ticker_default_compare=(
                    multi_ticker_report
                    or (
                        conversation_decision is not None
                        and conversation_decision.relation == "compare"
                    )
                ),
                output_mode=output_mode,
            )
            # skill fast path：当 _company_operations 已判定为 valuation_sanity（确定性轻量
            # 估值合理性诉求，带 return 的快路径）时，尊重该判定，不让 main 的 intent_contract
            # legacy operation（通常会泛化成 investment_opinion）覆盖它。
            fallback_primary_op = str(
                ((fallback_operations[0] if fallback_operations else None) or {}).get("name") or ""
            ).strip()
            contract_operations = (
                [legacy_operation_for_contract(company_intent_contract, subject_type="company")]
                if (
                    contract_enforced
                    and isinstance(company_intent_contract, dict)
                    and company_intent_contract.get("required_evidence")
                    and output_mode != "investment_report"
                    and fallback_primary_op != "valuation_sanity"
                )
                else []
            )
            if contract_operations:
                contract_operation_names = {
                    str(operation.get("name") or "").strip()
                    for operation in contract_operations
                    if isinstance(operation, dict)
                }
                for operation in fallback_operations:
                    op_name = str((operation or {}).get("name") or "").strip()
                    if op_name == "alert_set" and op_name not in contract_operation_names:
                        contract_operations.append(operation)
                        contract_operation_names.add(op_name)
            router_operations = None if contract_operations else _router_directed_company_operations(
                conversation_decision,
                fallback_operations=fallback_operations,
            )
            operations = [
                _operation_with_report_peers(operation, report_peer_tickers)
                for operation in (contract_operations or router_operations or fallback_operations)
            ]
            if len(scoped_tickers) >= 2 and _is_lightweight_representative_compare(query):
                _add_task(
                    tasks,
                    subject_type="company",
                    operation=_operation("qa", 0.7),
                    query=query,
                    tickers=scoped_tickers,
                    subject_label=", ".join(scoped_tickers),
                    priority=25,
                    reason="representative_basket_qa",
                )
            elif (
                router_operations is None
                and len(scoped_tickers) >= 2
                and any((operation.get("name") or "") == "compare" for operation in operations)
            ):
                _add_task(
                    tasks,
                    subject_type="company",
                    operation=_operation("compare", 0.7),
                    query=query,
                    tickers=scoped_tickers,
                    priority=25,
                    reason="multi_ticker_operation",
                )
            else:
                _add_per_ticker_company_tasks(
                    tasks,
                    tickers=scoped_tickers,
                    operations=operations,
                    query=query,
                    priority=25,
                    reason=(
                        "primary_report_ticker"
                        if report_peer_tickers
                        else ("conversation_router_intent" if router_operations else "ticker_or_alias")
                    ),
                )

    has_macro = _contains_any(query, _MACRO_HINTS)
    if not blocked_tasks and not context_router_research_bound and has_macro:
        _add_task(
            tasks,
            subject_type="macro",
            subject_label=_macro_subject_label(query),
            operation=_macro_operation(query),
            query=query,
            priority=30,
            reason="macro_hint",
        )

    url_only_doc_turn = bool(explicit_urls) and not _query_requests_company_side_data(query)
    if (
        not blocked_tasks
        and not context_router_research_bound
        and _contains_any(query, _THEME_HINTS)
        and not has_macro
        and not tickers
        and not wants_no_news_or_links(query)
        and not url_only_doc_turn
    ):
        if not any(task.get("subject_type") == "theme" for task in tasks):
            _add_task(
                tasks,
                subject_type="theme",
                subject_label=conversation_decision.context_binding.subject_hint if conversation_decision else "主题/行业",
                operation=_operation("news_impact" if _contains_any(query, _IMPACT_HINTS) else "fetch", 0.7),
                query=query,
                priority=35,
                reason="theme_hint",
            )

    has_portfolio = _contains_any(query, _PORTFOLIO_HINTS)
    if not blocked_tasks and not holdings_intent_handled and not context_router_research_bound and has_portfolio:
        if _portfolio_context_available(query, ui_context):
            portfolio_tickers = tickers or _portfolio_tickers_from_context(ui_context)
            positions = _positions_from_ui_context(ui_context)
            _add_task(
                tasks,
                subject_type="portfolio",
                subject_label="当前持仓",
                operation=_operation("rebalance_check" if "调仓" in query else "portfolio_impact", 0.74),
                query=query,
                tickers=portfolio_tickers,
                priority=40,
                reason="portfolio_context_available",
                params={"positions": positions},
            )
        elif _contains_any(query, _FALLBACK_HINTS):
            fallback_assumptions.append("用户允许在缺少持仓明细时使用查询中的替代假设。")
            _add_task(
                tasks,
                subject_type="portfolio",
                subject_label="持仓替代假设",
                operation=_operation("portfolio_fallback", 0.58),
                query=query,
                tickers=tickers,
                priority=80,
                reason="user_allowed_fallback",
                params={"fallback": True},
            )
        else:
            blocked_tasks.append(
                {
                    "id": f"blocked_{len(blocked_tasks) + 1}",
                    "subject_type": "portfolio",
                    "subject_label": "我的持仓",
                    "operation": _operation("portfolio_impact", 0.0),
                    "reason": "missing_portfolio_holdings",
                    "question": "要判断持仓影响或调仓，需要你的持仓列表、权重或允许我按假设组合估算。",
                    "suggestions": ["补充持仓和大致权重", "或说明按等权科技股组合估算"],
                    "fallback_allowed": True,
                }
            )

    if not tasks and not blocked_tasks:
        if conversation_decision is None:
            conversation_decision = await route_conversation(state, tickers=tickers, selection_ids=selection_ids)
        if conversation_decision is not None:
            trace["conversation_router"] = conversation_decision.model_dump()
            if conversation_decision.execution_route in {"direct_answer", "out_of_scope"}:
                if _direct_decision_must_project_tasks(query, conversation_decision, current_tickers=tickers, request_frame=request_frame):
                    conversation_decision = _force_grounded_research_decision(conversation_decision)
                    trace["conversation_router"] = conversation_decision.model_dump()
                else:
                    direct_context_refs = list(context_refs)
                    binding = conversation_decision.context_binding
                    if binding.source != "none":
                        direct_context_refs.append(
                            {
                                "source": "conversation_context",
                                "key": binding.source,
                                "label": binding.subject_hint or binding.source,
                                "value": binding.reason,
                            }
                        )
                    reply = await generate_contextual_reply(state, conversation_decision)
                    result = _direct_conversation_result(
                        query=query,
                        output_mode=output_mode,
                        decision=conversation_decision,
                        reply=reply,
                        context_refs=direct_context_refs,
                        artifacts=artifacts,
                        trace=trace,
                        memory_context=memory_context,
                        request_frame=request_frame,
                    )
                    await _emit_understanding_trace(result["understanding"])
                    return result
            if conversation_decision.execution_route == "research":
                if conversation_decision.task_hints:
                    if contract_enforced:
                        hint_bound = _add_router_task_hints_contract(
                            tasks=tasks,
                            context_refs=context_refs,
                            decision=conversation_decision,
                            query=query,
                            output_mode=output_mode,
                            current_tickers=tickers,
                            selection_ids=selection_ids,
                            selection_types=selection_types,
                            intent_contracts=intent_contracts,
                            request_frames=request_frames,
                        )
                    else:
                        hint_bound = _add_router_task_hints(
                            tasks=tasks,
                            context_refs=context_refs,
                            decision=conversation_decision,
                            query=query,
                            current_tickers=tickers,
                            output_mode=output_mode,
                            selection_ids=selection_ids,
                            selection_types=selection_types,
                        )
                    context_router_research_bound = context_router_research_bound or hint_bound
                    if contract_enforced and request_frames:
                        request_frame = request_frames[0]
                if not tasks:
                    _add_context_bound_research_task(
                        tasks=tasks,
                        context_refs=context_refs,
                        decision=conversation_decision,
                        query=query,
                        ui_context=ui_context,
                        memory_context=memory_context,
                        current_tickers=tickers,
                        selection_ids=selection_ids,
                        selection_types=selection_types,
                    )
                if not tasks:
                    if conversation_decision.context_binding.source == "none":
                        _add_unbound_research_task(
                            tasks=tasks,
                            decision=conversation_decision,
                            query=query,
                        )
                    else:
                        blocked_tasks.append(
                            {
                                "id": "blocked_1",
                                "subject_type": "unknown",
                                "subject_label": conversation_decision.context_binding.subject_hint,
                                "operation": _domain_intent_operation(
                                    conversation_decision.domain_intent,
                                    conversation_decision.confidence,
                                ),
                                "reason": "context_binding_unresolved",
                                "question": conversation_decision.reply_guidance
                                or "我理解这是接着上下文问，但还不能确定要绑定哪个对象。",
                                "suggestions": ["补充具体公司、股票代码、选中文档、持仓，或说明你指的是哪份报告"],
                                "fallback_allowed": False,
                            }
                        )
            if not tasks and conversation_decision.execution_route == "clarify":
                blocked_tasks.append(
                    {
                        "id": "blocked_1",
                        "subject_type": "unknown",
                        "subject_label": conversation_decision.context_binding.subject_hint,
                        "operation": _operation("qa", 0.0),
                        "reason": "context_router_clarify",
                        "question": conversation_decision.reply_guidance or "我需要你补充想看的对象或上下文。",
                        "suggestions": ["补充公司、股票代码、宏观主题、持仓，或说明你指的是哪条消息/哪份报告"],
                        "fallback_allowed": False,
                    }
                )

    tasks = _prune_url_only_company_context_tasks(tasks, query=query, explicit_urls=explicit_urls)

    if (
        not tasks
        and not blocked_tasks
        and conversation_decision is None
        and _history_tickers_from_messages(state, query)
    ):
        history_tickers = _history_tickers_from_messages(state, query)
        conversation_decision = ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(
                source="last_turn",
                confidence=0.62,
                reason="same-thread history provides the subject while router is unavailable",
                subject_hint=", ".join(history_tickers[:3]),
            ),
            relation="follow_up",
            domain_intent="analysis",
            confidence=0.58,
            needs_tools=False,
            reason="deterministic same-thread direct fallback without tools",
        )
        trace["conversation_router"] = conversation_decision.model_dump()
        reply = await generate_contextual_reply(state, conversation_decision)
        result = _direct_conversation_result(
            query=query,
            output_mode=output_mode,
            decision=conversation_decision,
            reply=reply,
            context_refs=[*context_refs, _binding_context_ref(conversation_decision.context_binding)],
            artifacts=artifacts,
            trace=trace,
            memory_context=memory_context,
            request_frame=request_frame,
        )
        await _emit_understanding_trace(result["understanding"])
        return result

    if (
        not tasks
        and not blocked_tasks
        and conversation_decision is None
        and _request_frame_is_authoritative_direct_answer(request_frame, query)
    ):
        conversation_decision = ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(
                source="request_frame",
                confidence=0.72,
                reason="request frame answer lane requires no tool evidence",
            ),
            relation="new_topic",
            domain_intent="finance_concept",
            confidence=0.72,
            needs_tools=False,
            reason="request-frame answer contract without evidence obligations",
        )
        trace["conversation_router"] = conversation_decision.model_dump()
        reply = await generate_contextual_reply(state, conversation_decision)
        result = _direct_conversation_result(
            query=query,
            output_mode=output_mode,
            decision=conversation_decision,
            reply=reply,
            context_refs=list(context_refs),
            artifacts=artifacts,
            trace=trace,
            memory_context=memory_context,
            request_frame=request_frame,
        )
        await _emit_understanding_trace(result["understanding"])
        return result

    if (
        not tasks
        and not blocked_tasks
        and conversation_decision is None
        and not _request_frame_requires_execution(request_frame)
        and _query_can_fallback_to_direct_finance_answer(query)
    ):
        conversation_decision = ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(source="none", confidence=0.0),
            relation="new_topic",
            domain_intent="finance_concept",
            confidence=0.58,
            needs_tools=False,
            reason="deterministic finance concept fallback without tools",
        )
        trace["conversation_router"] = conversation_decision.model_dump()
        reply = await generate_contextual_reply(state, conversation_decision)
        result = _direct_conversation_result(
            query=query,
            output_mode=output_mode,
            decision=conversation_decision,
            reply=reply,
            context_refs=list(context_refs),
            artifacts=artifacts,
            trace=trace,
            memory_context=memory_context,
            request_frame=request_frame,
        )
        await _emit_understanding_trace(result["understanding"])
        return result

    has_alert_task = any((task.get("operation") or {}).get("name") == "alert_set" for task in tasks)
    pending_research_after_alert = has_alert_task and any(
        (task.get("operation") or {}).get("name") != "alert_set" for task in tasks
    )

    if not tasks and blocked_tasks:
        route = "clarify"
    elif tasks and has_alert_task and (pending_research_after_alert or all((task.get("operation") or {}).get("name") == "alert_set" for task in tasks)):
        route = "alert"
    elif tasks or _request_frame_requires_execution(request_frame):
        route = "research"
    else:
        route = "clarify"
        blocked_tasks.append(
            {
                "id": "blocked_1",
                "subject_type": "unknown",
                "subject_label": "",
                "operation": _operation("qa", 0.0),
                "reason": "missing_analysis_target",
                "question": "我需要知道你想分析的公司、股票、宏观主题、新闻、财报或持仓。",
                "suggestions": ["输入公司名或 ticker，例如 谷歌 / GOOGL", "输入宏观主题，例如 美联储利率路径"],
                "fallback_allowed": False,
            }
        )

    if blocked_tasks:
        _sanitize_blocked_task_questions(query, blocked_tasks)

    if route == "clarify":
        first_blocked = blocked_tasks[0] if blocked_tasks else {}
        suggestions = list(first_blocked.get("suggestions") or [])
        question = str(first_blocked.get("question") or "请补充分析对象。")
        if conversation_decision is not None and conversation_decision.execution_route == "clarify":
            suggestions = suggestions[:2]
        if suggestions:
            artifacts["draft_markdown"] = "\n".join([question, "", "可以补充：", *[f"- {s}" for s in suggestions]]).strip()
        else:
            artifacts["draft_markdown"] = question

    if _is_explicit_brief_request(query):
        output_mode = "brief"

    if intent_contract is None and intent_contracts:
        intent_contract = intent_contracts[0]

    reply_contract = build_reply_contract(
        query=query,
        output_mode=output_mode,
        tasks=tasks,
        blocked_tasks=blocked_tasks,
        conversation_decision=conversation_decision,
        memory_context=memory_context,
    )
    _apply_reply_contract_to_tasks(tasks, reply_contract)
    reply_contract = build_reply_contract(
        query=query,
        output_mode=output_mode,
        tasks=tasks,
        blocked_tasks=blocked_tasks,
        conversation_decision=conversation_decision,
        memory_context=memory_context,
    )

    primary = tasks[0] if tasks else None
    operation = (primary or {}).get("operation") or (
        (request_frame.get("legacy_operation") if isinstance(request_frame, dict) else None)
        if _request_frame_requires_execution(request_frame)
        else None
    ) or _operation("qa", 0.0)
    subject = _build_subject(primary, selection_payload, tasks)
    if not tasks and isinstance(request_frame, dict):
        frame_subject = request_frame.get("subject") if isinstance(request_frame.get("subject"), dict) else {}
        frame_tickers = frame_subject.get("tickers") if isinstance(frame_subject, dict) else []
        if isinstance(frame_tickers, list):
            subject = _build_subject(
                {
                    "subject_type": frame_subject.get("type", "company"),
                    "tickers": frame_tickers,
                    "selection_ids": [],
                    "selection_types": [],
                    "selection_payload": selection_payload,
                },
                selection_payload,
                [],
            )
    facets = derive_request_facets(query=query, operation=operation, subject=subject)
    clarify = {
        "needed": route == "clarify",
        "reason": str((blocked_tasks[0] if blocked_tasks else {}).get("reason") or ""),
        "question": str((blocked_tasks[0] if blocked_tasks else {}).get("question") or ""),
        "suggestions": list((blocked_tasks[0] if blocked_tasks else {}).get("suggestions") or []),
    }
    summary_bits = []
    if tasks:
        for task in tasks[:5]:
            op_name = (task.get("operation") or {}).get("name")
            subject_label = task.get("subject_label") or ",".join(task.get("tickers") or []) or task.get("subject_type")
            summary_bits.append(f"{subject_label}:{op_name}")
    if blocked_tasks:
        summary_bits.append(f"阻塞项:{len(blocked_tasks)}")
    user_visible_summary = "；".join(summary_bits) if summary_bits else "需要补充信息。"

    understanding = {
        "route": route,
        "original_query": query,
        "cleaned_query": query,
        "language": "zh" if re.search(r"[\u4e00-\u9fff]", query) else "en",
        "social_prefix": social_prefix,
        "user_visible_summary": user_visible_summary,
        "confidence": 0.78 if tasks else 0.42,
        "tasks": tasks,
        "blocked_tasks": blocked_tasks,
        "context_refs": context_refs,
        "fallback_assumptions": fallback_assumptions,
        "facets": facets,
    }
    # WP2-T4：understanding_v2 影子默认冻结（off）——纯对拍产物，无任何消费方（见 notes-contract-consumers.md）
    understanding_v2_mode = str(os.getenv("FINSIGHT_UNDERSTANDING_V2_MODE") or "off").strip().lower()
    understanding_v2 = {}
    if understanding_v2_mode != "off":
        understanding_v2 = build_understanding_v2(
            query=query,
            output_mode=output_mode,
            tasks=tasks,
            blocked_tasks=blocked_tasks,
            subject=subject,
            operation=operation,
            reply_contract=reply_contract,
            context_refs=context_refs,
            fallback_assumptions=fallback_assumptions,
        )
        understanding["v2"] = understanding_v2
    trace["understanding"] = understanding
    if contract_enforced and intent_contract is not None:
        trace["intent_contract"] = intent_contract
    elif contract_shadow and intent_contract is not None:
        trace["intent_contract_shadow"] = intent_contract
    if contract_enforced and intent_contracts:
        trace["intent_contracts"] = intent_contracts
    elif contract_shadow and intent_contracts:
        trace["intent_contracts_shadow"] = intent_contracts
    if understanding_v2:
        trace["understanding_v2"] = understanding_v2
    if contract_enforced and not request_frames and request_frame:
        request_frames = [request_frame]
    if contract_enforced and request_frames:
        request_frame = request_frames[0]
        understanding["request_frames"] = request_frames
        trace["request_frames"] = request_frames
    if contract_enforced and request_frame:
        understanding["request_frame"] = request_frame
        trace["request_frame"] = request_frame
    trace["reply_contract"] = reply_contract
    await _emit_understanding_trace(understanding)

    result = {
        "understanding": understanding,
        "understanding_v2": understanding_v2,
        "reply_contract": reply_contract,
        "tasks": tasks,
        "blocked_tasks": blocked_tasks,
        "context_refs": context_refs,
        "subject": subject,
        "operation": operation,
        "facets": facets,
        "output_mode": output_mode,
        "clarify": clarify,
        "chat_responded": route == "direct",
        "pending_research_after_alert": pending_research_after_alert,
        "artifacts": artifacts,
        "trace": trace,
    }
    if contract_enforced and request_frames:
        result["request_frames"] = request_frames
    if contract_enforced and request_frame:
        result["request_frame"] = request_frame
    if contract_enforced and intent_contract is not None:
        result["intent_contract"] = intent_contract
    if contract_enforced and intent_contracts:
        result["intent_contracts"] = intent_contracts
    return result

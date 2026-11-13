# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/planner_stub.py（WP3 Task2，零行为变更）。
from __future__ import annotations

import os
import re
import json

from backend.graph.earnings_intent import query_requests_earnings_price_impact
from backend.graph.capability_registry import select_agents_for_request
from backend.graph.coverage_validator import validate_plan_coverage_for_frames
from backend.graph.intent_contract import EXTERNAL_IMPACT_LIGHT_PROFILE, MACRO_INDICATOR_KEYS, canonical_evidence_kinds
from backend.graph.request_task_contract import reply_contract_disallows_news
from backend.graph.state import GraphState
from backend.graph.plan_ir import PlanIR, PlanBudget, PlanSubject
from backend.graph.understanding_v2 import VALUATION_COMPARE_LIGHT_PROFILE, project_v2_tasks_to_legacy
from backend.graph.planning.builders.evidence import _append_evidence_steps_for_ticker
from backend.graph.planning.steps import _append_tool_step, _append_agent_step
from backend.graph.planning.builders.url_docs import _append_document_task_steps
from backend.tools.macro_official import official_macro_query


def _frame_id(ctx, frame: dict, index: int) -> str:
    return str(frame.get("frame_id") or f"frame_{index}").strip() or f"frame_{index}"


def _frame_task_ids(ctx, frame_id: str) -> list[str]:
    if not ctx.ready_tasks:
        return [frame_id]
    return list(dict.fromkeys(
        str(task.get("id") or "").strip()
        for task in ctx.ready_tasks
        if str(task.get("id") or "").strip()
        and (
            str(task.get("request_frame_id") or "").strip() == frame_id
            or (not task.get("request_frame_id") and str(task.get("id") or "").strip() == frame_id)
        )
    ))


def _frame_subject(ctx, frame: dict) -> dict:
    subject_payload = frame.get("subject")
    return subject_payload if isinstance(subject_payload, dict) else {}


def _frame_subject_type(ctx, frame: dict) -> str:
    return str(_frame_subject(ctx, frame).get("type") or "unknown").strip().lower() or "unknown"


def _frame_tickers(ctx, frame: dict) -> list[str]:
    frame_subject = _frame_subject(ctx, frame)
    frame_tickers = frame_subject.get("tickers")
    if not isinstance(frame_tickers, list):
        return []
    normalized: list[str] = []
    seen: set[str] = set()
    for item in frame_tickers:
        ticker = str(item or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        normalized.append(ticker)
    return normalized


def _frame_required_evidence(ctx, frame: dict) -> list[str]:
    raw_evidence = frame.get("evidence_obligations")
    kinds = canonical_evidence_kinds(raw_evidence if isinstance(raw_evidence, list) else [])
    if "required_input_groups" not in frame:
        return kinds
    from backend.graph.intent_contract import evidence_plan_for_kinds
    if ctx.output_mode == "investment_report":
        return [kind for kind in kinds if evidence_plan_for_kinds([kind], market=ctx.market or "US")]
    groups = frame["required_input_groups"]
    selected = []
    for group in groups:
        choice = next((kind for kind in group["any_of"] if evidence_plan_for_kinds([kind], market=ctx.market or "US")), None)
        if choice and choice not in selected:
            selected.append(choice)
    grouped = {kind for group in groups for kind in group["any_of"]}
    enrichment = set(frame.get("enrichment") or [])
    selected.extend(kind for kind in kinds if kind not in grouped | enrichment)
    if ctx.output_mode == "investment_report":
        selected.extend(kind for kind in kinds if kind in enrichment and evidence_plan_for_kinds([kind], market=ctx.market or "US"))
    return list(dict.fromkeys(selected))


def _frame_evidence_profile(ctx, frame: dict) -> str:
    raw_intent_contract = frame.get("intent_contract")
    intent_contract = raw_intent_contract if isinstance(raw_intent_contract, dict) else {}
    raw_legacy_operation = frame.get("legacy_operation")
    legacy_operation = raw_legacy_operation if isinstance(raw_legacy_operation, dict) else {}
    raw_legacy_params = legacy_operation.get("params")
    legacy_params = raw_legacy_params if isinstance(raw_legacy_params, dict) else {}
    return str(
        frame.get("evidence_profile")
        or frame.get("budget_profile")
        or intent_contract.get("budget_profile")
        or legacy_params.get("evidence_profile")
        or legacy_params.get("budget_profile")
        or ""
    ).strip()


def _append_macro_frame_steps(ctx, frame: dict, *, group: str, task_ids: list[str]) -> None:
    frame_subject = _frame_subject(ctx, frame)
    label = str(frame_subject.get("label") or frame.get("subject_label") or "").strip()
    macro_query = str(frame.get("query_text") or label or ctx.query)
    requirements = [row for task_id in task_ids for row in ctx.ready_tasks_by_id.get(task_id, {}).get("answer_requirements", [])
                    if row.get("capability_status", "supported") == "supported"]
    selectors: dict[str | None, list[str]] = {}
    for requirement in requirements:
        indices = [key for key in [requirement.get("metric"), *requirement.get("components", [])] if key in MACRO_INDICATOR_KEYS]
        if indices:
            as_of = (requirement.get("time_scope") or {}).get("as_of")
            selected = selectors.setdefault(as_of, [])
            selected.extend(key for key in indices if key not in selected)
    all_indicators = list(dict.fromkeys(key for selected in selectors.values() for key in selected))
    employment_requested = bool({"nonfarm_payroll_change", "unemployment"}.intersection(all_indicators))
    research_query = macro_query
    macro_query = official_macro_query(research_query, all_indicators)
    for as_of, indicators in selectors.items():
        _append_tool_step(ctx, "get_fred_data", {"indicators": indicators, "as_of": as_of},
            why="按已确认的宏观数值指标采集同频官方序列，并保留指标口径与观测期。", optional=False,
            parallel_group=group, task_ids=task_ids, evidence_kind="macro_context")
    _append_tool_step(ctx, 
        "get_current_datetime",
        {},
        why="Request frame macro evidence: current date guard.",
        optional=True,
        parallel_group=group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "get_official_macro_releases",
        {"query": macro_query, "max_results": 8, **({"include_content": True} if employment_requested else {})},
        why="Request frame macro evidence: official macro releases.",
        evidence_kind="macro_context",
        optional=False,
        parallel_group=group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "get_authoritative_media_news",
        {"query": macro_query, "max_results": 6, "authoritative_only": True},
        why="Request frame macro evidence: authoritative market context.",
        evidence_kind="macro_context",
        optional=True,
        parallel_group=group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "search",
        {"query": macro_query},
        why="Request frame macro evidence: supplemental search.",
        evidence_kind="macro_context",
        optional=True,
        parallel_group=group,
        task_ids=task_ids,
    )
    if not requirements or any(row.get("requires_analysis") for row in requirements):
        _append_agent_step(ctx, "macro_agent", {"query": research_query, "ticker": "MACRO",
            **({"indicators": all_indicators, "as_of": next(iter(selectors)) if len(selectors) == 1 else None} if all_indicators else {})},
            why="结合带观测期和单位的官方宏观指标解释政策影响。", optional=True,
            parallel_group=f"{group}_macro", task_ids=task_ids, evidence_kind="macro_context")


def _append_performance_comparison_frame_step(ctx, frame: dict, *, group: str, task_ids: list[str]) -> bool:
    if "get_performance_comparison" not in ctx.allowed_tools:
        return False
    frame_tickers = _frame_tickers(ctx, frame)
    if not frame_tickers and isinstance(ctx.tickers, list):
        frame_tickers = [
            str(ticker).strip().upper()
            for ticker in ctx.tickers
            if str(ticker).strip()
        ]
    frame_tickers = list(dict.fromkeys([ticker for ticker in frame_tickers if ticker]))[:6]
    if len(frame_tickers) < 2:
        return False
    _append_tool_step(ctx, 
        "get_performance_comparison",
        {"tickers": {ticker: ticker for ticker in frame_tickers}},
        why="Request frame compare evidence: cross-subject performance comparison.",
        optional=False,
        parallel_group=group,
        task_ids=task_ids,
    )
    return True




def _append_request_frame_steps(ctx) -> bool:
    if not ctx.request_frames:
        return False
    bound_frames = {str(frame.get("frame_id")) for frame in ctx.request_frames}
    if any(str(task.get("request_frame_id")) not in bound_frames for task in ctx.ready_tasks):
        return False
    # Frame 是执行分组，任务 ID 才是结果合同的身份；缺绑定时交回任务规划器。
    if any(not _frame_task_ids(ctx, _frame_id(ctx, frame, index)) for index, frame in enumerate(ctx.request_frames[:16], 1)):
        return False
    initial_step_count = len(ctx.steps)
    for index, frame in enumerate(ctx.request_frames[:16], 1):
        frame_id = _frame_id(ctx, frame, index)
        task_ids = _frame_task_ids(ctx, frame_id)
        group = frame_id
        required_evidence = _frame_required_evidence(ctx, frame)
        if not required_evidence:
            continue

        if _frame_subject_type(ctx, frame) in {"filing", "research_doc", "news_item", "news_set"}:
            for task_id in task_ids:
                task = ctx.ready_tasks_by_id.get(task_id)
                if task:
                    _append_document_task_steps(ctx, task, group=group)
            continue

        if "macro_context" in required_evidence or _frame_subject_type(ctx, frame) == "macro":
            _append_macro_frame_steps(ctx, frame, group=group, task_ids=task_ids)

        if "performance_comparison" in required_evidence:
            _append_performance_comparison_frame_step(ctx, frame, group=group, task_ids=task_ids)

        per_ticker_evidence = [
            kind
            for kind in required_evidence
            if kind not in {"macro_context", "performance_comparison"}
        ]
        if not per_ticker_evidence:
            continue
        frame_tickers = _frame_tickers(ctx, frame)
        if not frame_tickers and _frame_subject_type(ctx, frame) == "company":
            query = f"{_frame_subject(ctx, frame).get('label') or ''} {frame.get('query_text') or ctx.query}".strip()
            _append_tool_step(ctx, "search", {"query": query}, why="公司名已明确，先检索原始要求及证券身份。",
                              optional=False, parallel_group=group, task_ids=task_ids, evidence_kind="document_context")
            _append_agent_step(ctx, "deep_search_agent", {"query": query}, why="读取发现的来源并核对公司研究依据。",
                               optional=True, parallel_group=f"{group}_research_agents", task_ids=task_ids,
                               evidence_kind="document_context")
            continue
        if not frame_tickers and ctx.primary_ticker and _frame_subject_type(ctx, frame) in {"company", "index", "commodity"}:
            frame_tickers = [ctx.primary_ticker]
        for ticker in frame_tickers[:12]:
            _append_evidence_steps_for_ticker(ctx, 
                ticker,
                per_ticker_evidence,
                group=group,
                task_ids=task_ids,
                evidence_profile=_frame_evidence_profile(ctx, frame),
            )
    return len(ctx.steps) > initial_step_count


def _request_frames_authoritatively_need_no_plan_steps(ctx) -> bool:
    if ctx.ready_tasks:
        return False
    if not ctx.request_frames:
        return False
    for frame in ctx.request_frames:
        render = frame.get("render_contract") if isinstance(frame.get("render_contract"), dict) else {}
        if (
            _frame_required_evidence(ctx, frame)
            or str(frame.get("lane") or "").strip().lower() in {"research", "report"}
            or render.get("shape") == "compare"
        ):
            return False
    return True

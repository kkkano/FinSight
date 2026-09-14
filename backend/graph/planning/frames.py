# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/planner_stub.py（WP3 Task2，零行为变更）。
from __future__ import annotations

import os
import re
import json

from backend.graph.earnings_intent import query_requests_earnings_price_impact
from backend.graph.capability_registry import select_agents_for_request
from backend.graph.coverage_validator import validate_plan_coverage_for_frames
from backend.graph.intent_contract import EXTERNAL_IMPACT_LIGHT_PROFILE, canonical_evidence_kinds
from backend.graph.request_task_contract import reply_contract_disallows_news
from backend.graph.state import GraphState
from backend.graph.plan_ir import PlanIR, PlanBudget, PlanSubject
from backend.graph.understanding_v2 import VALUATION_COMPARE_LIGHT_PROFILE, project_v2_tasks_to_legacy
from backend.graph.planning.builders.evidence import _append_evidence_steps_for_ticker
from backend.graph.planning.steps import _append_tool_step


def _frame_id(ctx, frame: dict, index: int) -> str:
    return str(frame.get("frame_id") or f"frame_{index}").strip() or f"frame_{index}"


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
    return canonical_evidence_kinds(raw_evidence if isinstance(raw_evidence, list) else [])


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


def _append_macro_frame_steps(ctx, frame: dict, *, group: str, task_id: str) -> None:
    frame_subject = _frame_subject(ctx, frame)
    label = str(frame_subject.get("label") or frame.get("subject_label") or "").strip()
    macro_query = label if label else ctx.query
    _append_tool_step(ctx, 
        "get_current_datetime",
        {},
        why="Request frame macro evidence: current date guard.",
        optional=True,
        parallel_group=group,
        task_ids=[task_id],
    )
    _append_tool_step(ctx, 
        "get_official_macro_releases",
        {"query": macro_query, "max_results": 8},
        why="Request frame macro evidence: official macro releases.",
        optional=False,
        parallel_group=group,
        task_ids=[task_id],
    )
    _append_tool_step(ctx, 
        "get_authoritative_media_news",
        {"query": macro_query, "max_results": 6, "authoritative_only": True},
        why="Request frame macro evidence: authoritative market context.",
        optional=True,
        parallel_group=group,
        task_ids=[task_id],
    )
    _append_tool_step(ctx, 
        "search",
        {"query": macro_query},
        why="Request frame macro evidence: supplemental search.",
        optional=True,
        parallel_group=group,
        task_ids=[task_id],
    )


def _append_performance_comparison_frame_step(ctx, frame: dict, *, group: str, task_id: str) -> bool:
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
        task_ids=[task_id],
    )
    return True




def _append_request_frame_steps(ctx) -> bool:
    if not ctx.request_frames:
        return False
    appended = False
    for index, frame in enumerate(ctx.request_frames[:16], 1):
        frame_id = _frame_id(ctx, frame, index)
        group = frame_id
        required_evidence = _frame_required_evidence(ctx, frame)
        if not required_evidence:
            continue

        if "macro_context" in required_evidence or _frame_subject_type(ctx, frame) == "macro":
            _append_macro_frame_steps(ctx, frame, group=group, task_id=frame_id)
            appended = True

        if "performance_comparison" in required_evidence:
            appended = _append_performance_comparison_frame_step(ctx, frame, group=group, task_id=frame_id) or appended

        per_ticker_evidence = [
            kind
            for kind in required_evidence
            if kind not in {"macro_context", "performance_comparison"}
        ]
        if not per_ticker_evidence:
            continue
        frame_tickers = _frame_tickers(ctx, frame)
        if not frame_tickers and ctx.primary_ticker and _frame_subject_type(ctx, frame) in {"company", "index", "commodity"}:
            frame_tickers = [ctx.primary_ticker]
        for ticker in frame_tickers[:12]:
            _append_evidence_steps_for_ticker(ctx, 
                ticker,
                per_ticker_evidence,
                group=group,
                task_ids=[frame_id],
                evidence_profile=_frame_evidence_profile(ctx, frame),
            )
            appended = True
    return appended


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

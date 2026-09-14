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


def _contains_any(ctx, tokens: tuple[str, ...]) -> bool:
    return any(token in ctx.query_lower for token in tokens)


def _qa_needs_live_context(ctx) -> bool:
    if ctx.output_mode == "investment_report":
        return True
    if ctx.news_disallowed:
        return False
    return _contains_any(ctx, 
        (
            "最新",
            "最近",
            "新闻",
            "消息",
            "今天",
            "现在",
            "实时",
            "股价",
            "价格",
            "涨跌",
            "财报",
            "指引",
            "latest",
            "recent",
            "news",
            "today",
            "current",
            "real-time",
            "realtime",
            "price",
            "earnings",
            "guidance",
        )
    )


def _macro_query_for_task(ctx, task: dict) -> str:
    label = str(task.get("subject_label") or "").strip()
    if label and label != "宏观环境":
        return label
    return ctx.query


def _task_operation_params(ctx, task: dict) -> dict:
    op = task.get("operation")
    if not isinstance(op, dict):
        return {}
    params = op.get("params")
    return params if isinstance(params, dict) else {}


def _task_required_evidence(ctx, task: dict) -> list[str]:
    params = _task_operation_params(ctx, task)
    required = params.get("required_evidence")
    if not isinstance(required, list):
        task_params = task.get("params")
        required = task_params.get("required_evidence") if isinstance(task_params, dict) else []
    if not isinstance(required, list):
        required = []
    if not required and len(ctx.ready_tasks) == 1 and isinstance(ctx.policy.get("required_evidence"), list):
        required = ctx.policy.get("required_evidence") or []
    return canonical_evidence_kinds([str(item) for item in required if str(item).strip()])


def _task_id(ctx, task: dict) -> str:
    value = str(task.get("id") or "").strip()
    return value or f"task_{len(ctx.steps) + 1}"


def _task_operation_name(ctx, task: dict) -> str:
    op = task.get("operation")
    if isinstance(op, dict):
        name = op.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return "qa"


def _task_tickers(ctx, task: dict) -> list[str]:
    values = task.get("tickers")
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        ticker = str(value or "").strip().upper()
        if not ticker or ticker in seen:
            continue
        seen.add(ticker)
        result.append(ticker)
    return result


def _task_urls(ctx, task: dict) -> list[str]:
    params = _task_operation_params(ctx, task)
    candidates: list[object] = [
        params.get("url"),
        task.get("url"),
    ]
    raw_urls = params.get("urls")
    if isinstance(raw_urls, list):
        candidates.extend(raw_urls)
    result: list[str] = []
    seen: set[str] = set()
    for value in candidates:
        url = str(value or "").strip().rstrip(".,，。;；:：!?！？")
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        result.append(url)
    return result[:3]


def _plan_task_summary(ctx) -> list[dict]:
    rows: list[dict] = []
    for task in ctx.ready_tasks[:16]:
        task_id = str(task.get("id") or f"task_{len(rows) + 1}").strip()
        rows.append(
            {
                "id": task_id or f"task_{len(rows) + 1}",
                "title": str(task.get("title") or task.get("subject_label") or task.get("subject_type") or "分析任务"),
                "subject_type": str(task.get("subject_type") or "unknown"),
                "tickers": _task_tickers(ctx, task),
                "operation": _task_operation_name(ctx, task),
                "status": str(task.get("status") or "ready"),
                "priority": int(task.get("priority") or 50),
                "order_index": int(task.get("order_index") or 0),
                "request_frame_id": str(task.get("request_frame_id") or f"request_frame_{len(rows)}"),
                "render_kind": str(task.get("render_kind") or "single"),
                "render_group_id": str(task.get("render_group_id") or task.get("request_frame_id") or f"request_frame_{len(rows)}"),
            }
        )
    return rows


def _plan_subject_payload(ctx) -> dict:
    return {
        "subject_type": str(ctx.subject.get("subject_type") or "unknown"),
        "tickers": [
            str(ticker).strip().upper()
            for ticker in (ctx.subject.get("tickers") if isinstance(ctx.subject.get("tickers"), list) else [])
            if str(ticker).strip()
        ],
        "selection_ids": list(ctx.subject.get("selection_ids") or []) if isinstance(ctx.subject.get("selection_ids"), list) else [],
        "selection_types": list(ctx.subject.get("selection_types") or []) if isinstance(ctx.subject.get("selection_types"), list) else [],
        "selection_payload": list(ctx.subject.get("selection_payload") or []) if isinstance(ctx.subject.get("selection_payload"), list) else [],
        "binding_tier": str(ctx.subject.get("binding_tier") or "none"),
        "is_comparison": ctx.subject.get("is_comparison") if isinstance(ctx.subject.get("is_comparison"), bool) else None,
    }


def _compare_has_current_support(ctx, task: dict) -> bool:
    compare_tickers = set(_task_tickers(ctx, task))
    if not compare_tickers:
        return False
    current_ops = {"price", "fetch", "analyze_impact", "daily_brief", "technical", "investment_opinion", "earnings_impact", "earnings_performance"}
    for other in ctx.ready_tasks:
        if other is task:
            continue
        if _task_operation_name(ctx, other) not in current_ops:
            continue
        if compare_tickers.intersection(_task_tickers(ctx, other)):
            return True
    return False


def _should_use_performance_compare(ctx, task: dict | None = None) -> bool:
    if ctx.output_mode == "investment_report":
        return True
    params = _task_operation_params(ctx, task or {})
    if bool(params.get("synthesis_only")):
        return False
    data_profile = str(params.get("data_profile") or params.get("comparison_data_profile") or "").strip().lower()
    if data_profile in {"research_synthesis", "synthesis_only"}:
        return False
    if data_profile in {"performance", "historical_performance"}:
        return True
    if data_profile in {
        "facet_evidence",
        "research_synthesis",
        "synthesis_only",
        VALUATION_COMPARE_LIGHT_PROFILE,
        "valuation_compare",
        "technical_compare",
        "earnings_price_impact",
        "investment_opinion_compare",
    }:
        return False
    if task is not None and _compare_has_current_support(ctx, task):
        return False
    return True


_SEC_HOLDINGS_ENABLED_VALUES = {"1", "true", "yes", "on"}


def _sec_holdings_enabled() -> bool:
    return str(os.getenv("SEC_HOLDINGS_ENABLED") or "").strip().lower() in _SEC_HOLDINGS_ENABLED_VALUES


def _holder_cik_or_name_from_query(query: str) -> str:
    lowered = str(query or "").lower()
    if any(token in lowered for token in ("buffett", "berkshire")) or any(
        token in str(query or "") for token in ("巴菲特", "伯克希尔")
    ):
        return "Berkshire Hathaway"
    return ""

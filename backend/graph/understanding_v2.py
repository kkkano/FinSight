# -*- coding: utf-8 -*-
"""Canonical request-understanding helpers.

This module deliberately evolves the existing ``understanding/tasks`` contract
instead of creating a parallel intent system.  The legacy ``operation`` field is
kept as a compatibility projection; stable semantics live in subjects, facets
and relations.
"""
from __future__ import annotations

import os
import re
from typing import Any

from backend.graph.earnings_intent import (
    query_requests_earnings_performance,
    query_requests_earnings_price_impact,
)
from backend.graph.investment_intent import query_requests_investment_opinion

SCHEMA_VERSION = "understanding.v2"

_COMPARE_HINTS = ("对比", "比较", "相比", "vs", "versus", "谁", "哪个", "哪家", "compare", "which", "who")
_RANK_HINTS = ("哪个", "哪家", "谁", "which", "who", "better", "stronger", "more", "更")
_VALUATION_HINTS = (
    "估值",
    "valuation",
    "p/e",
    "pe ",
    "pe ratio",
    "p/s",
    "ps ratio",
    "p/b",
    "pb ratio",
    "贵",
    "便宜",
    "合理",
    "overvalued",
    "undervalued",
    "expensive",
    "cheap",
)
_TECHNICAL_HINTS = ("技术面", "技术分析", "k线", "均线", "macd", "rsi", "technical", "chart", "support", "resistance")
_PRICE_HINTS = ("价格", "股价", "涨跌幅", "涨幅", "跌幅", "表现", "行情", "price", "quote", "performance")
_NEWS_HINTS = ("新闻", "消息", "headline", "latest", "news")
_RISK_HINTS = ("风险", "risk", "drawdown", "volatility", "压力")
_MACRO_HINTS = ("美联储", "利率", "cpi", "ppi", "fed", "fomc", "macro", "通胀")


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    for hint in hints:
        needle = str(hint or "").strip().lower()
        if not needle:
            continue
        if needle in lowered:
            return True
    return False


def _facet(name: str, *, required: bool = True, metrics: list[str] | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {"id": f"facet_{name}", "name": name, "required": required}
    if metrics:
        row["metrics"] = list(metrics)
    return row


def infer_facets(query: str, *, output_mode: str = "") -> list[dict[str, Any]]:
    """Infer stable research dimensions without enumerating full query types."""
    names: list[str] = []

    def add(name: str) -> None:
        if name not in names:
            names.append(name)

    if _contains_any(query, _VALUATION_HINTS):
        add("valuation")
        add("fundamental")
        add("risk")
    if query_requests_earnings_price_impact(query):
        add("earnings")
        add("price")
        add("news")
        add("risk")
        add("fundamental")
    elif query_requests_earnings_performance(query):
        add("earnings")
        add("fundamental")
        add("news")
    if _contains_any(query, _TECHNICAL_HINTS):
        add("technical")
        add("price")
    if query_requests_investment_opinion(query):
        for name in ("price", "technical", "news", "fundamental", "valuation", "risk"):
            add(name)
    if _contains_any(query, _PRICE_HINTS):
        add("price")
    if _contains_any(query, _NEWS_HINTS):
        add("news")
    if _contains_any(query, _RISK_HINTS):
        add("risk")
    if _contains_any(query, _MACRO_HINTS):
        add("macro")
    if str(output_mode or "").strip().lower() == "investment_report":
        for name in ("price", "news", "fundamental", "valuation", "risk"):
            add(name)

    return [_facet(name) for name in names]


def facet_names(facets: list[dict[str, Any]] | None) -> list[str]:
    names: list[str] = []
    for facet in facets or []:
        if not isinstance(facet, dict):
            continue
        name = str(facet.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def has_comparison_relation(query: str, tickers: list[str]) -> bool:
    return len([ticker for ticker in tickers if str(ticker).strip()]) >= 2 and _contains_any(query, _COMPARE_HINTS)


def _subject_id(ticker: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(ticker or "").strip().lower()).strip("_")
    return f"subj_{cleaned or 'unknown'}"


def build_subject_specs(tickers: list[str]) -> list[dict[str, Any]]:
    subjects: list[dict[str, Any]] = []
    seen: set[str] = set()
    for idx, ticker in enumerate(tickers):
        symbol = str(ticker or "").strip().upper()
        if not symbol or symbol in seen:
            continue
        seen.add(symbol)
        subjects.append(
            {
                "id": _subject_id(symbol),
                "type": "company",
                "label": symbol,
                "tickers": [symbol],
                "role": "primary" if idx == 0 else "peer",
                "binding": "explicit",
                "confidence": 0.9,
            }
        )
    return subjects


def build_relation_specs(query: str, tickers: list[str], facets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not has_comparison_relation(query, tickers):
        return []
    relation_type = "rank" if _contains_any(query, _RANK_HINTS) else "compare"
    names = facet_names(facets)
    return [
        {
            "id": "rel_compare_1",
            "type": relation_type,
            "subject_ids": [_subject_id(ticker) for ticker in tickers if str(ticker).strip()],
            "facet_refs": names,
            "comparator": _relation_comparator(query, names),
            "render_strategy": "comparison_matrix_with_conditional_verdict",
        }
    ]


def _relation_comparator(query: str, names: list[str]) -> str:
    lowered = str(query or "").lower()
    if "valuation" in names or "估值" in str(query or ""):
        return "more_reasonable"
    if "technical" in names:
        return "stronger"
    if "earnings" in names and "price" in names:
        return "larger_impact"
    if "risk" in names:
        return "higher_risk" if ("高" in str(query or "") or "higher" in lowered) else "risk_adjusted"
    return "relative_view"


def _operation(name: str, confidence: float, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "confidence": confidence, "params": params or {}}


def relation_operation_params(query: str, facets: list[dict[str, Any]]) -> dict[str, Any]:
    names = facet_names(facets)
    params: dict[str, Any] = {
        "relation": "rank" if _contains_any(query, _RANK_HINTS) else "compare",
        "facets": names,
        "aspects": names,
    }
    if any(name in names for name in ("valuation", "fundamental", "earnings", "risk", "technical")):
        params["comparison_data_profile"] = "facet_evidence"
    return params


def support_operations_for_relation(query: str, facets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project facet bundles into legacy operations for current downstream nodes."""
    names = set(facet_names(facets))
    operations: list[dict[str, Any]] = []

    def add(op: dict[str, Any]) -> None:
        name = str(op.get("name") or "")
        if name and name not in {str(existing.get("name") or "") for existing in operations}:
            operations.append(op)

    if "earnings" in names and "price" in names:
        add(
            _operation(
                "earnings_impact",
                0.86,
                {
                    "event_type": "earnings",
                    "target_metric": "stock_price",
                    "facets": sorted(names),
                    "required_dimensions": ["financials", "earnings", "price", "news", "risk"],
                    "relation_ids": ["rel_compare_1"],
                },
            )
        )
    elif "earnings" in names:
        add(_operation("earnings_performance", 0.84, {"facets": sorted(names), "relation_ids": ["rel_compare_1"]}))

    if "technical" in names:
        add(
            _operation(
                "technical",
                0.82,
                {
                    "facets": sorted(names),
                    "indicators": ["moving_average", "RSI", "MACD", "volume", "support_resistance"],
                    "include_current_price": True,
                    "relation_ids": ["rel_compare_1"],
                },
            )
        )

    if {"valuation", "fundamental"} & names or query_requests_investment_opinion(query):
        add(
            _operation(
                "investment_opinion",
                0.86,
                {
                    "facets": sorted(names),
                    "required_dimensions": ["price", "news", "fundamental", "valuation", "risk"],
                    "relation_ids": ["rel_compare_1"],
                },
            )
        )

    if "price" in names and not operations:
        add(_operation("price", 0.82, {"facets": sorted(names), "relation_ids": ["rel_compare_1"]}))
    if "news" in names and (not operations or {str(op.get("name") or "") for op in operations} == {"price"}):
        add(_operation("fetch", 0.78, {"topic": "news", "facets": sorted(names), "relation_ids": ["rel_compare_1"]}))

    return operations[: _max_relation_support_operations()]


def _max_relation_support_operations() -> int:
    raw = os.getenv("FINSIGHT_UNDERSTANDING_V2_MAX_SUPPORT_OPS", "3")
    try:
        value = int(raw)
    except Exception:
        return 3
    return max(1, min(8, value))


def build_understanding_v2(
    *,
    query: str,
    output_mode: str,
    tasks: list[dict[str, Any]],
    blocked_tasks: list[dict[str, Any]],
    subject: dict[str, Any],
    operation: dict[str, Any],
    reply_contract: dict[str, Any],
    context_refs: list[dict[str, Any]],
    fallback_assumptions: list[str],
) -> dict[str, Any]:
    tickers = [str(ticker).strip().upper() for ticker in (subject.get("tickers") or []) if str(ticker).strip()]
    facets = infer_facets(query, output_mode=output_mode)
    relations = build_relation_specs(query, tickers, facets)
    return {
        "schema_version": SCHEMA_VERSION,
        "route": "clarify" if blocked_tasks else ("research" if tasks else "direct"),
        "original_query": query,
        "cleaned_query": query,
        "language": "zh" if re.search(r"[\u4e00-\u9fff]", str(query or "")) else "en",
        "subjects": build_subject_specs(tickers),
        "facets": facets,
        "relations": relations,
        "tasks": [_task_to_v2(task) for task in tasks],
        "blocked_tasks": blocked_tasks,
        "evidence_requirements": _evidence_requirements(facets, relations),
        "render": {
            "output_mode": output_mode,
            "lane": reply_contract.get("lane"),
            "structure": _render_structure(relations, reply_contract),
        },
        "constraints": _constraints_from_reply_contract(reply_contract),
        "primary_task_id": str((tasks[0] if tasks else {}).get("id") or ""),
        "confidence": {"overall": 0.78 if tasks else 0.42},
        "provenance": [{"source": "understand_request", "method": "deterministic_facet_relation_projection"}],
        "context_refs": context_refs,
        "fallback_assumptions": fallback_assumptions,
        "legacy_projection": {"subject": subject, "operation": operation, "reply_contract": reply_contract},
    }


def project_v2_tasks_to_legacy(understanding_v2: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return legacy-shaped tasks from a v2 payload for gradual reader migration."""
    if not isinstance(understanding_v2, dict):
        return []
    subjects_by_id: dict[str, dict[str, Any]] = {}
    for subject in understanding_v2.get("subjects") or []:
        if isinstance(subject, dict) and str(subject.get("id") or "").strip():
            subjects_by_id[str(subject.get("id"))] = subject

    rows: list[dict[str, Any]] = []
    for idx, task in enumerate(understanding_v2.get("tasks") or [], 1):
        if not isinstance(task, dict):
            continue
        operation = task.get("legacy_operation") if isinstance(task.get("legacy_operation"), dict) else {}
        subject_refs = [str(item) for item in (task.get("subject_refs") or []) if str(item).strip()]
        tickers: list[str] = []
        subject_type = "unknown"
        subject_label = ""
        for ref in subject_refs:
            subject = subjects_by_id.get(ref)
            if not isinstance(subject, dict):
                continue
            if subject_type == "unknown":
                subject_type = str(subject.get("type") or "unknown")
            if not subject_label:
                subject_label = str(subject.get("label") or "")
            tickers.extend(str(ticker).strip().upper() for ticker in (subject.get("tickers") or []) if str(ticker).strip())
        rows.append(
            {
                "id": str(task.get("id") or f"task_{idx}"),
                "subject_type": subject_type,
                "subject_label": subject_label,
                "tickers": tickers,
                "selection_ids": [],
                "selection_types": [],
                "operation": operation or {"name": "qa", "confidence": 0.0, "params": {}},
                "time_scope": task.get("time_scope") or {},
                "priority": int(task.get("priority") or 50),
                "status": str(task.get("status") or "ready"),
                "reason": "understanding_v2_projection",
                "constraints": [],
                "params": task.get("params") or {},
            }
        )
    return rows


def _task_to_v2(task: dict[str, Any]) -> dict[str, Any]:
    operation = task.get("operation") if isinstance(task.get("operation"), dict) else {}
    params = operation.get("params") if isinstance(operation.get("params"), dict) else {}
    facets = [str(item) for item in params.get("facets", []) if str(item).strip()] if isinstance(params.get("facets"), list) else []
    return {
        "id": task.get("id"),
        "goal_type": _goal_type(operation),
        "subject_refs": [_subject_id(ticker) for ticker in (task.get("tickers") or []) if str(ticker).strip()],
        "facet_refs": facets,
        "relation_refs": list(params.get("relation_ids") or []) if isinstance(params.get("relation_ids"), list) else [],
        "time_scope": task.get("time_scope") or {},
        "status": task.get("status") or "ready",
        "priority": task.get("priority"),
        "legacy_operation": operation,
        "params": task.get("params") or {},
    }


def _goal_type(operation: dict[str, Any]) -> str:
    name = str(operation.get("name") or "").strip().lower()
    if name == "compare":
        relation = str((operation.get("params") or {}).get("relation") or "").strip().lower()
        return "rank" if relation == "rank" else "compare"
    if name == "alert_set":
        return "set_alert"
    if name in {"analyze_impact", "earnings_impact"}:
        return "explain_impact"
    if name == "generate_report":
        return "generate_report"
    return "measure"


def _evidence_requirements(facets: list[dict[str, Any]], relations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    names = facet_names(facets)
    if not names:
        return []
    profile = "source_grounded"
    if relations and "valuation" in names:
        profile = "valuation_compare"
    elif relations and "technical" in names:
        profile = "technical_compare"
    elif "earnings" in names and "price" in names:
        profile = "earnings_price_impact"
    return [
        {
            "id": "ev_1",
            "profile": profile,
            "required_facets": names,
            "freshness": "latest" if {"price", "news", "technical"} & set(names) else "recent",
            "coverage": "cross_subject_normalized" if relations else "per_subject",
            "citation_policy": "cite_if_available",
            "missing_data_policy": "disclose",
        }
    ]


def _render_structure(relations: list[dict[str, Any]], reply_contract: dict[str, Any]) -> str:
    if relations:
        return "comparison_matrix"
    lane = str(reply_contract.get("lane") or "").strip()
    return "source_grounded_answer" if lane == "source_grounded_answer" else "short_answer"


def _constraints_from_reply_contract(reply_contract: dict[str, Any]) -> list[str]:
    constraints = reply_contract.get("source_constraints") if isinstance(reply_contract.get("source_constraints"), dict) else {}
    rows: list[str] = []
    for key, enabled in constraints.items():
        if enabled:
            rows.append(str(key))
    return rows


__all__ = [
    "SCHEMA_VERSION",
    "build_understanding_v2",
    "build_relation_specs",
    "build_subject_specs",
    "facet_names",
    "has_comparison_relation",
    "infer_facets",
    "project_v2_tasks_to_legacy",
    "relation_operation_params",
    "support_operations_for_relation",
]

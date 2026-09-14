# -*- coding: utf-8 -*-
"""
WP2-Task9: 双 planner 边界具名化（ORC-08）。

语义 = 原 planner._should_use_task_graph_planner 逐字搬运，True→"rule"、False→"llm"。
三个集合从 planner.py 内联字面量收编为唯一具名常量（原 subject 集合在函数内重复两处）。
"""
from __future__ import annotations

from typing import Any, Literal

# 原 planner.py simple_task_graph_ops（:117-124 区段）
SIMPLE_TASK_GRAPH_OPS: frozenset[str] = frozenset({
    "compare",
    "price",
    "fetch",
    "technical",
    "investment_opinion",
    "earnings_impact",
    "earnings_performance",
    "analyze_impact",
    "news_impact",
    "daily_brief",
    "fact_check",
    "macro_brief",
    "qa",
})

# 原 router_evidence_graph 的操作集（:162-166 区段）
ROUTER_EVIDENCE_OPS: frozenset[str] = frozenset({
    "compare",
    "price",
    "fetch",
    "investment_opinion",
    "analyze_impact",
    "news_impact",
    "daily_brief",
    "fact_check",
    "qa",
})

# url_evidence_graph 的操作集 = router 集 + macro_brief（保持原字面量语义）
URL_EVIDENCE_OPS: frozenset[str] = ROUTER_EVIDENCE_OPS | {"macro_brief"}

# 原函数内重复两处的 subject_type 白名单（:138-152 区段等）
PLANNABLE_SUBJECT_TYPES: frozenset[str] = frozenset({
    "company",
    "index",
    "crypto",
    "fund",
    "macro",
    "theme",
    "news_item",
    "news_set",
    "research_doc",
    "filing",
    "portfolio",
    "unknown",
})

_ROUTER_DECOMPOSED_REASONS = frozenset({
    "conversation_router_task_hint",
    "conversation_router_task_hint_support",
    "explicit_url_reference",
})

_EAGER_RULE_OPS = frozenset({
    "price",
    "fetch",
    "technical",
    "investment_opinion",
    "earnings_impact",
    "earnings_performance",
    "analyze_impact",
    "news_impact",
    "daily_brief",
})

_ROUTER_GRAPH_TRIGGER_OPS = frozenset({
    "compare",
    "investment_opinion",
    "analyze_impact",
    "news_impact",
    "daily_brief",
})


def _all_subjects_plannable(ready_tasks: list[dict[str, Any]]) -> bool:
    return all(
        str(task.get("subject_type") or "").strip().lower() in PLANNABLE_SUBJECT_TYPES
        for task in ready_tasks
    )


def select_planner_lane(state: dict[str, Any], ready_tasks: list[dict[str, Any]]) -> Literal["rule", "llm"]:
    """规则 planner 还是 LLM planner——语义与 _should_use_task_graph_planner 完全一致。"""
    if not ready_tasks:
        return "llm"
    output_mode = str(state.get("output_mode") or "chat").strip().lower()
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    analysis_depth = str((ui_context or {}).get("analysis_depth") or "").strip().lower()
    if output_mode not in {"chat", "brief"} or analysis_depth == "deep_research":
        return "llm"

    operation_names = {
        str((task.get("operation") or {}).get("name") or "").strip().lower()
        for task in ready_tasks
        if isinstance(task.get("operation"), dict)
    }
    operation_names.discard("")
    if operation_names != {"price"}:
        has_url_task = any(
            isinstance(op.get("params"), dict)
            and str(op.get("params", {}).get("url") or "").startswith("http")
            for task in ready_tasks
            for op in [task.get("operation") if isinstance(task.get("operation"), dict) else {}]
        )
        if operation_names.issubset(SIMPLE_TASK_GRAPH_OPS) and (
            has_url_task
            or len(ready_tasks) >= 2
            or bool(operation_names & _EAGER_RULE_OPS)
        ):
            return "rule" if _all_subjects_plannable(ready_tasks) else "llm"

        router_decomposed = all(
            str(task.get("reason") or "").strip() in _ROUTER_DECOMPOSED_REASONS
            for task in ready_tasks
        )
        router_evidence_graph = (
            router_decomposed
            and operation_names.issubset(ROUTER_EVIDENCE_OPS)
            and (
                bool(operation_names & _ROUTER_GRAPH_TRIGGER_OPS)
                or len(operation_names) >= 2
            )
        )
        url_evidence_graph = (
            has_url_task
            and operation_names.issubset(URL_EVIDENCE_OPS)
            and len(ready_tasks) >= 2
        )
        if not router_evidence_graph and not url_evidence_graph:
            return "llm"

    return "rule" if _all_subjects_plannable(ready_tasks) else "llm"


__all__ = [
    "SIMPLE_TASK_GRAPH_OPS",
    "ROUTER_EVIDENCE_OPS",
    "URL_EVIDENCE_OPS",
    "PLANNABLE_SUBJECT_TYPES",
    "select_planner_lane",
]

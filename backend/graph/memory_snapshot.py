# -*- coding: utf-8 -*-
"""构造随 LangGraph checkpoint 保存的轻量会话上下文。"""
from __future__ import annotations

from typing import Any

from backend.graph.state import GraphState


_SUMMARY_MAX_LEN = 600
_REPORT_CONTEXT_MAX_LEN = 1200


def _compact_text(value: Any, *, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _ticker_from_state(state: GraphState) -> str | None:
    subject = state.get("subject") if isinstance(state.get("subject"), dict) else {}
    tickers = subject.get("tickers") if isinstance(subject, dict) else None
    if isinstance(tickers, list):
        for item in tickers:
            ticker = str(item or "").strip().upper()
            if ticker:
                return ticker
    return None


def _summary_from_artifacts(artifacts: dict[str, Any]) -> str:
    report = artifacts.get("report") if isinstance(artifacts.get("report"), dict) else {}
    synthesis = (
        artifacts.get("research_synthesis")
        if isinstance(artifacts.get("research_synthesis"), dict)
        else {}
    )
    render_vars = artifacts.get("render_vars") if isinstance(artifacts.get("render_vars"), dict) else {}
    for value in (
        report.get("summary"),
        synthesis.get("overall_conclusion"),
        render_vars.get("investment_summary"),
        render_vars.get("conclusion"),
        render_vars.get("analysis"),
        artifacts.get("draft_markdown"),
    ):
        summary = _compact_text(value, limit=_SUMMARY_MAX_LEN)
        if summary:
            return summary
    return ""


def _string_list(value: Any, *, limit: int, item_limit: int = 240) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = item.get("title") or item.get("text") or item.get("name")
        else:
            text = item
        normalized = _compact_text(text, limit=item_limit)
        if normalized:
            result.append(normalized)
        if len(result) >= limit:
            break
    return result


def _report_context(
    *,
    state: GraphState,
    artifacts: dict[str, Any],
    ticker: str | None,
    summary: str,
) -> dict[str, Any] | None:
    if str(state.get("output_mode") or "").strip().lower() != "investment_report":
        return None

    report = artifacts.get("report") if isinstance(artifacts.get("report"), dict) else {}
    synthesis = (
        artifacts.get("research_synthesis")
        if isinstance(artifacts.get("research_synthesis"), dict)
        else {}
    )
    render_vars = artifacts.get("render_vars") if isinstance(artifacts.get("render_vars"), dict) else {}
    task_results = synthesis.get("task_results") if isinstance(synthesis.get("task_results"), list) else []
    sections = report.get("sections") if isinstance(report.get("sections"), list) else task_results
    risks = report.get("risks") if isinstance(report.get("risks"), list) else synthesis.get("risks")
    title = _compact_text(report.get("title"), limit=160)
    if not title:
        query = _compact_text(state.get("query"), limit=120)
        title = f"{ticker} 研究报告" if ticker else query or "研究报告"

    context: dict[str, Any] = {
        "ticker": ticker,
        "title": title,
        "summary": _compact_text(report.get("summary") or summary, limit=_REPORT_CONTEXT_MAX_LEN),
        "section_titles": _string_list(sections, limit=8),
        "risks": _string_list(risks, limit=6),
    }
    for key, value in (
        ("report_id", report.get("report_id")),
        ("sentiment", report.get("sentiment") or render_vars.get("sentiment")),
        ("generated_at", report.get("generated_at")),
    ):
        normalized = _compact_text(value, limit=160)
        if normalized:
            context[key] = normalized
    return {key: value for key, value in context.items() if value not in (None, "", [])}


def build_checkpoint_memory(
    *,
    state: GraphState,
    rendered_artifacts: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """为当前 thread 构造上下文；不访问文件、网络或第二套数据库。"""
    artifacts = rendered_artifacts if isinstance(rendered_artifacts, dict) else {}
    subject = state.get("subject") if isinstance(state.get("subject"), dict) else {}
    subject_type = str(subject.get("subject_type") or "unknown").strip().lower()
    ticker = _ticker_from_state(state)
    summary = _summary_from_artifacts(artifacts)
    report = _report_context(state=state, artifacts=artifacts, ticker=ticker, summary=summary)

    # 问候和无法绑定对象的普通回复不应覆盖上一轮有效焦点。
    if subject_type == "unknown" and report is None:
        return None
    query = _compact_text(state.get("query"), limit=500)
    if not query and not ticker and not summary and report is None:
        return None

    existing = state.get("memory_context") if isinstance(state.get("memory_context"), dict) else {}
    memory = dict(existing)
    focus: dict[str, Any] = {
        "ticker": ticker,
        "query": query,
        "summary": summary,
    }
    previous_report = existing.get("current_report") if isinstance(existing.get("current_report"), dict) else None
    current_report = report or previous_report
    if current_report:
        focus["last_report"] = current_report
        memory["current_report"] = current_report
    memory["current_thread_focus"] = {
        key: value for key, value in focus.items() if value not in (None, "", [])
    }
    return memory


__all__ = ["build_checkpoint_memory"]

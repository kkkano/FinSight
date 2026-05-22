# -*- coding: utf-8 -*-
"""Structured request/reply contract for chat UX routing.

This module is intentionally small and independent of LangGraph nodes.  It
defines the stable vocabulary shared by understanding, policy, planning,
execution diagnostics, and rendering.
"""
from __future__ import annotations

import re
from typing import Any, Literal, TypedDict

from backend.graph.memory_scope import current_report_context

Lane = Literal["chat_answer", "source_grounded_answer", "report_generation"]
CitationPolicy = Literal["none", "cite_if_available", "must_cite_or_disclose_unavailable"]

LANE_CHAT_ANSWER: Lane = "chat_answer"
LANE_SOURCE_GROUNDED_ANSWER: Lane = "source_grounded_answer"
LANE_REPORT_GENERATION: Lane = "report_generation"

CITATION_NONE: CitationPolicy = "none"
CITATION_IF_AVAILABLE: CitationPolicy = "cite_if_available"
CITATION_MUST_CITE_OR_DISCLOSE: CitationPolicy = "must_cite_or_disclose_unavailable"

NEWS_TOOL_NAMES = frozenset(
    {
        "get_company_news",
        "get_event_calendar",
        "get_authoritative_media_news",
        "score_news_source_reliability",
        "get_earnings_call_transcripts",
    }
)

SOURCE_OPERATION_NAMES = frozenset(
    {
        "price",
        "fetch",
        "news_impact",
        "technical",
        "investment_opinion",
        "earnings_impact",
        "earnings_performance",
        "daily_brief",
        "fact_check",
        "company_info",
        "fundamental",
        "morning_brief",
    }
)

ERROR_STATUSES = frozenset(
    {
        "error",
        "failed",
        "failure",
        "rejected",
        "empty",
        "timeout",
        "cancelled",
        "blocked",
        "forbidden",
        "unauthorized",
        "not_found",
        "skipped",
    }
)

_URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+", re.IGNORECASE)


class SourceConstraints(TypedDict, total=False):
    requires_sources: bool
    requires_links: bool
    requires_realtime: bool
    requires_url_fetch: bool
    disallow_news: bool
    diagnostics_allowed: bool


class ReplyContract(TypedDict, total=False):
    lane: Lane
    answer_style: str
    length_preference: str
    context_binding: dict[str, Any]
    source_constraints: SourceConstraints
    citation_policy: CitationPolicy
    continuation_target: dict[str, Any]


class EvidenceItem(TypedDict, total=False):
    title: str
    url: str | None
    snippet: str | None
    source: str
    published_date: str | None
    confidence: float
    type: str
    id: str
    step_id: str
    task_ids: list[str]
    claim_id: str
    source_id: str
    stance: str
    as_of: str | None
    reliability: float
    layer: str
    collection: str
    limitations: list[str]


class ToolError(TypedDict, total=False):
    tool_name: str
    step_id: str
    task_ids: list[str]
    status: str
    reason_code: str
    message: str
    url: str
    retryable: bool
    raw: dict[str, Any]


def _lower_text(value: object) -> str:
    return str(value or "").strip().lower()


def _contains_any(text: str, tokens: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(token.lower() in lowered for token in tokens)


def _task_operation_name(task: dict[str, Any]) -> str:
    operation = task.get("operation")
    if isinstance(operation, dict):
        name = operation.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip().lower()
    return "qa"


def _task_operation_params(task: dict[str, Any]) -> dict[str, Any]:
    operation = task.get("operation")
    if not isinstance(operation, dict):
        return {}
    params = operation.get("params")
    return params if isinstance(params, dict) else {}


def _tasks_require_url_fetch(tasks: list[dict[str, Any]]) -> bool:
    for task in tasks:
        params = _task_operation_params(task)
        if str(params.get("url") or "").startswith(("http://", "https://")):
            return True
        raw_urls = params.get("urls")
        if isinstance(raw_urls, list) and any(str(url or "").startswith(("http://", "https://")) for url in raw_urls):
            return True
    return False


def _tasks_require_sources(tasks: list[dict[str, Any]]) -> bool:
    for task in tasks:
        if _task_operation_name(task) in SOURCE_OPERATION_NAMES:
            return True
        params = _task_operation_params(task)
        if params.get("include_links") or params.get("url") or params.get("urls"):
            return True
    return False


def _tasks_require_links(tasks: list[dict[str, Any]]) -> bool:
    for task in tasks:
        params = _task_operation_params(task)
        op_name = _task_operation_name(task)
        if params.get("include_links") or params.get("url") or params.get("urls"):
            return True
        if op_name in {"fetch", "news_impact"}:
            return True
    return False


def wants_no_news_or_links(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    if re.search(
        r"\b(?:do\s+not|don't|dont|never|please\s+do\s+not|please\s+don't)\s+"
        r"(?:look\s+up|lookup|search|fetch|use|cite|include|show)\s+"
        r"(?:the\s+)?(?:latest\s+)?(?:news|headlines?|links?|sources?|citations?)\b",
        lowered,
    ):
        return True
    return _contains_any(
        text,
        (
            "no news",
            "without news",
            "no links",
            "without links",
            "no source",
            "no sources",
            "without source",
            "without sources",
            "no citation",
            "no citations",
            "no news lookup",
            "no news search",
            "no source lookup",
            "no source search",
            "forget the latest headlines",
            "forget latest headlines",
            "ignore the latest headlines",
            "ignore latest headlines",
            "不要新闻",
            "不要链接",
            "别找新闻",
            "不用新闻",
            "不用链接",
            "直接说原因",
            "像聊天一样",
        ),
    )


def query_explicitly_requests_sources(query: str) -> bool:
    return _contains_any(
        query,
        (
            "latest news",
            "headline link",
            "headline with link",
            "news with links",
            "with links",
            "with link",
            "source",
            "sources",
            "citation",
            "cite",
            "url",
            "current price",
            "real-time",
            "realtime",
            "right now",
            "now?",
            "trading at now",
            "最新新闻",
            "带链接",
            "链接",
            "来源",
            "引用",
            "现在",
            "实时",
            "多少钱",
            "股价",
            "报价",
        ),
    )


def query_explicitly_requests_links(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    if re.search(r"\b(?:links?|urls?|citations?)\b", lowered):
        return True
    return _contains_any(
        text,
        (
            "source link",
            "source links",
            "news link",
            "news links",
            "headline link",
            "headline links",
            "带链接",
            "链接",
        ),
    )


def build_reply_contract(
    *,
    query: str,
    output_mode: str,
    tasks: list[dict[str, Any]] | None,
    blocked_tasks: list[dict[str, Any]] | None = None,
    conversation_decision: Any = None,
    memory_context: dict[str, Any] | None = None,
) -> ReplyContract:
    task_rows = [task for task in (tasks or []) if isinstance(task, dict)]
    query_text = str(query or "")
    output_mode_text = str(output_mode or "chat").strip().lower()
    disallow_news = wants_no_news_or_links(query_text)
    has_url = bool(_URL_RE.search(query_text)) or _tasks_require_url_fetch(task_rows)
    explicit_sources = query_explicitly_requests_sources(query_text)
    explicit_links = query_explicitly_requests_links(query_text)
    task_sources = _tasks_require_sources(task_rows)
    task_links = _tasks_require_links(task_rows)

    if output_mode_text == "investment_report":
        lane: Lane = LANE_REPORT_GENERATION
    elif disallow_news:
        lane = LANE_CHAT_ANSWER
    elif has_url or explicit_sources or task_links or any(_task_operation_name(task) in {"price", "fetch", "daily_brief", "investment_opinion", "earnings_impact", "earnings_performance"} for task in task_rows):
        lane = LANE_SOURCE_GROUNDED_ANSWER
    else:
        lane = LANE_CHAT_ANSWER

    if lane == LANE_REPORT_GENERATION:
        answer_style = "investment_report"
        citation_policy: CitationPolicy = CITATION_MUST_CITE_OR_DISCLOSE
    elif lane == LANE_SOURCE_GROUNDED_ANSWER:
        answer_style = "grounded_concise"
        citation_policy = CITATION_MUST_CITE_OR_DISCLOSE
    else:
        answer_style = "natural_chat"
        citation_policy = CITATION_NONE

    if output_mode_text == "brief":
        length_preference = "short"
    elif lane == LANE_REPORT_GENERATION:
        length_preference = "long"
    else:
        length_preference = "normal"

    binding: dict[str, Any] = {}
    raw_binding = getattr(conversation_decision, "context_binding", None)
    if raw_binding is not None and hasattr(raw_binding, "model_dump"):
        binding = raw_binding.model_dump()
    elif isinstance(raw_binding, dict):
        binding = dict(raw_binding)

    continuation_target: dict[str, Any] = {}
    if str(binding.get("source") or "").strip() == "last_report":
        last_report = current_report_context(memory_context)
    else:
        last_report = None
    if isinstance(last_report, dict):
        continuation_target = {
            "type": "last_report",
            "report_id": last_report.get("report_id"),
            "ticker": last_report.get("ticker"),
            "title": last_report.get("title"),
        }

    source_constraints: SourceConstraints = {
        "requires_sources": bool(lane in {LANE_SOURCE_GROUNDED_ANSWER, LANE_REPORT_GENERATION} and (task_sources or explicit_sources or has_url)),
        "requires_links": False
        if disallow_news
        else bool(task_links or has_url or explicit_links),
        "requires_realtime": bool(
            any(_task_operation_name(task) == "price" for task in task_rows)
            or any(_task_operation_name(task) in {"daily_brief", "investment_opinion", "earnings_impact", "earnings_performance"} for task in task_rows)
            or _contains_any(query_text, ("real-time", "realtime", "right now", "trading at now", "现在", "实时", "多少钱", "报价"))
        ),
        "requires_url_fetch": has_url,
        "disallow_news": disallow_news,
        "diagnostics_allowed": True,
    }

    return {
        "lane": lane,
        "answer_style": answer_style,
        "length_preference": length_preference,
        "context_binding": binding,
        "source_constraints": source_constraints,
        "citation_policy": citation_policy,
        "continuation_target": continuation_target,
    }


def reply_contract_lane(state: dict[str, Any]) -> str:
    contract = state.get("reply_contract")
    if not isinstance(contract, dict):
        return ""
    return str(contract.get("lane") or "").strip()


def reply_contract_disallows_news(state: dict[str, Any]) -> bool:
    contract = state.get("reply_contract")
    if not isinstance(contract, dict):
        return False
    constraints = contract.get("source_constraints")
    return bool(isinstance(constraints, dict) and constraints.get("disallow_news"))


def output_is_error_like(output: Any) -> bool:
    if output is None:
        return False
    if isinstance(output, str):
        text = output.strip().lower()
        return bool(text) and any(token in text for token in ("403 forbidden", "401 unauthorized", "timeout", "rejected"))
    if not isinstance(output, dict):
        return False
    if output.get("skipped"):
        return True
    status = _lower_text(output.get("status") or output.get("state"))
    if status in ERROR_STATUSES:
        return True
    if output.get("error") or output.get("error_message"):
        return True
    if output.get("rejected") is True:
        return True
    return False


def classify_tool_error(output: Any) -> tuple[str, str, bool]:
    text = ""
    status = "failed"
    if isinstance(output, dict):
        status = str(output.get("status") or output.get("state") or "failed").strip().lower() or "failed"
        text = str(
            output.get("error")
            or output.get("error_message")
            or output.get("reason")
            or output.get("message")
            or status
        )
    else:
        text = str(output or "")
    lowered = text.lower()
    if "403" in lowered or "forbidden" in lowered:
        return status, "access_denied", False
    if "401" in lowered or "unauthorized" in lowered:
        return status, "unauthorized", False
    if "timeout" in lowered or status == "timeout":
        return status, "timeout", True
    if "reject" in lowered or status == "rejected":
        return status, "rejected", False
    if status == "empty":
        return status, "empty", True
    if status in ERROR_STATUSES:
        return status, status, status not in {"rejected", "forbidden", "unauthorized"}
    return status, "tool_error", True


def build_tool_diagnostic(
    *,
    tool_name: str,
    step_id: str,
    task_ids: list[str],
    output: Any,
) -> ToolError:
    status, reason_code, retryable = classify_tool_error(output)
    message = ""
    url = ""
    raw: dict[str, Any] = {}
    if isinstance(output, dict):
        message = str(
            output.get("error")
            or output.get("error_message")
            or output.get("reason")
            or output.get("message")
            or status
        )
        url = str(output.get("url") or output.get("final_url") or "").strip()
        raw = dict(output)
    else:
        message = str(output or status)
    diagnostic: ToolError = {
        "tool_name": str(tool_name),
        "step_id": str(step_id),
        "task_ids": list(task_ids or []),
        "status": status,
        "reason_code": reason_code,
        "message": message[:500],
        "retryable": retryable,
    }
    if url:
        diagnostic["url"] = url
    if raw:
        diagnostic["raw"] = raw
    return diagnostic


__all__ = [
    "CITATION_IF_AVAILABLE",
    "CITATION_MUST_CITE_OR_DISCLOSE",
    "CITATION_NONE",
    "EvidenceItem",
    "LANE_CHAT_ANSWER",
    "LANE_REPORT_GENERATION",
    "LANE_SOURCE_GROUNDED_ANSWER",
    "NEWS_TOOL_NAMES",
    "ReplyContract",
    "ToolError",
    "build_reply_contract",
    "build_tool_diagnostic",
    "output_is_error_like",
    "query_explicitly_requests_links",
    "query_explicitly_requests_sources",
    "reply_contract_disallows_news",
    "reply_contract_lane",
]

# -*- coding: utf-8 -*-
"""Canonical request frame compiler.

The request frame is the semantic source of truth above legacy operations.  It
separates user-facing product lane, subject/relation, research evidence
obligations, and deterministic workflow actions.
"""
from __future__ import annotations

import re
from typing import Any, Literal, NotRequired, TypedDict

from backend.config.ticker_mapping import dedup_tickers, extract_tickers, normalize_ticker
from backend.graph.intent_contract import (
    canonical_evidence_kinds,
    derive_intent_contract,
    legacy_operation_for_contract,
)


RequestLane = Literal["answer", "research", "action", "report", "clarify", "reject"]
RelationKind = Literal["single", "compare", "rank", "impact", "continuation", "none"]
WorkflowActionName = Literal["backtest", "alert", "screen", "holdings", "fetch_url"]


class WorkflowAction(TypedDict, total=False):
    name: WorkflowActionName
    slots: dict[str, Any]
    required_results: list[str]


class RequestFrame(TypedDict, total=False):
    version: str
    frame_id: str
    lane: RequestLane
    relation: RelationKind
    subject: dict[str, Any]
    evidence_obligations: list[str]
    required_results: list[str]
    workflow_action: NotRequired[WorkflowAction]
    render_contract: dict[str, Any]
    intent_contract: NotRequired[dict[str, Any]]
    legacy_operation: dict[str, Any]
    source: str
    reason: str


_FRAME_VERSION = "request_frame.v1"
_BACKTEST_ACTION_RE = re.compile(r"(?<![a-z0-9])(?:back[\s-]?test(?:ing)?|run\s+a?\s*backtest|strategy\s+backtest)(?![a-z0-9])", re.IGNORECASE)
_BACKTEST_DEFINITION_RE = re.compile(
    r"^\s*(?:what\s+is|what's|explain|meaning\s+of|define|how\s+does)\s+(?:a\s+)?back[\s-]?test(?:ing)?\??\s*$",
    re.IGNORECASE,
)
_FRAME_SPLIT_RE = re.compile(
    r"[\u3001,\uff0c;\uff1b\u3002.!?\uff1f\uff01]+"
    r"|\b(?:and|then|also)\b"
    r"|(?:\u7136\u540e|\u518d|\u4ee5\u53ca|\u5e76\u4e14)",
    re.IGNORECASE,
)
_PRICE_HINT_RE = re.compile(r"\b(?:price|quote|trading|current)\b|\u4ef7\u683c|\u80a1\u4ef7|\u884c\u60c5", re.IGNORECASE)
_NEWS_HINT_RE = re.compile(r"\b(?:news|headline|headlines|latest)\b|\u65b0\u95fb|\u6d88\u606f", re.IGNORECASE)
_TECHNICAL_HINT_RE = re.compile(r"\b(?:technical|rsi|macd|support|resistance)\b|\u6280\u672f|\u5747\u7ebf", re.IGNORECASE)
_MACRO_HINT_RE = re.compile(
    r"\b(?:fed|fomc|rate|rates|inflation|cpi|ppi|macro)\b|\u5229\u7387|\u7f8e\u8054\u50a8|\u5b8f\u89c2|\u901a\u80c0",
    re.IGNORECASE,
)


def _normalized_tickers(tickers: list[str] | tuple[str, ...] | None) -> list[str]:
    return dedup_tickers([normalize_ticker(str(ticker)) for ticker in (tickers or []) if str(ticker).strip()])


def _strategy_slot(query: str) -> str:
    lowered = str(query or "").lower()
    if "macd" in lowered:
        return "macd"
    if re.search(r"(?<![a-z0-9])rsi(?![a-z0-9])", lowered):
        return "rsi_mean_reversion"
    if any(token in lowered for token in ("sma", "moving average", "ma cross", "ma_cross", "crossover")):
        return "ma_cross"
    return "ma_cross"


def _requests_backtest_action(query: str, tickers: list[str]) -> bool:
    text = str(query or "").strip()
    if not text:
        return False
    if _BACKTEST_DEFINITION_RE.search(text):
        return False
    if not tickers:
        return False
    return bool(_BACKTEST_ACTION_RE.search(text))


def _domain_intent_for_fragment(fragment: str, *, subject_type: str) -> str:
    if _PRICE_HINT_RE.search(fragment):
        return "quote"
    if _NEWS_HINT_RE.search(fragment):
        return "news"
    if _TECHNICAL_HINT_RE.search(fragment):
        return "technical"
    if subject_type == "macro" or _MACRO_HINT_RE.search(fragment):
        return "macro"
    return ""


def _fragment_subject_type(fragment: str, fragment_tickers: list[str]) -> str:
    if fragment_tickers:
        return "company"
    if _MACRO_HINT_RE.search(fragment):
        return "macro"
    return "unknown"


def _relation_for_contract(contract: dict[str, Any]) -> RelationKind:
    render = contract.get("render_intent") if isinstance(contract, dict) else {}
    dimensions = render.get("dimensions") if isinstance(render, dict) else []
    facets = {str(f) for f in (contract.get("facets") or []) if str(f).strip()}
    if isinstance(render, dict) and render.get("shape") == "compare":
        if dimensions and any(str(dim).endswith("_reasonableness") or str(dim).endswith("_quality") for dim in dimensions):
            return "rank"
        return "compare"
    if "external_entity_impact" in facets:
        return "impact"
    return "single" if contract.get("target_scope") != "unknown" else "none"


def _subject(subject_type: str, tickers: list[str]) -> dict[str, Any]:
    return {
        "type": str(subject_type or "unknown").strip().lower() or "unknown",
        "tickers": list(tickers),
    }


def _backtest_frame(
    *,
    query: str,
    tickers: list[str],
    subject_type: str,
    frame_id: str,
) -> RequestFrame:
    ticker = tickers[0]
    strategy = _strategy_slot(query)
    operation = {
        "name": "backtest",
        "confidence": 0.9,
        "params": {
            "workflow_action": "backtest",
            "strategy": strategy,
            "required_results": ["backtest_result"],
        },
    }
    return {
        "version": _FRAME_VERSION,
        "frame_id": frame_id,
        "lane": "action",
        "relation": "single",
        "subject": _subject(subject_type, [ticker]),
        "evidence_obligations": [],
        "required_results": ["backtest_result"],
        "workflow_action": {
            "name": "backtest",
            "slots": {"ticker": ticker, "strategy": strategy, "params": {}},
            "required_results": ["backtest_result"],
        },
        "render_contract": {"shape": "action_result", "artifact": "backtest_result"},
        "legacy_operation": operation,
        "source": "deterministic_request_frame",
        "reason": "workflow action compiled before research facets or legacy operation",
    }


def compile_request_frame(
    *,
    query: str,
    tickers: list[str] | tuple[str, ...] | None,
    output_mode: str,
    comparison_requested: bool = False,
    domain_intent: str = "",
    subject_type: str = "company",
    frame_id: str = "frame_1",
) -> RequestFrame:
    normalized = _normalized_tickers(tickers)
    subject = str(subject_type or "company").strip().lower() or "company"
    if _requests_backtest_action(query, normalized):
        return _backtest_frame(query=query, tickers=normalized, subject_type=subject, frame_id=frame_id)

    contract = derive_intent_contract(
        query=query,
        tickers=normalized,
        output_mode=output_mode,
        comparison_requested=comparison_requested,
        domain_intent=domain_intent,
        subject_type=subject,
        frame_id=frame_id,
    )
    required = canonical_evidence_kinds(contract.get("required_evidence") if isinstance(contract.get("required_evidence"), list) else [])
    render = contract.get("render_intent") if isinstance(contract.get("render_intent"), dict) else {}
    mode = str(output_mode or "").strip().lower()
    lane: RequestLane
    if mode == "investment_report":
        lane = "report"
    elif required or render.get("shape") == "compare":
        lane = "research"
    else:
        lane = "answer"
    return {
        "version": _FRAME_VERSION,
        "frame_id": frame_id,
        "lane": lane,
        "relation": _relation_for_contract(contract),
        "subject": _subject(subject, list(contract.get("primary_tickers") or normalized)),
        "evidence_obligations": required,
        "required_results": [],
        "render_contract": dict(render),
        "intent_contract": dict(contract),
        "legacy_operation": legacy_operation_for_contract(contract, subject_type=subject),
        "source": "deterministic_request_frame",
        "reason": "request frame compiled from query/resolved subjects before legacy operation projection",
    }


def compile_request_frames(
    *,
    query: str,
    tickers: list[str] | tuple[str, ...] | None,
    output_mode: str,
) -> list[RequestFrame]:
    """Compile simple compound user turns into independent request frames.

    This is intentionally conservative.  It only splits on clear separators and
    keeps frames that have a concrete subject or a macro topic plus evidence
    signal.  More ambiguous decomposition remains the router's job.
    """
    raw_query = str(query or "").strip()
    if not raw_query:
        return []
    fragments = [part.strip() for part in _FRAME_SPLIT_RE.split(raw_query) if part.strip()]
    if len(fragments) < 2:
        return []

    known_tickers = set(_normalized_tickers(tickers))
    frames: list[RequestFrame] = []
    for idx, fragment in enumerate(fragments, 1):
        fragment_tickers = _normalized_tickers(extract_tickers(fragment).get("tickers") or [])
        if not fragment_tickers and len(known_tickers) == 1 and any(
            regex.search(fragment) for regex in (_PRICE_HINT_RE, _NEWS_HINT_RE, _TECHNICAL_HINT_RE)
        ):
            fragment_tickers = list(known_tickers)
        subject_type = _fragment_subject_type(fragment, fragment_tickers)
        domain_intent = _domain_intent_for_fragment(fragment, subject_type=subject_type)
        if subject_type == "unknown" or not domain_intent:
            continue
        frame = compile_request_frame(
            query=fragment,
            tickers=fragment_tickers,
            output_mode=output_mode,
            comparison_requested=False,
            domain_intent=domain_intent,
            subject_type=subject_type,
            frame_id=f"query_frame_{idx}",
        )
        if frame.get("lane") == "answer" and not frame.get("workflow_action"):
            continue
        frames.append(frame)
    return frames if len(frames) >= 2 else []


__all__ = [
    "RequestFrame",
    "WorkflowAction",
    "compile_request_frame",
    "compile_request_frames",
]

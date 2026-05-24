# -*- coding: utf-8 -*-
"""Canonical request frame compiler.

The request frame is the semantic source of truth above legacy operations.  It
separates user-facing product lane, subject/relation, research evidence
obligations, and deterministic workflow actions.
"""
from __future__ import annotations

import re
from typing import Any, Literal, NotRequired, TypedDict

from backend.config.ticker_mapping import dedup_tickers, normalize_ticker
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


__all__ = [
    "RequestFrame",
    "WorkflowAction",
    "compile_request_frame",
]

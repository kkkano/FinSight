# -*- coding: utf-8 -*-
"""Thin request intent contract.

The legacy ``operation`` field is still the compatibility label used by many
nodes.  This module adds a smaller execution contract that states the evidence
the graph must collect before rendering an answer.  It intentionally avoids a
large intent tree; facets are semantic buckets that map to evidence obligations.
"""
from __future__ import annotations

import os
import re
from typing import Any, NotRequired, TypedDict

from backend.config.ticker_mapping import dedup_tickers, normalize_ticker
from backend.graph.earnings_intent import (
    query_requests_earnings_performance,
    query_requests_earnings_price_impact,
)
from backend.graph.investment_intent import query_requests_investment_opinion


class RenderIntent(TypedDict, total=False):
    shape: str
    dimensions: list[str]


class IntentContract(TypedDict, total=False):
    version: str
    primary_operation: str
    target_scope: str
    primary_tickers: list[str]
    omitted_tickers: NotRequired[list[str]]
    facets: list[str]
    per_ticker_required: bool
    render_intent: RenderIntent
    required_evidence: list[str]
    budget_profile: str
    source: str
    reason: str


_CONTRACT_VERSION = "intent_contract.v1"
_HIGH_ORDER_FACETS = {"valuation", "risk", "trend", "earnings", "investment_opinion"}


def chat_multi_ticker_research_limit() -> int:
    raw = os.getenv("FINSIGHT_CHAT_MULTI_TICKER_RESEARCH_LIMIT")
    if not isinstance(raw, str) or not raw.strip():
        return 3
    try:
        value = int(raw.strip())
    except Exception:
        return 3
    return max(1, min(10, value))


def _normalized_tickers(tickers: list[str] | tuple[str, ...] | None) -> list[str]:
    return dedup_tickers([normalize_ticker(str(ticker)) for ticker in (tickers or []) if str(ticker).strip()])


def _has_valuation_facet(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    return bool(
        "估值" in text
        or "valuation" in lowered
        or "multiple" in lowered
        or re.search(r"(?<![a-z0-9])(pe|p/e|peg|ev/ebitda)(?![a-z0-9])", lowered)
    )


def _has_risk_facet(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    return bool("风险" in text or "risk" in lowered or "drawdown" in lowered or "downside" in lowered)


def _has_trend_facet(query: str) -> bool:
    text = str(query or "")
    lowered = text.lower()
    return bool(
        "走势" in text
        or "趋势" in text
        or "后市" in text
        or "trend" in lowered
        or "outlook" in lowered
    )


def _derive_facets(query: str, *, domain_intent: str = "") -> list[str]:
    facets: list[str] = []
    if _has_valuation_facet(query):
        facets.append("valuation")
    if query_requests_earnings_price_impact(query) or query_requests_earnings_performance(query):
        facets.append("earnings")
    if _has_risk_facet(query):
        facets.append("risk")
    if _has_trend_facet(query):
        facets.append("trend")
    if query_requests_investment_opinion(query) or domain_intent == "investment_opinion":
        facets.append("investment_opinion")
    return list(dict.fromkeys(facets))


def _required_evidence_for_facets(facets: list[str], *, per_ticker_required: bool) -> list[str]:
    evidence: list[str] = []
    facet_set = set(facets)
    if "valuation" in facet_set:
        evidence.extend(
            [
                "price_by_ticker",
                "company_info_by_ticker",
                "earnings_estimates_by_ticker",
                "fundamental_snapshot_by_ticker",
            ]
        )
    if "earnings" in facet_set:
        evidence.extend(["company_info_by_ticker", "earnings_estimates_by_ticker", "earnings_news_by_ticker"])
    if "risk" in facet_set:
        evidence.extend(["price_by_ticker", "risk_profile_by_ticker"])
    if "trend" in facet_set or "investment_opinion" in facet_set:
        evidence.extend(["price_by_ticker", "technical_snapshot_by_ticker", "news_by_ticker"])
    if not per_ticker_required:
        evidence.append("comparison_table")
    return list(dict.fromkeys(evidence))


def _comparison_dimensions(facets: list[str]) -> list[str]:
    dims: list[str] = []
    for facet in facets:
        if facet == "valuation":
            dims.append("valuation_reasonableness")
        elif facet == "risk":
            dims.append("risk_level")
        elif facet == "earnings":
            dims.append("earnings_impact")
        elif facet == "trend":
            dims.append("trend_quality")
        elif facet == "investment_opinion":
            dims.append("investment_attractiveness")
    return dims or ["performance"]


def derive_intent_contract(
    *,
    query: str,
    tickers: list[str] | tuple[str, ...] | None,
    output_mode: str,
    comparison_requested: bool = False,
    domain_intent: str = "",
    lightweight_requested: bool = False,
) -> IntentContract:
    normalized = _normalized_tickers(list(tickers or []))
    target_scope = "multi" if len(normalized) >= 2 else ("single" if len(normalized) == 1 else "unknown")
    facets = _derive_facets(query, domain_intent=domain_intent)
    if comparison_requested and not facets:
        facets = ["price_performance"]

    per_ticker_required = bool(
        target_scope == "multi"
        and comparison_requested
        and set(facets).intersection(_HIGH_ORDER_FACETS)
        and (not lightweight_requested or "valuation" in facets)
    )
    limit = chat_multi_ticker_research_limit() if str(output_mode or "").strip().lower() == "chat" else 10
    primary_tickers = normalized[:limit] if per_ticker_required else normalized
    omitted_tickers = normalized[limit:] if per_ticker_required else []
    shape = "compare" if comparison_requested and target_scope == "multi" else "answer"

    primary_operation = "research" if per_ticker_required else ("compare" if shape == "compare" else "qa")
    if "investment_opinion" in facets and per_ticker_required:
        budget_profile = "investment_opinion_compare"
    elif "valuation" in facets and per_ticker_required:
        budget_profile = "valuation_compare_light"
    elif per_ticker_required:
        budget_profile = "per_ticker_compare"
    else:
        budget_profile = "light_compare" if shape == "compare" else "default"

    contract: IntentContract = {
        "version": _CONTRACT_VERSION,
        "primary_operation": primary_operation,
        "target_scope": target_scope,
        "primary_tickers": primary_tickers,
        "facets": facets,
        "per_ticker_required": per_ticker_required,
        "render_intent": {"shape": shape, "dimensions": _comparison_dimensions(facets)},
        "required_evidence": _required_evidence_for_facets(facets, per_ticker_required=per_ticker_required),
        "budget_profile": budget_profile,
        "source": "deterministic_semantic_facets",
        "reason": "semantic evidence obligations are separated from the legacy operation label",
    }
    if omitted_tickers:
        contract["omitted_tickers"] = omitted_tickers
    return contract


def requires_per_ticker_research(contract: dict[str, Any] | None) -> bool:
    return bool(isinstance(contract, dict) and contract.get("per_ticker_required"))


def is_valuation_contract(contract: dict[str, Any] | None) -> bool:
    facets = contract.get("facets") if isinstance(contract, dict) else None
    return isinstance(facets, list) and "valuation" in {str(f) for f in facets}


def evidence_focused_operation(contract: dict[str, Any] | None) -> dict[str, Any]:
    facets = contract.get("facets") if isinstance(contract, dict) else []
    required = contract.get("required_evidence") if isinstance(contract, dict) else []
    if isinstance(facets, list) and "valuation" in {str(f) for f in facets}:
        return {
            "name": "investment_opinion",
            "confidence": 0.86,
            "params": {
                "evidence_focus": "valuation",
                "facets": ["valuation"],
                "required_evidence": list(required or []),
            },
        }
    return {
        "name": "investment_opinion",
        "confidence": 0.84,
        "params": {
            "evidence_focus": "investment_opinion",
            "facets": [str(f) for f in facets if str(f).strip()],
            "required_evidence": list(required or []),
        },
    }


def synthesis_compare_operation(contract: dict[str, Any] | None) -> dict[str, Any]:
    render_intent = contract.get("render_intent") if isinstance(contract, dict) else {}
    dimensions = render_intent.get("dimensions") if isinstance(render_intent, dict) else []
    facets = contract.get("facets") if isinstance(contract, dict) else []
    return {
        "name": "compare",
        "confidence": 0.86,
        "params": {
            "synthesis_only": True,
            "data_profile": "research_synthesis",
            "comparison_dimensions": list(dimensions or []),
            "facets": [str(f) for f in facets if str(f).strip()],
        },
    }


__all__ = [
    "IntentContract",
    "derive_intent_contract",
    "evidence_focused_operation",
    "is_valuation_contract",
    "requires_per_ticker_research",
    "synthesis_compare_operation",
]

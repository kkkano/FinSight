# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any


def _operation_name(operation: dict[str, Any] | None) -> str:
    if not isinstance(operation, dict):
        return "qa"
    return str(operation.get("name") or "qa").strip() or "qa"


def _primary_asset(subject: dict[str, Any] | None) -> str:
    if not isinstance(subject, dict):
        return ""
    tickers = subject.get("tickers")
    if isinstance(tickers, list) and tickers:
        return str(tickers[0] or "").strip().upper()
    return ""


def _market_from_asset(asset: str) -> str:
    symbol = str(asset or "").strip().upper()
    if symbol.endswith((".SS", ".SZ", ".BJ")):
        return "CN"
    if symbol.endswith(".HK"):
        return "HK"
    if symbol:
        return "US"
    return ""


def derive_request_facets(
    *,
    query: str,
    operation: dict[str, Any] | None,
    subject: dict[str, Any] | None,
) -> dict[str, Any]:
    del query
    op_name = _operation_name(operation)
    params = operation.get("params") if isinstance(operation, dict) and isinstance(operation.get("params"), dict) else {}
    asset = _primary_asset(subject)
    facets: dict[str, Any] = {
        "asset": asset,
        "market": _market_from_asset(asset),
        "operation": op_name,
        "primary_task": "qa",
        "analysis_need": [],
    }

    if op_name == "price":
        facets.update(
            {
                "primary_task": "price_lookup",
                "target_metric": "stock_price",
                "analysis_need": ["price"],
            }
        )
    elif op_name == "technical":
        facets.update(
            {
                "primary_task": "technical_analysis",
                "target_metric": "price_action",
                "analysis_need": ["technical", "price"],
            }
        )
    elif op_name == "earnings_impact":
        facets.update(
            {
                "primary_task": "impact_analysis",
                "event_type": params.get("event_type") or "earnings",
                "target_metric": params.get("target_metric") or "stock_price",
                "analysis_need": ["fundamental", "news", "risk", "price"],
            }
        )
    elif op_name == "earnings_performance":
        facets.update(
            {
                "primary_task": "earnings_analysis",
                "event_type": "earnings",
                "target_metric": "financial_performance",
                "analysis_need": ["fundamental", "news"],
            }
        )
    elif op_name == "investment_opinion":
        facets.update(
            {
                "primary_task": "investment_opinion",
                "target_metric": "stock_price",
                "analysis_need": ["fundamental", "technical", "news", "risk", "price"],
            }
        )
    elif op_name == "valuation_sanity":
        facets.update(
            {
                "primary_task": "valuation_analysis",
                "target_metric": "valuation",
                "analysis_need": ["fundamental", "technical", "risk", "price"],
            }
        )
    elif op_name in {"fetch", "news_impact"}:
        facets.update(
            {
                "primary_task": "news_research",
                "target_metric": "news",
                "analysis_need": ["news"],
            }
        )

    required_dimensions = params.get("required_dimensions")
    if isinstance(required_dimensions, list) and required_dimensions:
        facets["required_dimensions"] = [str(item) for item in required_dimensions if str(item).strip()]
    return facets

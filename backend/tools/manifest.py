# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ToolManifestEntry:
    name: str
    group: str
    markets: tuple[str, ...]
    operations: tuple[str, ...]
    depths: tuple[str, ...]
    risk_level: str
    timeout_ms: int
    cache_ttl_s: int
    requires_env: tuple[str, ...] = ()
    default_enabled: bool = True


TOOL_MANIFEST: tuple[ToolManifestEntry, ...] = (
    ToolManifestEntry(
        name="get_stock_price",
        group="market",
        markets=("US", "CN"),
        operations=("price", "technical", "qa", "generate_report"),
        depths=("quick", "report", "deep_research"),
        risk_level="low",
        timeout_ms=10000,
        cache_ttl_s=30,
    ),
    ToolManifestEntry(
        name="get_technical_snapshot",
        group="technical",
        markets=("US", "CN"),
        operations=("technical", "qa", "generate_report"),
        depths=("quick", "report", "deep_research"),
        risk_level="low",
        timeout_ms=12000,
        cache_ttl_s=60,
    ),
    ToolManifestEntry(
        name="get_option_chain_metrics",
        group="derivatives",
        markets=("US",),
        operations=("price", "technical", "qa", "generate_report"),
        depths=("quick", "report", "deep_research"),
        risk_level="medium",
        timeout_ms=12000,
        cache_ttl_s=300,
    ),
    ToolManifestEntry(
        name="get_sec_filings",
        group="regulatory",
        markets=("US",),
        operations=("fetch", "qa", "generate_report", "analyze_impact"),
        depths=("quick", "report", "deep_research"),
        risk_level="low",
        timeout_ms=15000,
        cache_ttl_s=900,
        requires_env=("SEC_USER_AGENT",),
    ),
    ToolManifestEntry(
        name="get_sec_material_events",
        group="regulatory",
        markets=("US",),
        operations=("fetch", "qa", "generate_report", "analyze_impact"),
        depths=("quick", "report", "deep_research"),
        risk_level="low",
        timeout_ms=15000,
        cache_ttl_s=900,
        requires_env=("SEC_USER_AGENT",),
    ),
    ToolManifestEntry(
        name="get_sec_risk_factors",
        group="regulatory",
        markets=("US",),
        operations=("qa", "generate_report", "analyze_impact"),
        depths=("report", "deep_research"),
        risk_level="medium",
        timeout_ms=18000,
        cache_ttl_s=1800,
        requires_env=("SEC_USER_AGENT",),
    ),
    ToolManifestEntry(
        name="get_company_info",
        group="fundamental",
        markets=("US", "CN"),
        operations=("qa", "generate_report", "compare"),
        depths=("quick", "report", "deep_research"),
        risk_level="low",
        timeout_ms=10000,
        cache_ttl_s=600,
    ),
    ToolManifestEntry(
        name="get_company_news",
        group="news",
        markets=("US", "CN"),
        operations=("fetch", "analyze_impact", "qa", "generate_report"),
        depths=("quick", "report", "deep_research"),
        risk_level="low",
        timeout_ms=10000,
        cache_ttl_s=300,
    ),
    ToolManifestEntry(
        name="get_event_calendar",
        group="news",
        markets=("US", "CN"),
        operations=("fetch", "analyze_impact", "qa", "generate_report"),
        depths=("quick", "report", "deep_research"),
        risk_level="low",
        timeout_ms=10000,
        cache_ttl_s=3600,
    ),
    ToolManifestEntry(
        name="score_news_source_reliability",
        group="news",
        markets=("US", "CN"),
        operations=("fetch", "analyze_impact", "qa", "generate_report"),
        depths=("quick", "report", "deep_research"),
        risk_level="low",
        timeout_ms=8000,
        cache_ttl_s=86400,
    ),
    ToolManifestEntry(
        name="get_earnings_estimates",
        group="fundamental",
        markets=("US",),
        operations=("qa", "generate_report"),
        depths=("report", "deep_research"),
        risk_level="low",
        timeout_ms=12000,
        cache_ttl_s=3600,
    ),
    ToolManifestEntry(
        name="get_eps_revisions",
        group="fundamental",
        markets=("US",),
        operations=("qa", "generate_report"),
        depths=("report", "deep_research"),
        risk_level="low",
        timeout_ms=12000,
        cache_ttl_s=3600,
    ),
    ToolManifestEntry(
        name="analyze_historical_drawdowns",
        group="risk",
        markets=("US", "CN"),
        operations=("qa", "generate_report"),
        depths=("report", "deep_research"),
        risk_level="low",
        timeout_ms=15000,
        cache_ttl_s=3600,
    ),
    ToolManifestEntry(
        name="get_factor_exposure",
        group="risk",
        markets=("US",),
        operations=("qa", "generate_report"),
        depths=("report", "deep_research"),
        risk_level="medium",
        timeout_ms=15000,
        cache_ttl_s=1800,
    ),
    ToolManifestEntry(
        name="run_portfolio_stress_test",
        group="risk",
        markets=("US",),
        operations=("qa", "generate_report"),
        depths=("report", "deep_research"),
        risk_level="medium",
        timeout_ms=15000,
        cache_ttl_s=1800,
    ),
    ToolManifestEntry(
        name="get_performance_comparison",
        group="market",
        markets=("US", "CN"),
        operations=("compare",),
        depths=("quick", "report", "deep_research"),
        risk_level="low",
        timeout_ms=12000,
        cache_ttl_s=300,
    ),
    ToolManifestEntry(
        name="search",
        group="search",
        markets=("US", "CN"),
        operations=("qa", "fetch", "analyze_impact", "generate_report", "compare", "price", "technical"),
        depths=("quick", "report", "deep_research"),
        risk_level="low",
        timeout_ms=12000,
        cache_ttl_s=60,
    ),
    ToolManifestEntry(
        name="get_current_datetime",
        group="utility",
        markets=("US", "CN"),
        operations=("qa", "fetch", "analyze_impact", "generate_report", "compare", "price", "technical"),
        depths=("quick", "report", "deep_research"),
        risk_level="low",
        timeout_ms=2000,
        cache_ttl_s=0,
    ),
)


_MANIFEST_BY_NAME: dict[str, ToolManifestEntry] = {entry.name: entry for entry in TOOL_MANIFEST}


def select_tools(
    *,
    subject_type: str,
    operation_name: str,
    output_mode: str,
    analysis_depth: str | None = None,
    market: str = "US",
) -> list[str]:
    """Select tools from manifest while preserving current policy behavior."""
    subject = (subject_type or "unknown").strip().lower()
    operation = (operation_name or "qa").strip().lower()
    depth = (analysis_depth or "report").strip().lower()
    market_norm = (market or "US").strip().upper()

    if depth not in {"quick", "report", "deep_research"}:
        depth = "report"

    if subject in {"news_item", "news_set"}:
        candidate_names = [
            "get_company_news",
            "get_event_calendar",
            "score_news_source_reliability",
            "search",
            "get_current_datetime",
        ]
    elif subject == "company":
        if operation == "price":
            candidate_names = [
                "get_stock_price",
                "get_option_chain_metrics",
                "get_current_datetime",
                "search",
            ]
        elif operation == "technical":
            candidate_names = [
                "get_stock_price",
                "get_technical_snapshot",
                "get_option_chain_metrics",
                "get_current_datetime",
                "search",
            ]
        elif operation == "compare":
            candidate_names = ["get_performance_comparison", "get_current_datetime", "search"]
        else:
            candidate_names = [
                "get_stock_price",
                "get_technical_snapshot",
                "get_option_chain_metrics",
                "get_sec_filings",
                "get_sec_material_events",
                "get_sec_risk_factors",
                "get_company_info",
                "get_company_news",
                "get_event_calendar",
                "score_news_source_reliability",
                "get_earnings_estimates",
                "get_eps_revisions",
                "analyze_historical_drawdowns",
                "get_factor_exposure",
                "run_portfolio_stress_test",
                "get_current_datetime",
                "search",
            ]
    else:
        candidate_names = ["search", "get_current_datetime"]

    selected: list[str] = []
    for name in candidate_names:
        entry = _MANIFEST_BY_NAME.get(name)
        if not entry:
            continue
        if market_norm not in entry.markets:
            continue
        if operation not in entry.operations and "qa" not in entry.operations:
            continue
        if depth not in entry.depths:
            continue
        selected.append(name)

    # Keep stable fallback behavior for brief/chat when depth filters out too much.
    if not selected:
        selected = [name for name in candidate_names if name in _MANIFEST_BY_NAME]

    # For non-report modes, keep manifests deterministic and avoid deep-only inflation.
    if output_mode != "investment_report" and "deep_research" == depth:
        selected = [name for name in selected if name not in {"get_factor_exposure", "run_portfolio_stress_test"}] or selected

    return selected


__all__ = ["ToolManifestEntry", "TOOL_MANIFEST", "select_tools"]

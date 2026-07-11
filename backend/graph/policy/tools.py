"""Tool selection helpers used by the policy gate node."""
from __future__ import annotations

from backend.graph.intent_contract import canonical_evidence_kinds
from backend.graph.policy.runtime import _append_missing

_SEC_HOLDINGS_TOOL_NAMES: tuple[str, ...] = (
    "get_institutional_holdings",
    "get_institution_holdings_by_ticker",
    "get_insider_transactions",
    "get_holdings_overlap",
)

_VALUATION_COMPARE_LIGHT_TOOLS: tuple[str, ...] = (
    "get_stock_price",
    "get_company_info",
    "get_sec_company_facts_quarterly",
    "get_earnings_estimates",
    "get_current_datetime",
    "search",
)

_ACTION_RESULT_TOOLS: dict[str, tuple[str, ...]] = {
    "backtest_result": ("run_strategy_backtest", "get_current_datetime", "search"),
}


def _valuation_compare_light_tool_floor(required_evidence: list[str], *, market: str) -> tuple[str, ...]:
    """Light profile 可裁增强项，但不能裁契约声明的最低证据工具。"""
    market_norm = str(market or "US").strip().upper() or "US"
    minimum_tools_by_evidence = {
        "price_snapshot": ("get_stock_price",),
        "company_profile": ("get_company_info",),
        "earnings_estimates": ("get_earnings_estimates",),
        "filing_context": (
            ("get_sec_company_facts_quarterly",)
            if market_norm == "US"
            else ("get_local_market_filings",)
        ),
        "news_context": ("get_company_news",),
    }
    required_tools: list[str] = []
    for kind in canonical_evidence_kinds(required_evidence):
        required_tools.extend(minimum_tools_by_evidence.get(kind, ()))
    return tuple(_append_missing(list(_VALUATION_COMPARE_LIGHT_TOOLS), tuple(required_tools)))


def _tools_for_required_results(required_results: list[str]) -> list[str]:
    tools: list[str] = []
    seen: set[str] = set()
    for result in required_results:
        for tool_name in _ACTION_RESULT_TOOLS.get(str(result or "").strip(), ()):
            if tool_name in seen:
                continue
            seen.add(tool_name)
            tools.append(tool_name)
    return tools


def _with_us_holdings_tools(tools: list[str], *, subject_type: str, op_name: str, market: str) -> list[str]:
    if market != "US" or op_name != "holdings" or subject_type not in {"company", "portfolio"}:
        return tools
    result = list(tools)
    seen = set(result)
    for tool_name in _SEC_HOLDINGS_TOOL_NAMES:
        if tool_name in seen:
            continue
        seen.add(tool_name)
        result.append(tool_name)
    return result


def _without_holdings_tools(tools: list[str]) -> list[str]:
    return [tool_name for tool_name in tools if tool_name not in _SEC_HOLDINGS_TOOL_NAMES]


def _filter_tools_for_market(tools: list[str], *, market: str) -> list[str]:
    market_norm = str(market or "US").strip().upper() or "US"
    try:
        from backend.tools.manifest import TOOL_MANIFEST

        markets_by_tool = {entry.name: set(entry.markets) for entry in TOOL_MANIFEST}
    except Exception:
        markets_by_tool = {}
    filtered: list[str] = []
    seen: set[str] = set()
    for tool_name in tools:
        if tool_name in seen:
            continue
        seen.add(tool_name)
        markets = markets_by_tool.get(tool_name)
        if markets and market_norm not in markets:
            continue
        filtered.append(tool_name)
    return filtered


def _with_earnings_impact_tools(tools: list[str], *, market: str) -> list[str]:
    result = list(tools)
    seen = set(result)
    required = [
        "get_stock_price",
        "get_company_info",
        "get_company_news",
        "get_authoritative_media_news",
        "get_earnings_call_transcripts",
        "get_earnings_estimates",
        "get_eps_revisions",
        "analyze_historical_drawdowns",
        "get_current_datetime",
        "search",
    ]
    if str(market or "").strip().upper() == "US":
        required.insert(2, "get_sec_company_facts_quarterly")
    else:
        required.insert(2, "get_local_market_filings")
    for tool_name in required:
        if tool_name in seen:
            continue
        seen.add(tool_name)
        result.append(tool_name)
    return result


def _legacy_select_tools(subject_type: str, op_name: str) -> list[str]:
    """Legacy hardcoded allowlist selector kept as manifest fallback."""
    if op_name == "holdings" and subject_type in {"company", "portfolio"}:
        return [
            "get_institutional_holdings",
            "get_institution_holdings_by_ticker",
            "get_insider_transactions",
            "get_holdings_overlap",
            "get_current_datetime",
            "search",
        ]
    if op_name == "screen":
        return ["screen_stocks", "search", "get_current_datetime"]
    if op_name == "cn_market":
        return [
            "get_cn_market_fund_flow",
            "get_cn_market_northbound",
            "get_cn_limit_board",
            "get_cn_lhb",
            "get_cn_concept_map",
            "search",
            "get_current_datetime",
        ]
    if op_name == "backtest":
        return ["run_strategy_backtest", "search", "get_current_datetime"]
    if op_name == "morning_brief":
        return ["get_stock_price", "get_company_news", "get_current_datetime"]
    if subject_type in ("news_item", "news_set"):
        return [
            "fetch_url_content",
            "get_company_news",
            "get_event_calendar",
            "score_news_source_reliability",
            "get_authoritative_media_news",
            "search",
            "get_current_datetime",
        ]
    if subject_type in ("filing", "research_doc"):
        return ["fetch_url_content", "search", "get_current_datetime"]
    if subject_type == "macro":
        return [
            "get_official_macro_releases",
            "get_authoritative_media_news",
            "search",
            "get_current_datetime",
        ]
    if subject_type in ("theme", "unknown"):
        return [
            "fetch_url_content",
            "get_authoritative_media_news",
            "search",
            "get_current_datetime",
        ]
    if subject_type in ("company", "index", "commodity"):
        if op_name == "price":
            return [
                "get_stock_price",
                "get_option_chain_metrics",
                "get_current_datetime",
                "search",
            ]
        if op_name == "technical":
            return [
                "get_stock_price",
                "get_technical_snapshot",
                "get_option_chain_metrics",
                "get_current_datetime",
                "search",
            ]
        if op_name == "compare":
            return [
                "get_performance_comparison",
                "get_stock_price",
                "get_company_news",
                "get_company_info",
                "get_current_datetime",
                "search",
            ]
        return [
            "get_stock_price",
            "get_technical_snapshot",
            "get_option_chain_metrics",
            "get_company_info",
            "get_company_news",
            "get_event_calendar",
            "get_authoritative_media_news",
            "get_earnings_call_transcripts",
            "score_news_source_reliability",
            "get_local_market_filings",
            "get_earnings_estimates",
            "get_eps_revisions",
            "analyze_historical_drawdowns",
            "get_factor_exposure",
            "run_portfolio_stress_test",
            "get_current_datetime",
            "search",
        ]
    return ["fetch_url_content", "search", "get_current_datetime"]

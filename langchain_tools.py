#!/usr/bin/env python3
"""
LangChain tool registry for FinSight.

Uses the latest langchain-core @tool decorator with typed Pydantic schemas
so the tools can be bound to LangGraph/LCEL pipelines without extra glue code.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from langchain_core.tools import tool
from pydantic import BaseModel, Field

# Prefer backend.tools; fall back to a sibling tools.py for compatibility.
try:  # pragma: no cover - import guard
    from backend.tools import (  # type: ignore
        analyze_historical_drawdowns as _analyze_historical_drawdowns,
        get_company_info as _get_company_info,
        get_company_news as _get_company_news,
        get_current_datetime as _get_current_datetime,
        get_economic_events as _get_economic_events,
        get_market_sentiment as _get_market_sentiment,
        get_performance_comparison as _get_performance_comparison,
        get_stock_price as _get_stock_price,
        search as _search,
    )
except ImportError:  # pragma: no cover - backwards compatibility
    from tools import (  # type: ignore
        analyze_historical_drawdowns as _analyze_historical_drawdowns,
        get_company_info as _get_company_info,
        get_company_news as _get_company_news,
        get_current_datetime as _get_current_datetime,
        get_economic_events as _get_economic_events,
        get_market_sentiment as _get_market_sentiment,
        get_performance_comparison as _get_performance_comparison,
        get_stock_price as _get_stock_price,
        search as _search,
    )


# ============================================
# Pydantic input models (LangChain-friendly)
# ============================================

class StockTickerInput(BaseModel):
    """Ticker symbol input."""

    ticker: str = Field(
        description="Ticker or index symbol, e.g. 'AAPL', 'TSLA', '^GSPC'"
    )


class SearchQueryInput(BaseModel):
    """Free-form search query."""

    query: str = Field(description="Natural language finance/market search query")


class TickerComparisonInput(BaseModel):
    """Structured mapping for performance comparison."""

    tickers: Dict[str, str] = Field(
        description="Mapping of label to ticker, e.g. {'Apple': 'AAPL', 'NVIDIA': 'NVDA'}"
    )


class EmptyInput(BaseModel):
    """No-argument tool input placeholder."""

    pass


# ============================================
# Tool definitions
# ============================================

@tool("get_stock_price", args_schema=StockTickerInput, return_direct=False)
def get_stock_price(ticker: str) -> str:
    """Fetch a live quote with multi-source fallback (Alpha Vantage -> Finnhub -> yfinance -> scrape)."""

    try:
        return _get_stock_price(ticker)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_stock_price failed: {exc}"


@tool("get_company_news", args_schema=StockTickerInput, return_direct=False)
def get_company_news(ticker: str) -> str:
    """Retrieve the latest company or index headlines, ordered by recency."""

    try:
        return _get_company_news(ticker)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_company_news failed: {exc}"


@tool("get_company_info", args_schema=StockTickerInput, return_direct=False)
def get_company_info(ticker: str) -> str:
    """Return company fundamentals such as industry, market cap, website, and a short description."""

    try:
        return _get_company_info(ticker)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_company_info failed: {exc}"


@tool("search", args_schema=SearchQueryInput, return_direct=False)
def search(query: str) -> str:
    """Blend Tavily AI search (if configured) with DuckDuckGo/Wikipedia fallback for market context."""

    try:
        return _search(query)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"search failed: {exc}"


@tool("get_market_sentiment", args_schema=EmptyInput, return_direct=False)
def get_market_sentiment() -> str:
    """Return current market fear/greed sentiment with the latest available index value."""

    try:
        return _get_market_sentiment()
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_market_sentiment failed: {exc}"


@tool("get_economic_events", args_schema=EmptyInput, return_direct=False)
def get_economic_events() -> str:
    """List near-term macro events (FOMC, CPI, payrolls) with dates for quick planning."""

    try:
        return _get_economic_events()
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_economic_events failed: {exc}"


@tool("get_performance_comparison", args_schema=TickerComparisonInput, return_direct=False)
def get_performance_comparison(tickers: Dict[str, str]) -> str:
    """Compare multi-asset performance (YTD and 1Y) for a labeled ticker set."""

    try:
        return _get_performance_comparison(tickers)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_performance_comparison failed: {exc}"


@tool("analyze_historical_drawdowns", args_schema=StockTickerInput, return_direct=False)
def analyze_historical_drawdowns(ticker: str) -> str:
    """Summarize the largest drawdowns in the last ~20 years with duration and recovery time."""

    try:
        return _analyze_historical_drawdowns(ticker)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"analyze_historical_drawdowns failed: {exc}"


@tool("get_current_datetime", args_schema=EmptyInput, return_direct=False)
def get_current_datetime() -> str:
    """Provide the current timestamp to anchor analysis and reporting."""

    try:
        return _get_current_datetime()
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_current_datetime failed: {exc}"


# ============================================
# Registry helpers
# ============================================

FINANCIAL_TOOLS = [
    get_current_datetime,
    get_stock_price,
    get_company_info,
    get_company_news,
    search,
    get_market_sentiment,
    get_economic_events,
    get_performance_comparison,
    analyze_historical_drawdowns,
]


def get_tool_names() -> list[str]:
    """Return tool names in registry order."""

    return [tool.name for tool in FINANCIAL_TOOLS]


def get_tools_description() -> str:
    """Human-readable registry overview."""

    descriptions = []
    for i, tool in enumerate(FINANCIAL_TOOLS, 1):
        descriptions.append(f"{i}. {tool.name}: {tool.description}")
    return "\n".join(descriptions)


def get_tool_by_name(name: str) -> Optional[Any]:
    """Locate a tool by its registry name."""

    for tool in FINANCIAL_TOOLS:
        if tool.name == name:
            return tool
    return None


__all__ = [
    "FINANCIAL_TOOLS",
    "get_tool_names",
    "get_tools_description",
    "get_tool_by_name",
    "get_stock_price",
    "get_company_news",
    "get_company_info",
    "search",
    "get_market_sentiment",
    "get_economic_events",
    "get_performance_comparison",
    "analyze_historical_drawdowns",
    "get_current_datetime",
]

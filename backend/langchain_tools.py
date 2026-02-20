#!/usr/bin/env python3
"""
LangChain tool registry for FinSight.

Uses the latest langchain-core @tool decorator with typed Pydantic schemas
so the tools can be bound to LangGraph/LCEL pipelines without extra glue code.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import json

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
        get_stock_historical_data as _get_stock_historical_data,
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
        get_stock_historical_data as _get_stock_historical_data,
        search as _search,
    )

try:  # pragma: no cover - optional tools
    from backend.tools import (  # type: ignore
        get_authoritative_media_news as _get_authoritative_media_news,
        get_earnings_call_transcripts as _get_earnings_call_transcripts,
        get_earnings_estimates as _get_earnings_estimates,
        get_eps_revisions as _get_eps_revisions,
        get_event_calendar as _get_event_calendar,
        get_factor_exposure as _get_factor_exposure,
        get_local_market_filings as _get_local_market_filings,
        get_option_chain_metrics as _get_option_chain_metrics,
        get_sec_filings as _get_sec_filings,
        get_sec_material_events as _get_sec_material_events,
        get_sec_risk_factors as _get_sec_risk_factors,
        run_portfolio_stress_test as _run_portfolio_stress_test,
        score_news_source_reliability as _score_news_source_reliability,
    )
except Exception:  # pragma: no cover - optional tools fallback
    try:
        from tools import (  # type: ignore
            get_authoritative_media_news as _get_authoritative_media_news,
            get_earnings_call_transcripts as _get_earnings_call_transcripts,
            get_earnings_estimates as _get_earnings_estimates,
            get_eps_revisions as _get_eps_revisions,
            get_event_calendar as _get_event_calendar,
            get_factor_exposure as _get_factor_exposure,
            get_local_market_filings as _get_local_market_filings,
            get_option_chain_metrics as _get_option_chain_metrics,
            get_sec_filings as _get_sec_filings,
            get_sec_material_events as _get_sec_material_events,
            get_sec_risk_factors as _get_sec_risk_factors,
            run_portfolio_stress_test as _run_portfolio_stress_test,
            score_news_source_reliability as _score_news_source_reliability,
        )
    except Exception:  # pragma: no cover - compatibility mode
        _get_authoritative_media_news = None
        _get_earnings_call_transcripts = None
        _get_earnings_estimates = None
        _get_eps_revisions = None
        _get_option_chain_metrics = None
        _get_factor_exposure = None
        _get_local_market_filings = None
        _run_portfolio_stress_test = None
        _get_event_calendar = None
        _score_news_source_reliability = None
        _get_sec_filings = None
        _get_sec_material_events = None
        _get_sec_risk_factors = None


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


class OptionChainInput(BaseModel):
    """Option-chain derived metric inputs."""

    ticker: str = Field(description="Ticker symbol, e.g. 'AAPL'")
    expiry: Optional[str] = Field(
        default=None,
        description="Optional expiry date in YYYY-MM-DD format",
    )


class EventCalendarInput(BaseModel):
    """Event calendar inputs."""

    ticker: str = Field(description="Ticker symbol, e.g. 'AAPL'")
    days_ahead: int = Field(default=30, ge=1, le=120, description="Forward window in days")


class SourceReliabilityInput(BaseModel):
    """News source reliability inputs."""

    source: str = Field(default="", description="Source name, e.g. Reuters")
    url: str = Field(default="", description="Optional article URL")


class AuthoritativeMediaInput(BaseModel):
    """Authoritative media retrieval inputs."""

    query: str = Field(description="Query for authoritative media coverage")
    max_results: int = Field(default=8, ge=1, le=20, description="Maximum article rows")
    authoritative_only: bool = Field(default=True, description="Keep only trusted media domains")


class EarningsTranscriptInput(BaseModel):
    """Free transcript lookup inputs."""

    ticker: str = Field(description="Ticker symbol, e.g. 'AAPL'")
    limit: int = Field(default=6, ge=1, le=20, description="Maximum transcript rows")


class LocalFilingsInput(BaseModel):
    """Local market filing lookup inputs for CN/HK symbols."""

    ticker: str = Field(description="Ticker symbol, e.g. '600519.SS' or '0700.HK'")
    limit: int = Field(default=8, ge=1, le=20, description="Maximum filing rows")


class SecFilingsInput(BaseModel):
    """SEC filing lookup inputs."""

    ticker: str = Field(description="US ticker symbol, e.g. 'AAPL'")
    forms: str = Field(
        default="10-K,10-Q,8-K",
        description="Comma-separated SEC form types, e.g. '10-K,8-K'",
    )
    limit: int = Field(default=12, ge=1, le=50, description="Maximum filing rows to return")


class SecMaterialEventsInput(BaseModel):
    """SEC 8-K material events lookup inputs."""

    ticker: str = Field(description="US ticker symbol, e.g. 'AAPL'")
    limit: int = Field(default=10, ge=1, le=50, description="Maximum event rows to return")


class FactorExposureInput(BaseModel):
    """Portfolio factor exposure inputs."""

    positions: list[dict[str, Any]] = Field(
        description="Portfolio positions, e.g. [{'ticker':'AAPL','weight':0.6}]"
    )
    lookback_days: int = Field(default=252, ge=30, le=1260, description="Historical lookback window")


class StressTestInput(BaseModel):
    """Portfolio stress-test inputs."""

    positions: list[dict[str, Any]] = Field(
        description="Portfolio positions, e.g. [{'ticker':'AAPL','weight':0.6}]"
    )
    scenarios: Optional[dict[str, dict[str, float]]] = Field(
        default=None,
        description="Optional scenario map, e.g. {'equity_selloff': {'market': -0.1}}",
    )
    lookback_days: int = Field(default=252, ge=30, le=1260, description="Historical lookback window")


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
        news = _get_company_news(ticker)
        if isinstance(news, list):
            return json.dumps(news, ensure_ascii=False)
        return str(news)
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


@tool("get_technical_snapshot", args_schema=StockTickerInput, return_direct=False)
def get_technical_snapshot(ticker: str) -> str:
    """
    Compute a lightweight technical snapshot (MA/RSI/MACD) from recent daily prices.

    Returns a JSON string so the planner/synthesizer can reliably parse it.
    """

    try:
        data = _get_stock_historical_data(ticker, period="6mo", interval="1d")
        if not isinstance(data, dict):
            return json.dumps({"ticker": ticker, "error": "invalid_kline_payload"}, ensure_ascii=False)

        kline = data.get("kline_data") or []
        if not isinstance(kline, list) or not kline:
            return json.dumps(
                {"ticker": ticker, "error": "no_kline_data", "source": data.get("source")}, ensure_ascii=False
            )

        closes = []
        last_time = None
        for item in kline:
            if not isinstance(item, dict):
                continue
            close = item.get("close")
            if close is None:
                continue
            closes.append(float(close))
            last_time = item.get("time") or item.get("datetime") or item.get("ts") or last_time

        if len(closes) < 30:
            return json.dumps(
                {
                    "ticker": ticker,
                    "error": "insufficient_points",
                    "points": len(closes),
                    "source": data.get("source"),
                },
                ensure_ascii=False,
            )

        import pandas as pd  # local import to keep cold-start minimal

        series = pd.Series(closes)
        close = float(series.iloc[-1])

        def _ma(window: int) -> float | None:
            if len(series) < window:
                return None
            return float(series.rolling(window=window).mean().iloc[-1])

        def _rsi(window: int = 14) -> float | None:
            if len(series) < window + 1:
                return None
            delta = series.diff()
            gains = delta.where(delta > 0, 0.0)
            losses = -delta.where(delta < 0, 0.0)
            avg_gain = gains.rolling(window=window, min_periods=window).mean()
            avg_loss = losses.rolling(window=window, min_periods=window).mean()
            last_gain = float(avg_gain.iloc[-1]) if not pd.isna(avg_gain.iloc[-1]) else 0.0
            last_loss = float(avg_loss.iloc[-1]) if not pd.isna(avg_loss.iloc[-1]) else 0.0
            if last_loss == 0:
                return 100.0
            rs = last_gain / last_loss
            return 100.0 - (100.0 / (1.0 + rs))

        def _macd() -> tuple[float | None, float | None]:
            if len(series) < 26:
                return None, None
            ema12 = series.ewm(span=12, adjust=False).mean()
            ema26 = series.ewm(span=26, adjust=False).mean()
            macd_series = ema12 - ema26
            signal_series = macd_series.ewm(span=9, adjust=False).mean()
            return float(macd_series.iloc[-1]), float(signal_series.iloc[-1])

        ma20 = _ma(20)
        ma50 = _ma(50)
        ma200 = _ma(200)
        rsi14 = _rsi(14)
        macd, signal = _macd()

        trend = "sideways"
        if ma20 is not None and ma50 is not None:
            if close > ma20 > ma50:
                trend = "uptrend"
            elif close < ma20 < ma50:
                trend = "downtrend"

        rsi_state = "neutral"
        if rsi14 is not None:
            if rsi14 >= 70:
                rsi_state = "overbought"
            elif rsi14 <= 30:
                rsi_state = "oversold"

        momentum = None
        if macd is not None and signal is not None:
            momentum = "bullish" if macd > signal else "bearish"

        payload = {
            "ticker": str(ticker).upper(),
            "as_of": last_time,
            "source": data.get("source"),
            "close": close,
            "ma20": ma20,
            "ma50": ma50,
            "ma200": ma200,
            "rsi14": rsi14,
            "rsi_state": rsi_state,
            "macd": macd,
            "macd_signal": signal,
            "momentum": momentum,
            "trend": trend,
        }
        return json.dumps(payload, ensure_ascii=False)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_technical_snapshot failed: {exc}"


@tool("get_current_datetime", args_schema=EmptyInput, return_direct=False)
def get_current_datetime() -> str:
    """Provide the current timestamp to anchor analysis and reporting."""

    try:
        return _get_current_datetime()
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_current_datetime failed: {exc}"


@tool("get_earnings_estimates", args_schema=StockTickerInput, return_direct=False)
def get_earnings_estimates(ticker: str) -> str:
    """Get forward earnings estimates and revision signal."""

    if not callable(_get_earnings_estimates):
        return "get_earnings_estimates unavailable: backend.tools function not found"
    try:
        payload = _get_earnings_estimates(ticker)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_earnings_estimates failed: {exc}"


@tool("get_eps_revisions", args_schema=StockTickerInput, return_direct=False)
def get_eps_revisions(ticker: str) -> str:
    """Get EPS revision table and trend signal."""

    if not callable(_get_eps_revisions):
        return "get_eps_revisions unavailable: backend.tools function not found"
    try:
        payload = _get_eps_revisions(ticker)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_eps_revisions failed: {exc}"


@tool("get_option_chain_metrics", args_schema=OptionChainInput, return_direct=False)
def get_option_chain_metrics(ticker: str, expiry: Optional[str] = None) -> str:
    """Get option-derived metrics such as IV, put/call ratio and skew."""

    if not callable(_get_option_chain_metrics):
        return "get_option_chain_metrics unavailable: backend.tools function not found"
    try:
        payload = _get_option_chain_metrics(ticker, expiry=expiry)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_option_chain_metrics failed: {exc}"


@tool("get_factor_exposure", args_schema=FactorExposureInput, return_direct=False)
def get_factor_exposure(positions: list[dict[str, Any]], lookback_days: int = 252) -> str:
    """Estimate portfolio factor exposures from free market data."""

    if not callable(_get_factor_exposure):
        return "get_factor_exposure unavailable: backend.tools function not found"
    try:
        payload = _get_factor_exposure(positions, lookback_days=lookback_days)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_factor_exposure failed: {exc}"


@tool("run_portfolio_stress_test", args_schema=StressTestInput, return_direct=False)
def run_portfolio_stress_test(
    positions: list[dict[str, Any]],
    scenarios: Optional[dict[str, dict[str, float]]] = None,
    lookback_days: int = 252,
) -> str:
    """Run factor-based portfolio stress tests under predefined or custom scenarios."""

    if not callable(_run_portfolio_stress_test):
        return "run_portfolio_stress_test unavailable: backend.tools function not found"
    try:
        payload = _run_portfolio_stress_test(positions, scenarios=scenarios, lookback_days=lookback_days)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"run_portfolio_stress_test failed: {exc}"


@tool("get_event_calendar", args_schema=EventCalendarInput, return_direct=False)
def get_event_calendar(ticker: str, days_ahead: int = 30) -> str:
    """Get upcoming earnings/dividend/macro events for a ticker."""

    if not callable(_get_event_calendar):
        return "get_event_calendar unavailable: backend.tools function not found"
    try:
        payload = _get_event_calendar(ticker, days_ahead=days_ahead)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_event_calendar failed: {exc}"


@tool("score_news_source_reliability", args_schema=SourceReliabilityInput, return_direct=False)
def score_news_source_reliability(source: str = "", url: str = "") -> str:
    """Score source reliability with rule-based heuristics."""

    if not callable(_score_news_source_reliability):
        return "score_news_source_reliability unavailable: backend.tools function not found"
    try:
        payload = _score_news_source_reliability(source=source, url=url)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"score_news_source_reliability failed: {exc}"


@tool("get_authoritative_media_news", args_schema=AuthoritativeMediaInput, return_direct=False)
def get_authoritative_media_news(query: str, max_results: int = 8, authoritative_only: bool = True) -> str:
    """Get authoritative media links from free publisher feeds."""

    if not callable(_get_authoritative_media_news):
        return "get_authoritative_media_news unavailable: backend.tools function not found"
    try:
        payload = _get_authoritative_media_news(
            query=query,
            max_results=max_results,
            authoritative_only=authoritative_only,
        )
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_authoritative_media_news failed: {exc}"


@tool("get_earnings_call_transcripts", args_schema=EarningsTranscriptInput, return_direct=False)
def get_earnings_call_transcripts(ticker: str, limit: int = 6) -> str:
    """Find free earnings-call transcript links and snippets."""

    if not callable(_get_earnings_call_transcripts):
        return "get_earnings_call_transcripts unavailable: backend.tools function not found"
    try:
        payload = _get_earnings_call_transcripts(ticker=ticker, limit=limit)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_earnings_call_transcripts failed: {exc}"


@tool("get_local_market_filings", args_schema=LocalFilingsInput, return_direct=False)
def get_local_market_filings(ticker: str, limit: int = 8) -> str:
    """Find CN/HK exchange disclosures via free local filing sources."""

    if not callable(_get_local_market_filings):
        return "get_local_market_filings unavailable: backend.tools function not found"
    try:
        payload = _get_local_market_filings(ticker=ticker, limit=limit)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_local_market_filings failed: {exc}"


@tool("get_sec_filings", args_schema=SecFilingsInput, return_direct=False)
def get_sec_filings(ticker: str, forms: str = "10-K,10-Q,8-K", limit: int = 12) -> str:
    """Get recent SEC filings for a US ticker from EDGAR submissions."""

    if not callable(_get_sec_filings):
        return "get_sec_filings unavailable: backend.tools function not found"
    try:
        payload = _get_sec_filings(ticker=ticker, forms=forms, limit=limit)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_sec_filings failed: {exc}"


@tool("get_sec_material_events", args_schema=SecMaterialEventsInput, return_direct=False)
def get_sec_material_events(ticker: str, limit: int = 10) -> str:
    """Get SEC 8-K material event filings for a US ticker."""

    if not callable(_get_sec_material_events):
        return "get_sec_material_events unavailable: backend.tools function not found"
    try:
        payload = _get_sec_material_events(ticker=ticker, limit=limit)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_sec_material_events failed: {exc}"


@tool("get_sec_risk_factors", args_schema=StockTickerInput, return_direct=False)
def get_sec_risk_factors(ticker: str) -> str:
    """Extract latest SEC Item 1A risk factor excerpt for a US ticker."""

    if not callable(_get_sec_risk_factors):
        return "get_sec_risk_factors unavailable: backend.tools function not found"
    try:
        payload = _get_sec_risk_factors(ticker=ticker)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_sec_risk_factors failed: {exc}"


# ============================================
# Registry helpers
# ============================================

FINANCIAL_TOOLS = [
    get_current_datetime,
    get_stock_price,
    get_technical_snapshot,
    get_option_chain_metrics,
    get_sec_filings,
    get_sec_material_events,
    get_sec_risk_factors,
    get_company_info,
    get_company_news,
    get_event_calendar,
    get_authoritative_media_news,
    get_earnings_call_transcripts,
    score_news_source_reliability,
    get_local_market_filings,
    search,
    get_market_sentiment,
    get_economic_events,
    get_earnings_estimates,
    get_eps_revisions,
    get_performance_comparison,
    analyze_historical_drawdowns,
    get_factor_exposure,
    run_portfolio_stress_test,
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
    "get_technical_snapshot",
    "get_option_chain_metrics",
    "get_sec_filings",
    "get_sec_material_events",
    "get_sec_risk_factors",
    "get_company_news",
    "get_event_calendar",
    "get_authoritative_media_news",
    "get_earnings_call_transcripts",
    "score_news_source_reliability",
    "get_local_market_filings",
    "get_company_info",
    "search",
    "get_market_sentiment",
    "get_economic_events",
    "get_earnings_estimates",
    "get_eps_revisions",
    "get_performance_comparison",
    "analyze_historical_drawdowns",
    "get_factor_exposure",
    "run_portfolio_stress_test",
    "get_current_datetime",
]

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
        fetch_url_document as _fetch_url_document,
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
        fetch_url_document as _fetch_url_document,
    )

try:  # pragma: no cover - optional tools
    from backend.tools import (  # type: ignore
        get_authoritative_media_news as _get_authoritative_media_news,
        get_earnings_call_transcripts as _get_earnings_call_transcripts,
        get_earnings_estimates as _get_earnings_estimates,
        get_eps_revisions as _get_eps_revisions,
        get_event_calendar as _get_event_calendar,
        get_factor_exposure as _get_factor_exposure,
        get_official_macro_releases as _get_official_macro_releases,
        get_local_market_filings as _get_local_market_filings,
        get_option_chain_metrics as _get_option_chain_metrics,
        get_sec_filings as _get_sec_filings,
        get_sec_company_facts_quarterly as _get_sec_company_facts_quarterly,
        get_sec_material_events as _get_sec_material_events,
        get_sec_risk_factors as _get_sec_risk_factors,
        get_institutional_holdings as _get_institutional_holdings,
        get_institution_holdings_by_ticker as _get_institution_holdings_by_ticker,
        get_insider_transactions as _get_insider_transactions,
        get_holdings_overlap as _get_holdings_overlap,
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
            get_official_macro_releases as _get_official_macro_releases,
            get_local_market_filings as _get_local_market_filings,
            get_option_chain_metrics as _get_option_chain_metrics,
            get_sec_filings as _get_sec_filings,
            get_sec_company_facts_quarterly as _get_sec_company_facts_quarterly,
            get_sec_material_events as _get_sec_material_events,
            get_sec_risk_factors as _get_sec_risk_factors,
            get_institutional_holdings as _get_institutional_holdings,
            get_institution_holdings_by_ticker as _get_institution_holdings_by_ticker,
            get_insider_transactions as _get_insider_transactions,
            get_holdings_overlap as _get_holdings_overlap,
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
        _get_official_macro_releases = None
        _get_local_market_filings = None
        _run_portfolio_stress_test = None
        _get_event_calendar = None
        _score_news_source_reliability = None
        _get_sec_filings = None
        _get_sec_company_facts_quarterly = None
        _get_sec_material_events = None
        _get_sec_risk_factors = None
        _get_institutional_holdings = None
        _get_institution_holdings_by_ticker = None
        _get_insider_transactions = None
        _get_holdings_overlap = None

try:  # pragma: no cover - phase 2/3 tools
    from backend.tools import (  # type: ignore
        screen_stocks as _screen_stocks,
        fetch_fund_flow as _fetch_fund_flow,
        fetch_northbound as _fetch_northbound,
        fetch_limit_board as _fetch_limit_board,
        fetch_lhb as _fetch_lhb,
        fetch_concept_map as _fetch_concept_map,
    )
except Exception:  # pragma: no cover
    _screen_stocks = None
    _fetch_fund_flow = None
    _fetch_northbound = None
    _fetch_limit_board = None
    _fetch_lhb = None
    _fetch_concept_map = None

try:  # pragma: no cover - phase 4 service
    from backend.services.backtest_engine import BacktestEngine as _BacktestEngine
except Exception:  # pragma: no cover
    _BacktestEngine = None


# ============================================
# Pydantic input models (LangChain-friendly)
# ============================================

class StockTickerInput(BaseModel):
    """Ticker symbol input."""

    ticker: str = Field(
        description="Ticker or index symbol, e.g. 'AAPL', 'TSLA', '^GSPC'"
    )


class NewsTickerInput(BaseModel):
    """Ticker news input."""

    ticker: str = Field(description="Ticker or index symbol, e.g. 'AAPL', 'TSLA', '^GSPC'")
    limit: int = Field(default=5, ge=1, le=10, description="Maximum number of headlines")
    fast: bool = Field(default=False, description="Use fast linked fallback for latency-sensitive brief answers")


class SearchQueryInput(BaseModel):
    """Free-form search query."""

    query: str = Field(description="Natural language finance/market search query")


class UrlFetchInput(BaseModel):
    """Safe URL fetch inputs."""

    url: str = Field(description="HTTP(S) URL to fetch")
    max_length: int = Field(default=6000, ge=500, le=20000, description="Maximum extracted text length")


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


class MacroOfficialInput(BaseModel):
    """Official macro release inputs (BLS/BEA/FED)."""

    query: str = Field(default="", description="Optional macro topic query, e.g. 'US CPI payrolls'")
    max_results: int = Field(default=10, ge=1, le=30, description="Maximum official release rows")


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


class SecCompanyFactsInput(BaseModel):
    """SEC company facts quarterly inputs."""

    ticker: str = Field(description="US ticker symbol, e.g. 'AAPL'")
    limit: int = Field(default=8, ge=1, le=12, description="Maximum quarterly periods to return")


class InstitutionalHoldingsInput(BaseModel):
    """SEC 13F institutional holdings inputs."""

    cik_or_name: str = Field(description="SEC CIK, US ticker, or institution name")
    quarter: Optional[str] = Field(default=None, description="Optional quarter, e.g. 2025Q1")
    limit: int = Field(default=100, ge=1, le=500, description="Maximum holding rows")


class InstitutionHoldingsByTickerInput(BaseModel):
    """SEC 13F holder lookup inputs."""

    ticker: str = Field(description="US ticker symbol, e.g. 'AAPL'")
    limit: int = Field(default=50, ge=1, le=200, description="Maximum holder rows")


class InsiderTransactionsInput(BaseModel):
    """SEC Form 4 insider transaction inputs."""

    ticker: str = Field(description="US ticker symbol, e.g. 'AAPL'")
    days: int = Field(default=180, ge=1, le=720, description="Lookback window in days")
    limit: int = Field(default=50, ge=1, le=200, description="Maximum transaction rows")


class HoldingsOverlapInput(BaseModel):
    """Compare portfolio positions to an institution's 13F holdings."""

    positions: list[dict[str, Any]] = Field(
        description="Portfolio positions, e.g. [{'ticker':'AAPL','weight':0.6}]"
    )
    holder_cik_or_name: str = Field(description="SEC CIK, US ticker, or institution name")
    quarter: Optional[str] = Field(default=None, description="Optional quarter, e.g. 2025Q1")


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


class ScreenerInput(BaseModel):
    """Stock screener inputs."""

    market: str = Field(default="US", description="US/CN/HK")
    filters: dict[str, Any] = Field(default_factory=dict, description="screener filter dict")
    limit: int = Field(default=20, ge=1, le=200, description="rows per page")
    page: int = Field(default=1, ge=1, le=100, description="page number")
    sort_by: str = Field(default="marketCap", description="sort field")
    sort_order: str = Field(default="desc", description="asc or desc")


class CNMarketInput(BaseModel):
    """CN market list query inputs."""

    limit: int = Field(default=20, ge=1, le=200, description="max rows")
    keyword: str = Field(default="", description="optional keyword for concept filtering")


class BacktestInput(BaseModel):
    """Strategy backtest inputs."""

    ticker: str = Field(description="ticker, e.g. AAPL or 600519.SS")
    strategy: str = Field(default="ma_cross", description="ma_cross/macd/rsi_mean_reversion")
    params: dict[str, Any] = Field(default_factory=dict, description="strategy params")
    start_date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    end_date: Optional[str] = Field(default=None, description="YYYY-MM-DD")
    initial_cash: float = Field(default=100000.0, gt=0, description="initial cash")
    fee_bps: Optional[float] = Field(default=None, ge=0, description="fee bps")
    slippage_bps: Optional[float] = Field(default=None, ge=0, description="slippage bps")
    t_plus_one: bool = Field(default=True, description="apply T+1")
    market: Optional[str] = Field(default=None, description="US/CN/HK hint")


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


@tool("get_company_news", args_schema=NewsTickerInput, return_direct=False)
def get_company_news(ticker: str, limit: int = 5, fast: bool = False) -> str:
    """Retrieve the latest company or index headlines, ordered by recency."""

    try:
        news = _get_company_news(ticker, limit=limit, fast=fast)
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


@tool("fetch_url_content", args_schema=UrlFetchInput, return_direct=False)
def fetch_url_content(url: str, max_length: int = 6000) -> str:
    """Fetch a safe HTTP(S) URL and extract title, source and readable page text."""

    try:
        payload = _fetch_url_document(url, max_length=max_length)
        if not isinstance(payload, dict):
            return json.dumps({"url": url, "error": "fetch_failed"}, ensure_ascii=False)
        return json.dumps(payload, ensure_ascii=False)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"fetch_url_content failed: {exc}"


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


@tool("get_official_macro_releases", args_schema=MacroOfficialInput, return_direct=False)
def get_official_macro_releases(query: str = "", max_results: int = 10) -> str:
    """Get official macro release links from BLS/BEA/FED feeds."""

    if not callable(_get_official_macro_releases):
        return "get_official_macro_releases unavailable: backend.tools function not found"
    try:
        payload = _get_official_macro_releases(query=query, max_results=max_results)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_official_macro_releases failed: {exc}"


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


@tool("get_sec_company_facts_quarterly", args_schema=SecCompanyFactsInput, return_direct=False)
def get_sec_company_facts_quarterly(ticker: str, limit: int = 8) -> str:
    """Get quarterly SEC CompanyFacts (XBRL) normalized metrics for a US ticker."""

    if not callable(_get_sec_company_facts_quarterly):
        return "get_sec_company_facts_quarterly unavailable: backend.tools function not found"
    try:
        payload = _get_sec_company_facts_quarterly(ticker=ticker, limit=limit)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_sec_company_facts_quarterly failed: {exc}"


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


@tool("get_institutional_holdings", args_schema=InstitutionalHoldingsInput, return_direct=False)
def get_institutional_holdings(cik_or_name: str, quarter: Optional[str] = None, limit: int = 100) -> str:
    """Get institution-level SEC 13F holdings; 13F data is delayed after quarter end."""

    if not callable(_get_institutional_holdings):
        return "get_institutional_holdings unavailable: backend.tools function not found"
    try:
        payload = _get_institutional_holdings(cik_or_name=cik_or_name, quarter=quarter, limit=limit)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_institutional_holdings failed: {exc}"


@tool("get_institution_holdings_by_ticker", args_schema=InstitutionHoldingsByTickerInput, return_direct=False)
def get_institution_holdings_by_ticker(ticker: str, limit: int = 50) -> str:
    """Get a read-only SEC 13F holder lookup stub for a US ticker."""

    if not callable(_get_institution_holdings_by_ticker):
        return "get_institution_holdings_by_ticker unavailable: backend.tools function not found"
    try:
        payload = _get_institution_holdings_by_ticker(ticker=ticker, limit=limit)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_institution_holdings_by_ticker failed: {exc}"


@tool("get_insider_transactions", args_schema=InsiderTransactionsInput, return_direct=False)
def get_insider_transactions(ticker: str, days: int = 180, limit: int = 50) -> str:
    """Get recent SEC Form 4 insider transactions for a US ticker."""

    if not callable(_get_insider_transactions):
        return "get_insider_transactions unavailable: backend.tools function not found"
    try:
        payload = _get_insider_transactions(ticker=ticker, days=days, limit=limit)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_insider_transactions failed: {exc}"


@tool("get_holdings_overlap", args_schema=HoldingsOverlapInput, return_direct=False)
def get_holdings_overlap(
    positions: list[dict[str, Any]],
    holder_cik_or_name: str,
    quarter: Optional[str] = None,
) -> str:
    """Compare portfolio tickers against an institution's disclosed SEC 13F holdings."""

    if not callable(_get_holdings_overlap):
        return "get_holdings_overlap unavailable: backend.tools function not found"
    try:
        payload = _get_holdings_overlap(positions=positions, holder_cik_or_name=holder_cik_or_name, quarter=quarter)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover - runtime data issues
        return f"get_holdings_overlap failed: {exc}"


@tool("screen_stocks", args_schema=ScreenerInput, return_direct=False)
def screen_stocks(
    market: str = "US",
    filters: dict[str, Any] | None = None,
    limit: int = 20,
    page: int = 1,
    sort_by: str = "marketCap",
    sort_order: str = "desc",
) -> str:
    """Run a stock screener and return candidate symbols."""

    if not callable(_screen_stocks):
        return "screen_stocks unavailable: backend.tools function not found"
    try:
        payload = _screen_stocks(
            market=market,
            filters=filters or {},
            limit=limit,
            page=page,
            sort_by=sort_by,
            sort_order=sort_order,
        )
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover
        return f"screen_stocks failed: {exc}"


@tool("get_cn_market_fund_flow", args_schema=CNMarketInput, return_direct=False)
def get_cn_market_fund_flow(limit: int = 20, keyword: str = "") -> str:
    """Fetch CN market fund-flow ranking."""

    if not callable(_fetch_fund_flow):
        return "get_cn_market_fund_flow unavailable: backend.tools function not found"
    try:
        payload = _fetch_fund_flow(limit=limit)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover
        return f"get_cn_market_fund_flow failed: {exc}"


@tool("get_cn_market_northbound", args_schema=CNMarketInput, return_direct=False)
def get_cn_market_northbound(limit: int = 20, keyword: str = "") -> str:
    """Fetch CN northbound flow ranking."""

    if not callable(_fetch_northbound):
        return "get_cn_market_northbound unavailable: backend.tools function not found"
    try:
        payload = _fetch_northbound(limit=limit)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover
        return f"get_cn_market_northbound failed: {exc}"


@tool("get_cn_limit_board", args_schema=CNMarketInput, return_direct=False)
def get_cn_limit_board(limit: int = 20, keyword: str = "") -> str:
    """Fetch CN limit board ranking."""

    if not callable(_fetch_limit_board):
        return "get_cn_limit_board unavailable: backend.tools function not found"
    try:
        payload = _fetch_limit_board(limit=limit)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover
        return f"get_cn_limit_board failed: {exc}"


@tool("get_cn_lhb", args_schema=CNMarketInput, return_direct=False)
def get_cn_lhb(limit: int = 20, keyword: str = "") -> str:
    """Fetch CN LongHuBang style list."""

    if not callable(_fetch_lhb):
        return "get_cn_lhb unavailable: backend.tools function not found"
    try:
        payload = _fetch_lhb(limit=limit)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover
        return f"get_cn_lhb failed: {exc}"


@tool("get_cn_concept_map", args_schema=CNMarketInput, return_direct=False)
def get_cn_concept_map(limit: int = 20, keyword: str = "") -> str:
    """Fetch CN concept-board map list."""

    if not callable(_fetch_concept_map):
        return "get_cn_concept_map unavailable: backend.tools function not found"
    try:
        payload = _fetch_concept_map(limit=limit, keyword=keyword)
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover
        return f"get_cn_concept_map failed: {exc}"


@tool("run_strategy_backtest", args_schema=BacktestInput, return_direct=False)
def run_strategy_backtest(
    ticker: str,
    strategy: str = "ma_cross",
    params: dict[str, Any] | None = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    initial_cash: float = 100000.0,
    fee_bps: Optional[float] = None,
    slippage_bps: Optional[float] = None,
    t_plus_one: bool = True,
    market: Optional[str] = None,
) -> str:
    """Run a strategy backtest and return metrics, trades, and equity curve."""

    if _BacktestEngine is None:
        return "run_strategy_backtest unavailable: backtest engine not found"
    try:
        engine = _BacktestEngine()
        payload = engine.run(
            ticker=ticker,
            strategy=strategy,
            params=params or {},
            start_date=start_date,
            end_date=end_date,
            initial_cash=initial_cash,
            fee_bps=fee_bps,
            slippage_bps=slippage_bps,
            t_plus_one=t_plus_one,
            market=market,
        )
        return json.dumps(payload, ensure_ascii=False) if isinstance(payload, (dict, list)) else str(payload)
    except Exception as exc:  # pragma: no cover
        return f"run_strategy_backtest failed: {exc}"


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
    get_sec_company_facts_quarterly,
    get_sec_risk_factors,
    get_institutional_holdings,
    get_institution_holdings_by_ticker,
    get_insider_transactions,
    get_holdings_overlap,
    screen_stocks,
    get_cn_market_fund_flow,
    get_cn_market_northbound,
    get_cn_limit_board,
    get_cn_lhb,
    get_cn_concept_map,
    run_strategy_backtest,
    get_company_info,
    get_company_news,
    get_event_calendar,
    get_authoritative_media_news,
    get_earnings_call_transcripts,
    score_news_source_reliability,
    get_local_market_filings,
    fetch_url_content,
    search,
    get_market_sentiment,
    get_economic_events,
    get_official_macro_releases,
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
    "get_sec_company_facts_quarterly",
    "get_sec_risk_factors",
    "get_institutional_holdings",
    "get_institution_holdings_by_ticker",
    "get_insider_transactions",
    "get_holdings_overlap",
    "screen_stocks",
    "get_cn_market_fund_flow",
    "get_cn_market_northbound",
    "get_cn_limit_board",
    "get_cn_lhb",
    "get_cn_concept_map",
    "run_strategy_backtest",
    "get_company_news",
    "get_event_calendar",
    "get_authoritative_media_news",
    "get_earnings_call_transcripts",
    "score_news_source_reliability",
    "get_local_market_filings",
    "get_company_info",
    "fetch_url_content",
    "search",
    "get_market_sentiment",
    "get_economic_events",
    "get_official_macro_releases",
    "get_earnings_estimates",
    "get_eps_revisions",
    "get_performance_comparison",
    "analyze_historical_drawdowns",
    "get_factor_exposure",
    "run_portfolio_stress_test",
    "get_current_datetime",
]

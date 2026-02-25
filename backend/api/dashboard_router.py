"""
Dashboard API 路由

提供 Dashboard 聚合接口，按 symbol 解析资产类型并返回结构化数据。
"""
import asyncio
import logging
import os
import time
from datetime import datetime, timezone
from functools import partial
from typing import Any, Awaitable, Callable, Optional

from fastapi import APIRouter, Query

from backend.dashboard.asset_resolver import is_valid_symbol, resolve_asset
from backend.dashboard.cache import dashboard_cache
from backend.dashboard.data_service import (
    fetch_analyst_targets,
    fetch_earnings_history,
    fetch_financial_statements,
    fetch_holdings,
    fetch_indicator_series,
    fetch_macro_snapshot,
    fetch_market_chart,
    fetch_news,
    fetch_recommendations,
    fetch_revenue_trend,
    fetch_sector_weights,
    fetch_segment_mix,
    fetch_snapshot,
    fetch_technical_indicators,
    fetch_top_constituents,
    fetch_valuation,
)
from backend.dashboard.errors import symbol_not_found
from backend.dashboard.peer_service import fetch_peer_comparison
from backend.dashboard.schemas import (
    AnalystTargets,
    Capabilities,
    DashboardData,
    DashboardInsightsResponse,
    DashboardResponse,
    DashboardState,
    EarningsHistoryEntry,
    FinancialStatement,
    IndicatorSeries,
    LayoutPrefs,
    MacroSnapshotData,
    NewsModeConfig,
    PeerComparisonData,
    RecommendationsSummary,
    TechnicalData,
    ValuationData,
    WatchItem,
)
from backend.dashboard.widget_selector import select_capabilities

logger = logging.getLogger(__name__)

dashboard_router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

_DASHBOARD_FETCH_TIMEOUT_SECONDS = 15.0
_DASHBOARD_NEWS_FETCH_TIMEOUT_SECONDS = float(os.getenv("FINSIGHT_DASHBOARD_NEWS_TIMEOUT", "45"))
_DASHBOARD_FAILURE_TTL_SECONDS = max(5, int(os.getenv("FINSIGHT_DASHBOARD_FAILURE_TTL", "30")))
_DASHBOARD_FAILURE_MARKER = "__dashboard_failure__"
_DASHBOARD_FAILURE_REASON_KEY = "reason"
_singleflight_tasks: dict[str, asyncio.Task[Any]] = {}
_singleflight_lock: asyncio.Lock | None = None


async def _run_blocking(
    name: str,
    fn,
    *args,
    timeout: float = _DASHBOARD_FETCH_TIMEOUT_SECONDS,
    **kwargs,
):
    bound = partial(fn, *args, **kwargs)
    try:
        return await asyncio.wait_for(asyncio.to_thread(bound), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("[Dashboard] %s timed out (%.1fs)", name, timeout)
    except Exception as exc:
        logger.warning("[Dashboard] %s failed: %s", name, exc)
    return None


def _get_singleflight_lock() -> asyncio.Lock:
    global _singleflight_lock
    if _singleflight_lock is None:
        _singleflight_lock = asyncio.Lock()
    return _singleflight_lock


async def _singleflight_call(
    key: str,
    coro_factory: Callable[[], Awaitable[Any]],
) -> Any:
    lock = _get_singleflight_lock()
    async with lock:
        task = _singleflight_tasks.get(key)
        if task is None or task.done():
            task = asyncio.create_task(coro_factory())
            _singleflight_tasks[key] = task

    try:
        return await task
    finally:
        async with lock:
            current = _singleflight_tasks.get(key)
            if current is task and task.done():
                _singleflight_tasks.pop(key, None)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_failure_marker(reason: str) -> dict[str, object]:
    return {
        _DASHBOARD_FAILURE_MARKER: True,
        _DASHBOARD_FAILURE_REASON_KEY: reason,
        "as_of": _utc_now_iso(),
    }


def _is_failure_marker(payload: object) -> bool:
    return isinstance(payload, dict) and payload.get(_DASHBOARD_FAILURE_MARKER) is True


def _failure_reason_from_marker(payload: object) -> str | None:
    if not _is_failure_marker(payload):
        return None
    reason = payload.get(_DASHBOARD_FAILURE_REASON_KEY) if isinstance(payload, dict) else None
    if isinstance(reason, str) and reason.strip():
        return reason.strip()
    return "upstream_unavailable"


def _as_iso(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), tz=timezone.utc).isoformat()
        except Exception:
            return ""
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return ""
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
        except Exception:
            return ""
    return ""


def _extract_as_of(payload: object) -> str:
    if isinstance(payload, dict):
        for key in ("as_of", "updated_at", "timestamp", "ts"):
            iso = _as_iso(payload.get(key))
            if iso:
                return iso
        return ""

    if isinstance(payload, list) and payload:
        latest = ""
        for item in payload:
            if not isinstance(item, dict):
                continue
            for key in ("as_of", "updated_at", "timestamp", "ts", "time"):
                iso = _as_iso(item.get(key))
                if iso and (not latest or iso > latest):
                    latest = iso
        return latest
    return ""


def _build_meta(
    *,
    provider: str,
    source_type: str,
    started_at: float,
    payload: object,
    fallback_reason: str | None,
    currency: str = "",
    calc_window: str = "",
) -> dict[str, object]:
    latency_ms = int((time.perf_counter() - started_at) * 1000)
    fallback_used = bool(fallback_reason)
    confidence = 0.35 if fallback_used else 0.85
    as_of = _extract_as_of(payload) or _utc_now_iso()
    return {
        "provider": provider,
        "source_type": source_type,
        "as_of": as_of,
        "latency_ms": latency_ms,
        "fallback_used": fallback_used,
        "confidence": confidence,
        "currency": currency,
        "calc_window": calc_window,
        "fallback_reason": fallback_reason,
    }


DEFAULT_WATCHLIST = [
    WatchItem(symbol="AAPL", type="equity", name="Apple Inc."),
    WatchItem(symbol="TSLA", type="equity", name="Tesla Inc."),
    WatchItem(symbol="^GSPC", type="index", name="S&P 500"),
    WatchItem(symbol="SPY", type="etf", name="SPDR S&P 500"),
    WatchItem(symbol="BTC-USD", type="crypto", name="Bitcoin"),
]


def _filter_charts_by_capabilities(raw_charts: dict, capabilities: Capabilities) -> dict:
    cap_chart_map = {
        "revenue_trend": capabilities.revenue_trend,
        "segment_mix": capabilities.segment_mix,
        "sector_weights": capabilities.sector_weights,
        "top_constituents": capabilities.top_constituents,
        "holdings": capabilities.holdings,
        "market_chart": capabilities.market_chart,
    }
    return {
        chart_key: raw_charts[chart_key]
        for chart_key, enabled in cap_chart_map.items()
        if enabled and chart_key in raw_charts
    }


@dashboard_router.get("", response_model=DashboardResponse)
async def get_dashboard(
    symbol: str = Query(..., min_length=1, description="资产代码"),
    type: str = Query(None, description="资产类型覆盖（可选）"),
):
    if not is_valid_symbol(symbol):
        raise symbol_not_found(symbol)

    active_asset = resolve_asset(symbol)
    logger.info("[Dashboard] Resolved %s -> %s", symbol, active_asset.type)
    if type and type in {"equity", "index", "etf", "crypto", "portfolio"}:
        active_asset.type = type

    capabilities = select_capabilities(active_asset)
    state = DashboardState(
        active_asset=active_asset,
        capabilities=capabilities,
        watchlist=DEFAULT_WATCHLIST,
        layout_prefs=LayoutPrefs(),
        news_mode=NewsModeConfig(mode="market"),
        debug={
            "mock": False,
            "resolver_type": active_asset.type,
            "data_source": "multi-source",
            "cache": {"snapshot": False, "charts": False, "news": False, "macro_snapshot": False},
        },
    )

    asset_type = active_asset.type
    sym = active_asset.symbol
    fallback_reasons: list[str] = []
    meta_map: dict[str, dict[str, object]] = {}

    def _set_meta(
        key: str,
        *,
        provider: str,
        source_type: str,
        payload: object,
        started_at: float,
        fallback_reason: str | None = None,
        currency: str = "",
        calc_window: str = "",
    ) -> None:
        meta_map[key] = _build_meta(
            provider=provider,
            source_type=source_type,
            started_at=started_at,
            payload=payload,
            fallback_reason=fallback_reason,
            currency=currency,
            calc_window=calc_window,
        )

    snapshot_started = time.perf_counter()
    snapshot = dashboard_cache.get(symbol, "snapshot")
    snapshot_source_type = "cache"
    snapshot_fallback_reason: Optional[str] = None
    if snapshot is None:
        snapshot_source_type = "snapshot"
        snapshot = await _run_blocking("fetch_snapshot", fetch_snapshot, sym, asset_type)
        if snapshot is None:
            snapshot = {}
            snapshot_fallback_reason = "snapshot_unavailable"
            fallback_reasons.append(snapshot_fallback_reason)
        dashboard_cache.set(symbol, "snapshot", snapshot, ttl=dashboard_cache.TTL_SNAPSHOT)
    else:
        state.debug["cache"]["snapshot"] = True
    _set_meta(
        "snapshot",
        provider="yfinance",
        source_type=snapshot_source_type,
        payload=snapshot,
        started_at=snapshot_started,
        fallback_reason=snapshot_fallback_reason,
        currency="USD",
    )

    charts_started = time.perf_counter()
    chart_meta_info: dict[str, tuple[str, str, str]] = {
        "market_chart": ("market_data", "timeseries", "1y/1d"),
    }
    if asset_type == "equity":
        chart_meta_info["revenue_trend"] = ("yfinance", "fundamental", "8Q")
        chart_meta_info["segment_mix"] = ("fmp", "fundamental", "")
    elif asset_type == "etf":
        chart_meta_info["sector_weights"] = ("fmp", "allocation", "")
        chart_meta_info["holdings"] = ("fmp", "holdings", "top50")
    elif asset_type == "index":
        chart_meta_info["sector_weights"] = ("fmp", "allocation", "")
        chart_meta_info["top_constituents"] = ("fmp", "constituents", "top10")

    charts = dashboard_cache.get(symbol, "charts")
    if charts is None:
        chart_tasks = {
            "market_chart": _run_blocking("fetch_market_chart", fetch_market_chart, sym, period="1y", interval="1d")
        }
        chart_started_map = {key: time.perf_counter() for key in chart_tasks}

        if asset_type == "equity":
            chart_tasks["revenue_trend"] = _run_blocking("fetch_revenue_trend", fetch_revenue_trend, sym)
            chart_tasks["segment_mix"] = _run_blocking("fetch_segment_mix", fetch_segment_mix, sym)
            chart_started_map["revenue_trend"] = time.perf_counter()
            chart_started_map["segment_mix"] = time.perf_counter()
        elif asset_type == "etf":
            chart_tasks["sector_weights"] = _run_blocking("fetch_sector_weights", fetch_sector_weights, sym, asset_type)
            chart_tasks["holdings"] = _run_blocking("fetch_holdings", fetch_holdings, sym, asset_type, limit=50)
            chart_started_map["sector_weights"] = time.perf_counter()
            chart_started_map["holdings"] = time.perf_counter()
        elif asset_type == "index":
            chart_tasks["sector_weights"] = _run_blocking("fetch_sector_weights", fetch_sector_weights, sym, asset_type)
            chart_tasks["top_constituents"] = _run_blocking("fetch_top_constituents", fetch_top_constituents, sym, asset_type, limit=10)
            chart_started_map["sector_weights"] = time.perf_counter()
            chart_started_map["top_constituents"] = time.perf_counter()

        results = await asyncio.gather(*chart_tasks.values())
        charts = {}
        has_any_failure = False
        for key, value in zip(chart_tasks.keys(), results):
            fallback_reason = None
            if value is None:
                fallback_reason = f"{key}_unavailable"
                fallback_reasons.append(fallback_reason)
                charts[key] = []
                has_any_failure = True
            else:
                charts[key] = value

            provider, source_type, calc_window = chart_meta_info.get(key, ("dashboard", "timeseries", ""))
            _set_meta(
                key,
                provider=provider,
                source_type=source_type,
                payload=charts[key],
                started_at=chart_started_map.get(key, charts_started),
                fallback_reason=fallback_reason,
                currency="USD",
                calc_window=calc_window,
            )

        # Only cache if we got valid data; never cache empty/failed results
        if has_any_failure and not charts.get("market_chart"):
            # All critical data failed — use very short TTL so next request retries
            dashboard_cache.set(symbol, "charts", charts, ttl=15)
        elif has_any_failure:
            # Some non-critical charts failed — short TTL
            dashboard_cache.set(symbol, "charts", charts, ttl=30)
        else:
            dashboard_cache.set(symbol, "charts", charts, ttl=dashboard_cache.TTL_CHARTS)
    else:
        state.debug["cache"]["charts"] = True
        for key, payload in charts.items():
            provider, _, calc_window = chart_meta_info.get(key, ("dashboard_cache", "cache", ""))
            _set_meta(
                key,
                provider=provider,
                source_type="cache",
                payload=payload,
                started_at=charts_started,
                currency="USD",
                calc_window=calc_window,
            )

    v2_valuation = None
    v2_financials = None
    v2_technicals = None
    v2_peers = None
    v2_valuation_fallback: Optional[str] = None
    v2_financials_fallback: Optional[str] = None
    v2_technicals_fallback: Optional[str] = None
    v2_peers_fallback: Optional[str] = None

    # Phase G2 new data
    g2_earnings_history = None
    g2_analyst_targets = None
    g2_recommendations = None
    g2_indicator_series = None

    if asset_type == "equity":
        v2_started_map = {
            "valuation": time.perf_counter(),
            "financials": time.perf_counter(),
            "technicals": time.perf_counter(),
            "peers": time.perf_counter(),
        }
        v2_fetch_config: dict[str, dict[str, object]] = {
            "valuation": {
                "fetch_name": "fetch_valuation",
                "fn": fetch_valuation,
                "timeout": 6.0,
                "ttl": dashboard_cache.TTL_VALUATION,
            },
            "financials": {
                "fetch_name": "fetch_financials",
                "fn": fetch_financial_statements,
                "timeout": 10.0,
                "ttl": dashboard_cache.TTL_FINANCIALS,
            },
            "technicals": {
                "fetch_name": "fetch_technicals",
                "fn": fetch_technical_indicators,
                "timeout": 8.0,
                "ttl": dashboard_cache.TTL_TECHNICALS,
            },
            "peers": {
                "fetch_name": "fetch_peers",
                "fn": fetch_peer_comparison,
                "timeout": 18.0,
                "ttl": dashboard_cache.TTL_PEERS,
            },
        }
        g2_fetch_config: dict[str, dict[str, object]] = {
            "earnings_history": {
                "fetch_name": "fetch_earnings",
                "fn": fetch_earnings_history,
                "timeout": 8.0,
                "ttl": dashboard_cache.TTL_EARNINGS,
            },
            "analyst_targets": {
                "fetch_name": "fetch_analyst_targets",
                "fn": fetch_analyst_targets,
                "timeout": 6.0,
                "ttl": dashboard_cache.TTL_ANALYST,
            },
            "recommendations": {
                "fetch_name": "fetch_recommendations",
                "fn": fetch_recommendations,
                "timeout": 6.0,
                "ttl": dashboard_cache.TTL_ANALYST,
            },
            "indicator_series": {
                "fetch_name": "fetch_indicator_series",
                "fn": fetch_indicator_series,
                "timeout": 8.0,
                "ttl": dashboard_cache.TTL_TECHNICALS,
            },
        }
        v2_meta_info: dict[str, tuple[str, str, str]] = {
            "valuation": ("yfinance", "fundamental", "TTM"),
            "financials": ("yfinance", "financial_statement", "8Q"),
            "technicals": ("yfinance", "technical", "1y/1d"),
            "peers": ("peer_service", "peer_group", ""),
        }
        v2_payload_map: dict[str, object] = {}
        v2_reason_map: dict[str, str | None] = {}
        v2_source_map: dict[str, str] = {}
        v2_tasks: dict[str, asyncio.Task[Any]] = {}

        for key, cfg in v2_fetch_config.items():
            cached = dashboard_cache.get(symbol, key)
            if cached is not None:
                if _is_failure_marker(cached):
                    fallback_reason = _failure_reason_from_marker(cached) or f"{key}_unavailable"
                    v2_payload_map[key] = {}
                    v2_reason_map[key] = fallback_reason
                    v2_source_map[key] = "failure_cache"
                    fallback_reasons.append(fallback_reason)
                else:
                    v2_payload_map[key] = cached
                    v2_reason_map[key] = None
                    v2_source_map[key] = "cache"
                    state.debug["cache"][key] = True
                continue

            fetch_name = str(cfg["fetch_name"])
            fetch_fn = cfg["fn"]
            timeout = float(cfg["timeout"])
            singleflight_key = f"{sym.upper()}:{key}"
            v2_tasks[key] = asyncio.create_task(
                _singleflight_call(
                    singleflight_key,
                    lambda fetch_name=fetch_name, fetch_fn=fetch_fn, timeout=timeout: _run_blocking(
                        fetch_name,
                        fetch_fn,
                        sym,
                        timeout=timeout,
                    ),
                )
            )

        if v2_tasks:
            task_results = await asyncio.gather(*v2_tasks.values(), return_exceptions=True)
            for key, result in zip(v2_tasks.keys(), task_results):
                cfg = v2_fetch_config[key]
                if isinstance(result, BaseException):
                    fallback_reason = f"{key}_error: {result}"
                    v2_payload_map[key] = {}
                    v2_reason_map[key] = fallback_reason
                    v2_source_map[key] = "error"
                    fallback_reasons.append(fallback_reason)
                    dashboard_cache.set(
                        symbol,
                        key,
                        _make_failure_marker(fallback_reason),
                        ttl=_DASHBOARD_FAILURE_TTL_SECONDS,
                    )
                    continue

                if result is None:
                    fallback_reason = f"{key}_unavailable"
                    v2_payload_map[key] = {}
                    v2_reason_map[key] = fallback_reason
                    v2_source_map[key] = "miss"
                    fallback_reasons.append(fallback_reason)
                    dashboard_cache.set(
                        symbol,
                        key,
                        _make_failure_marker(fallback_reason),
                        ttl=_DASHBOARD_FAILURE_TTL_SECONDS,
                    )
                    continue

                v2_payload_map[key] = result
                v2_reason_map[key] = None
                v2_source_map[key] = "live"
                dashboard_cache.set(
                    symbol,
                    key,
                    result,
                    ttl=int(cfg["ttl"]),
                )

        for key in v2_fetch_config:
            payload = v2_payload_map.get(key, {})
            fallback_reason = v2_reason_map.get(key)
            source_kind = v2_source_map.get(key, "miss")

            if key == "valuation":
                if fallback_reason:
                    v2_valuation_fallback = fallback_reason
                else:
                    v2_valuation = payload if isinstance(payload, dict) else None
            elif key == "financials":
                if fallback_reason:
                    v2_financials_fallback = fallback_reason
                else:
                    v2_financials = payload if isinstance(payload, dict) else None
            elif key == "technicals":
                if fallback_reason:
                    v2_technicals_fallback = fallback_reason
                else:
                    v2_technicals = payload if isinstance(payload, dict) else None
            elif key == "peers":
                if fallback_reason:
                    v2_peers_fallback = fallback_reason
                else:
                    v2_peers = payload if isinstance(payload, dict) else None

            provider, live_source_type, calc_window = v2_meta_info[key]
            source_type = live_source_type
            if source_kind == "cache":
                source_type = "cache"
            elif source_kind == "failure_cache":
                source_type = "failure_cache"

            _set_meta(
                key,
                provider=provider,
                source_type=source_type,
                payload=payload if isinstance(payload, (dict, list)) else {},
                started_at=v2_started_map.get(key, charts_started),
                fallback_reason=fallback_reason,
                currency="USD",
                calc_window=calc_window,
            )

        g2_payload_map: dict[str, object] = {}
        g2_tasks: dict[str, asyncio.Task[Any]] = {}
        for key, cfg in g2_fetch_config.items():
            cached = dashboard_cache.get(symbol, key)
            if cached is not None:
                if _is_failure_marker(cached):
                    fallback_reason = _failure_reason_from_marker(cached) or f"{key}_unavailable"
                    fallback_reasons.append(fallback_reason)
                    g2_payload_map[key] = None
                else:
                    g2_payload_map[key] = cached
                    state.debug["cache"][key] = True
                continue

            fetch_name = str(cfg["fetch_name"])
            fetch_fn = cfg["fn"]
            timeout = float(cfg["timeout"])
            singleflight_key = f"{sym.upper()}:{key}"
            g2_tasks[key] = asyncio.create_task(
                _singleflight_call(
                    singleflight_key,
                    lambda fetch_name=fetch_name, fetch_fn=fetch_fn, timeout=timeout: _run_blocking(
                        fetch_name,
                        fetch_fn,
                        sym,
                        timeout=timeout,
                    ),
                )
            )

        if g2_tasks:
            g2_results = await asyncio.gather(*g2_tasks.values(), return_exceptions=True)
            for key, result in zip(g2_tasks.keys(), g2_results):
                cfg = g2_fetch_config[key]
                if isinstance(result, BaseException):
                    fallback_reason = f"{key}_error: {result}"
                    fallback_reasons.append(fallback_reason)
                    g2_payload_map[key] = None
                    dashboard_cache.set(
                        symbol,
                        key,
                        _make_failure_marker(fallback_reason),
                        ttl=_DASHBOARD_FAILURE_TTL_SECONDS,
                    )
                    continue

                if result is None:
                    fallback_reason = f"{key}_unavailable"
                    fallback_reasons.append(fallback_reason)
                    g2_payload_map[key] = None
                    dashboard_cache.set(
                        symbol,
                        key,
                        _make_failure_marker(fallback_reason),
                        ttl=_DASHBOARD_FAILURE_TTL_SECONDS,
                    )
                    continue

                g2_payload_map[key] = result
                dashboard_cache.set(
                    symbol,
                    key,
                    result,
                    ttl=int(cfg["ttl"]),
                )

        g2_earnings_history = g2_payload_map.get("earnings_history")
        g2_analyst_targets = g2_payload_map.get("analyst_targets")
        g2_recommendations = g2_payload_map.get("recommendations")
        g2_indicator_series = g2_payload_map.get("indicator_series")

    news_started = time.perf_counter()
    news = dashboard_cache.get(symbol, "news")
    news_source_type = "cache"
    news_fallback_reason: Optional[str] = None
    if news is None:
        news_source_type = "news"
        fetched_news = await _run_blocking(
            "fetch_news",
            fetch_news,
            sym,
            limit=20,
            timeout=_DASHBOARD_NEWS_FETCH_TIMEOUT_SECONDS,
        )
        if fetched_news is None:
            fetched_news = {"market": [], "impact": []}
            news_fallback_reason = "news_unavailable"
            fallback_reasons.append(news_fallback_reason)
        news = fetched_news
        dashboard_cache.set(symbol, "news", news, ttl=dashboard_cache.TTL_NEWS)
    else:
        state.debug["cache"]["news"] = True

    _set_meta(
        "news_market",
        provider="hybrid_news",
        source_type=news_source_type,
        payload=(news or {}).get("market", []),
        started_at=news_started,
        fallback_reason=news_fallback_reason,
        calc_window="latest20",
    )
    _set_meta(
        "news_impact",
        provider="hybrid_news",
        source_type=news_source_type,
        payload=(news or {}).get("impact", []),
        started_at=news_started,
        fallback_reason=news_fallback_reason,
        calc_window="latest20",
    )

    macro_started = time.perf_counter()
    # macro_snapshot is global (not symbol-specific) — use fixed key to avoid N redundant copies
    macro_snapshot = dashboard_cache.get("__GLOBAL__", "macro_snapshot")
    macro_source_type = "cache"
    macro_fallback_reason: Optional[str] = None
    if macro_snapshot is None:
        macro_source_type = "macro_snapshot"
        macro_snapshot = await _run_blocking("fetch_macro_snapshot", fetch_macro_snapshot, timeout=12.0)
        if not isinstance(macro_snapshot, dict) or not macro_snapshot:
            macro_snapshot = {}
            macro_fallback_reason = "macro_snapshot_unavailable"
            fallback_reasons.append(macro_fallback_reason)
        dashboard_cache.set("__GLOBAL__", "macro_snapshot", macro_snapshot, ttl=dashboard_cache.TTL_MACRO)
    else:
        state.debug["cache"]["macro_snapshot"] = True

    _set_meta(
        "macro_snapshot",
        provider="macro_tools",
        source_type=macro_source_type,
        payload=macro_snapshot,
        started_at=macro_started,
        fallback_reason=macro_fallback_reason,
        calc_window="near_real_time",
    )

    raw_data = {
        "snapshot": snapshot or {},
        "charts": charts or {},
        "news": news or {},
        "macro_snapshot": macro_snapshot or {},
    }
    filtered_charts = _filter_charts_by_capabilities(raw_data.get("charts", {}), capabilities)
    if fallback_reasons:
        state.debug["fallback_reasons"] = fallback_reasons

    try:
        data = DashboardData(
            snapshot=raw_data.get("snapshot", {}),
            charts=filtered_charts,
            news=raw_data.get("news", {}),
            meta=meta_map,
            valuation=ValuationData(**v2_valuation) if v2_valuation else None,
            valuation_fallback_reason=v2_valuation_fallback,
            financials=FinancialStatement(**v2_financials) if v2_financials else None,
            financials_fallback_reason=v2_financials_fallback,
            technicals=TechnicalData(**v2_technicals) if v2_technicals else None,
            technicals_fallback_reason=v2_technicals_fallback,
            peers=PeerComparisonData(**v2_peers) if v2_peers else None,
            peers_fallback_reason=v2_peers_fallback,
            macro_snapshot=MacroSnapshotData(**raw_data["macro_snapshot"]) if raw_data["macro_snapshot"] else None,
            macro_snapshot_fallback_reason=macro_fallback_reason,
            # Phase G2 new data
            earnings_history=[EarningsHistoryEntry(**e) for e in g2_earnings_history] if g2_earnings_history else None,
            analyst_targets=AnalystTargets(**g2_analyst_targets) if g2_analyst_targets else None,
            recommendations=RecommendationsSummary(**g2_recommendations) if g2_recommendations else None,
            indicator_series=IndicatorSeries(**g2_indicator_series) if g2_indicator_series else None,
        )
    except Exception as exc:
        logger.warning("[Dashboard] DashboardData construction failed: %s", exc)
        data = DashboardData(
            snapshot=raw_data.get("snapshot", {}),
            charts=filtered_charts,
            news={"market": [], "impact": []},
            meta=meta_map,
        )
        state.debug["data_construction_error"] = str(exc)

    return DashboardResponse(success=True, state=state, data=data)


@dashboard_router.get("/insights", response_model=DashboardInsightsResponse)
async def get_dashboard_insights(
    symbol: str = Query(..., min_length=1, description="资产代码"),
    force: bool = Query(False, description="强制刷新缓存"),
):
    """
    AI 洞察端点 — 为 Dashboard 各标签页提供 LLM 生成的分析卡片。

    独立于主 Dashboard API 以隔离 LLM 延迟（3-6s）。
    前端应与 GET /api/dashboard 并行请求此端点。

    缓存策略: Fresh (<1h) 直接返回 / Stale (1-4h) 返回旧值+后台刷新 / Expired 重新生成
    """
    if not is_valid_symbol(symbol):
        raise symbol_not_found(symbol)

    from backend.dashboard.insights_engine import get_insights_orchestrator

    orchestrator = get_insights_orchestrator()
    return await orchestrator.generate(symbol, force=force)


@dashboard_router.get("/health")
async def dashboard_health():
    """Dashboard 健康检查端点"""
    return {"status": "healthy", "cache": dashboard_cache.stats()}

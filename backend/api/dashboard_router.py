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
from typing import Optional

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


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
        for key, value in zip(chart_tasks.keys(), results):
            fallback_reason = None
            if value is None:
                fallback_reason = f"{key}_unavailable"
                fallback_reasons.append(fallback_reason)
                charts[key] = []
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
        v2_tasks = {
            "valuation": _run_blocking("fetch_valuation", fetch_valuation, sym, timeout=6.0),
            "financials": _run_blocking("fetch_financials", fetch_financial_statements, sym, timeout=10.0),
            "technicals": _run_blocking("fetch_technicals", fetch_technical_indicators, sym, timeout=8.0),
            "peers": _run_blocking("fetch_peers", fetch_peer_comparison, sym, timeout=18.0),
        }

        # Phase G2: Additional data fetches (parallel with v2)
        g2_tasks = {
            "earnings_history": _run_blocking("fetch_earnings", fetch_earnings_history, sym, timeout=8.0),
            "analyst_targets": _run_blocking("fetch_analyst_targets", fetch_analyst_targets, sym, timeout=6.0),
            "recommendations": _run_blocking("fetch_recommendations", fetch_recommendations, sym, timeout=6.0),
            "indicator_series": _run_blocking("fetch_indicator_series", fetch_indicator_series, sym, timeout=8.0),
        }
        v2_meta_info: dict[str, tuple[str, str, str]] = {
            "valuation": ("yfinance", "fundamental", "TTM"),
            "financials": ("yfinance", "financial_statement", "8Q"),
            "technicals": ("yfinance", "technical", "1y/1d"),
            "peers": ("peer_service", "peer_group", ""),
        }
        v2_results = await asyncio.gather(*v2_tasks.values(), return_exceptions=True)
        v2_map = dict(zip(v2_tasks.keys(), v2_results))

        # Phase G2: gather in parallel
        g2_results = await asyncio.gather(*g2_tasks.values(), return_exceptions=True)
        g2_map = dict(zip(g2_tasks.keys(), g2_results))

        # Process G2 results (best-effort, no fallback reasons needed)
        for key, result in g2_map.items():
            if isinstance(result, BaseException) or result is None:
                continue
            if key == "earnings_history":
                g2_earnings_history = result
            elif key == "analyst_targets":
                g2_analyst_targets = result
            elif key == "recommendations":
                g2_recommendations = result
            elif key == "indicator_series":
                g2_indicator_series = result

        for key, result in v2_map.items():
            fallback_reason = None
            payload = result if not isinstance(result, BaseException) else {}
            if isinstance(result, BaseException):
                fallback_reason = f"{key}_error: {result}"
                fallback_reasons.append(fallback_reason)
            elif result is None:
                fallback_reason = f"{key}_unavailable"
                fallback_reasons.append(fallback_reason)
                payload = {}

            if key == "valuation":
                if fallback_reason:
                    v2_valuation_fallback = fallback_reason
                else:
                    v2_valuation = result
            elif key == "financials":
                if fallback_reason:
                    v2_financials_fallback = fallback_reason
                else:
                    v2_financials = result
            elif key == "technicals":
                if fallback_reason:
                    v2_technicals_fallback = fallback_reason
                else:
                    v2_technicals = result
            elif key == "peers":
                if fallback_reason:
                    v2_peers_fallback = fallback_reason
                else:
                    v2_peers = result

            provider, source_type, calc_window = v2_meta_info[key]
            _set_meta(
                key,
                provider=provider,
                source_type=source_type,
                payload=payload,
                started_at=v2_started_map.get(key, charts_started),
                fallback_reason=fallback_reason,
                currency="USD",
                calc_window=calc_window,
            )

        # Keep v2/G2 payloads in shared dashboard cache so /api/dashboard/insights
        # consumes the same source of truth and avoids cross-endpoint drift.
        if v2_valuation is not None:
            dashboard_cache.set(symbol, "valuation", v2_valuation, ttl=dashboard_cache.TTL_VALUATION)
        if v2_financials is not None:
            dashboard_cache.set(symbol, "financials", v2_financials, ttl=dashboard_cache.TTL_FINANCIALS)
        if v2_technicals is not None:
            dashboard_cache.set(symbol, "technicals", v2_technicals, ttl=dashboard_cache.TTL_TECHNICALS)
        if v2_peers is not None:
            dashboard_cache.set(symbol, "peers", v2_peers, ttl=dashboard_cache.TTL_PEERS)

        if g2_earnings_history is not None:
            dashboard_cache.set(symbol, "earnings_history", g2_earnings_history, ttl=dashboard_cache.TTL_EARNINGS)
        if g2_analyst_targets is not None:
            dashboard_cache.set(symbol, "analyst_targets", g2_analyst_targets, ttl=dashboard_cache.TTL_ANALYST)
        if g2_recommendations is not None:
            dashboard_cache.set(symbol, "recommendations", g2_recommendations, ttl=dashboard_cache.TTL_ANALYST)
        if g2_indicator_series is not None:
            dashboard_cache.set(symbol, "indicator_series", g2_indicator_series, ttl=dashboard_cache.TTL_TECHNICALS)

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
    macro_snapshot = dashboard_cache.get(symbol, "macro_snapshot")
    macro_source_type = "cache"
    macro_fallback_reason: Optional[str] = None
    if macro_snapshot is None:
        macro_source_type = "macro_snapshot"
        macro_snapshot = await _run_blocking("fetch_macro_snapshot", fetch_macro_snapshot, timeout=12.0)
        if not isinstance(macro_snapshot, dict) or not macro_snapshot:
            macro_snapshot = {}
            macro_fallback_reason = "macro_snapshot_unavailable"
            fallback_reasons.append(macro_fallback_reason)
        dashboard_cache.set(symbol, "macro_snapshot", macro_snapshot, ttl=dashboard_cache.TTL_MACRO)
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

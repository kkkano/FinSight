"""
Dashboard API 路由

提供 Dashboard 聚合接口，根据 symbol 解析资产类型并返回结构化数据。

v2.0 重构：使用多源数据服务层（data_service.py），支持 10+ 数据源回退策略
"""
import asyncio
import logging
import os
from functools import partial
from fastapi import APIRouter, Query
from backend.dashboard.schemas import (
    DashboardState,
    DashboardResponse,
    DashboardData,
    Capabilities,
    WatchItem,
    LayoutPrefs,
    NewsModeConfig,
)
from backend.dashboard.asset_resolver import resolve_asset, is_valid_symbol
from backend.dashboard.widget_selector import select_capabilities
from backend.dashboard.cache import dashboard_cache
from backend.dashboard.errors import symbol_not_found

# 导入多源数据服务
from backend.dashboard.data_service import (
    fetch_market_chart,
    fetch_snapshot,
    fetch_revenue_trend,
    fetch_segment_mix,
    fetch_news,
    fetch_sector_weights,
    fetch_top_constituents,
    fetch_holdings,
)

logger = logging.getLogger(__name__)

dashboard_router = APIRouter(prefix="/api/dashboard", tags=["Dashboard"])

_DASHBOARD_FETCH_TIMEOUT_SECONDS = 15.0
_DASHBOARD_NEWS_FETCH_TIMEOUT_SECONDS = float(
    os.getenv("FINSIGHT_DASHBOARD_NEWS_TIMEOUT", "45")
)


async def _run_blocking(name: str, fn, *args, timeout: float = _DASHBOARD_FETCH_TIMEOUT_SECONDS, **kwargs):
    bound = partial(fn, *args, **kwargs)
    try:
        return await asyncio.wait_for(asyncio.to_thread(bound), timeout=timeout)
    except asyncio.TimeoutError:
        logger.warning("[Dashboard] %s timed out (%.1fs)", name, timeout)
    except Exception as exc:
        logger.warning("[Dashboard] %s failed: %s", name, exc)
    return None


# ── 默认 Watchlist ──────────────────────────────────────────
DEFAULT_WATCHLIST = [
    WatchItem(symbol="AAPL", type="equity", name="Apple Inc."),
    WatchItem(symbol="TSLA", type="equity", name="Tesla Inc."),
    WatchItem(symbol="^GSPC", type="index", name="S&P 500"),
    WatchItem(symbol="SPY", type="etf", name="SPDR S&P 500"),
    WatchItem(symbol="BTC-USD", type="crypto", name="Bitcoin"),
]


def _filter_charts_by_capabilities(
    raw_charts: dict,
    capabilities: Capabilities,
) -> dict:
    """
    根据能力集过滤图表数据

    只返回 capabilities 中启用的图表类型

    Args:
        raw_charts: 原始图表数据
        capabilities: 能力集合

    Returns:
        dict: 过滤后的图表数据
    """
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


# ── 路由处理 ────────────────────────────────────────────────


@dashboard_router.get("", response_model=DashboardResponse)
async def get_dashboard(
    symbol: str = Query(..., min_length=1, description="资产代码"),
    type: str = Query(None, description="资产类型覆盖（可选）"),
):
    """
    Dashboard 聚合接口

    根据 symbol 解析资产类型 → 选择能力集 → 返回聚合数据。

    Args:
        symbol: 资产代码（如 AAPL, ^GSPC, SPY, BTC-USD）
        type: 可选的资产类型覆盖

    Returns:
        DashboardResponse: 包含 state 和 data 的响应

    Raises:
        HTTPException: 当 symbol 无效时返回 404
    """
    # 0. 验证 symbol 格式
    if not is_valid_symbol(symbol):
        raise symbol_not_found(symbol)

    # 1. 解析资产
    active_asset = resolve_asset(symbol)
    logger.info(f"[Dashboard] Resolved {symbol} -> {active_asset.type}")

    # 可选：类型覆盖
    if type and type in {"equity", "index", "etf", "crypto", "portfolio"}:
        active_asset.type = type

    # 2. 选择能力集
    capabilities = select_capabilities(active_asset)

    # 3. 构造状态
    state = DashboardState(
        active_asset=active_asset,
        capabilities=capabilities,
        watchlist=DEFAULT_WATCHLIST,
        layout_prefs=LayoutPrefs(),
        news_mode=NewsModeConfig(mode="market"),
        debug={
            "mock": False,
            "resolver_type": active_asset.type,
            "data_source": "multi-source",  # 使用多源回退策略
            "cache": {
                "snapshot": False,
                "charts": False,
                "news": False,
            },
        },
    )

    asset_type = active_asset.type
    sym = active_asset.symbol
    fallback_reasons: list[str] = []

    # 4. 聚合数据 - 使用多源数据服务层（支持 10+ 数据源回退）
    # 4.1 Snapshot 数据
    snapshot = dashboard_cache.get(symbol, "snapshot")
    if snapshot is None:
        snapshot = await _run_blocking("fetch_snapshot", fetch_snapshot, sym, asset_type)
        if snapshot is None:
            snapshot = {}
            fallback_reasons.append("snapshot_unavailable")
        dashboard_cache.set(symbol, "snapshot", snapshot, ttl=dashboard_cache.TTL_SNAPSHOT)
    else:
        state.debug["cache"]["snapshot"] = True

    # 4.2 图表数据（根据资产类型获取不同数据）
    charts = dashboard_cache.get(symbol, "charts")
    if charts is None:
        chart_tasks = {
            "market_chart": _run_blocking("fetch_market_chart", fetch_market_chart, sym, period="1y", interval="1d"),
        }

        # Equity 特有数据：营收趋势、分部收入
        if asset_type == "equity":
            chart_tasks["revenue_trend"] = _run_blocking("fetch_revenue_trend", fetch_revenue_trend, sym)
            chart_tasks["segment_mix"] = _run_blocking("fetch_segment_mix", fetch_segment_mix, sym)

        # ETF 特有数据：板块权重、持仓
        elif asset_type == "etf":
            chart_tasks["sector_weights"] = _run_blocking("fetch_sector_weights", fetch_sector_weights, sym, asset_type)
            chart_tasks["holdings"] = _run_blocking("fetch_holdings", fetch_holdings, sym, asset_type, limit=50)

        # Index 特有数据：板块权重、成分股
        elif asset_type == "index":
            chart_tasks["sector_weights"] = _run_blocking("fetch_sector_weights", fetch_sector_weights, sym, asset_type)
            chart_tasks["top_constituents"] = _run_blocking("fetch_top_constituents", fetch_top_constituents, sym, asset_type, limit=10)

        results = await asyncio.gather(*chart_tasks.values())
        charts = {}
        for key, value in zip(chart_tasks.keys(), results):
            if value is None:
                fallback_reasons.append(f"{key}_unavailable")
                charts[key] = []
            else:
                charts[key] = value

        dashboard_cache.set(symbol, "charts", charts, ttl=dashboard_cache.TTL_CHARTS)
    else:
        state.debug["cache"]["charts"] = True

    # 4.3 新闻数据 - 使用多源回退（yfinance → Finnhub → Alpha Vantage → 搜索）
    news = dashboard_cache.get(symbol, "news")
    if news is None:
        fetched_news = await _run_blocking("fetch_news", fetch_news, sym, limit=20, timeout=_DASHBOARD_NEWS_FETCH_TIMEOUT_SECONDS)
        if fetched_news is None:
            fetched_news = {"market": [], "impact": []}
            fallback_reasons.append("news_unavailable")
        news = fetched_news
        dashboard_cache.set(symbol, "news", news, ttl=dashboard_cache.TTL_NEWS)
    else:
        state.debug["cache"]["news"] = True

    raw_data = {
        "snapshot": snapshot or {},
        "charts": charts or {},
        "news": news or {},
    }

    # 5. 过滤：只返回 capabilities 允许的 chart 键
    filtered_charts = _filter_charts_by_capabilities(
        raw_data.get("charts", {}),
        capabilities,
    )

    if fallback_reasons:
        state.debug["fallback_reasons"] = fallback_reasons

    try:
        data = DashboardData(
            snapshot=raw_data.get("snapshot", {}),
            charts=filtered_charts,
            news=raw_data.get("news", {}),
        )
    except Exception as exc:
        logger.warning("[Dashboard] DashboardData construction failed: %s", exc)
        data = DashboardData(
            snapshot=raw_data.get("snapshot", {}),
            charts=filtered_charts,
            news={"market": [], "impact": []},
        )
        state.debug["data_construction_error"] = str(exc)

    return DashboardResponse(success=True, state=state, data=data)


@dashboard_router.get("/health")
async def dashboard_health():
    """Dashboard 健康检查端点"""
    cache_stats = dashboard_cache.stats()
    return {
        "status": "healthy",
        "cache": cache_stats,
    }

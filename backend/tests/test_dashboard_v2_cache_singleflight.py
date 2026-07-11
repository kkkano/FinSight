# -*- coding: utf-8 -*-
import asyncio

import pytest

import backend.api.dashboard_router as dashboard_router_module
from backend.dashboard.cache import DashboardCache
from backend.dashboard.insights_engine import InsightsOrchestrator


def test_dashboard_failure_marker_roundtrip():
    marker = dashboard_router_module._make_failure_marker("peers_unavailable")
    assert dashboard_router_module._is_failure_marker(marker) is True
    assert dashboard_router_module._failure_reason_from_marker(marker) == "peers_unavailable"
    assert dashboard_router_module._failure_reason_from_marker({}) is None


@pytest.mark.asyncio
async def test_dashboard_singleflight_deduplicates_same_key():
    call_count = 0

    async def slow_fetch():
        nonlocal call_count
        call_count += 1
        await asyncio.sleep(0.05)
        return {"ok": True}

    first, second = await asyncio.gather(
        dashboard_router_module._singleflight_call("MSFT:valuation", slow_fetch),
        dashboard_router_module._singleflight_call("MSFT:valuation", slow_fetch),
    )

    assert first == {"ok": True}
    assert second == {"ok": True}
    assert call_count == 1
    assert "MSFT:valuation" not in dashboard_router_module._singleflight_tasks


def test_insights_collect_data_ignores_failure_marker():
    cache = DashboardCache()
    cache.set(
        "AAPL",
        "technicals",
        {"__dashboard_failure__": True, "reason": "technicals_unavailable"},
        ttl=60,
    )
    cache.set(
        "AAPL",
        "news",
        {"market": [{"title": "Macro easing"}], "impact": []},
        ttl=60,
    )

    orchestrator = InsightsOrchestrator(cache=cache)
    data = orchestrator._collect_dashboard_data("AAPL")

    assert data["technicals"] == {}
    assert len(data["news"].get("market", [])) == 1


@pytest.mark.asyncio
async def test_dashboard_g2_payloads_publish_provenance_meta(monkeypatch):
    cache = DashboardCache()
    monkeypatch.setattr(dashboard_router_module, "dashboard_cache", cache)
    monkeypatch.setattr(dashboard_router_module, "fetch_snapshot", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(
        dashboard_router_module,
        "fetch_market_chart",
        lambda *_args, **_kwargs: [
            {"time": 1_700_000_000, "open": 100, "high": 102, "low": 99, "close": 101, "volume": 10_000}
        ],
    )
    monkeypatch.setattr(dashboard_router_module, "fetch_revenue_trend", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(dashboard_router_module, "fetch_segment_mix", lambda *_args, **_kwargs: [])
    monkeypatch.setattr(dashboard_router_module, "fetch_valuation", lambda *_args, **_kwargs: {"trailing_pe": 20})
    monkeypatch.setattr(
        dashboard_router_module,
        "fetch_financial_statements",
        lambda *_args, **_kwargs: {
            "periods": ["2026Q1"],
            "revenue": [100],
            "gross_profit": [50],
            "operating_income": [30],
            "net_income": [20],
            "eps": [1.2],
            "total_assets": [500],
            "total_liabilities": [200],
            "operating_cash_flow": [40],
            "free_cash_flow": [25],
        },
    )
    monkeypatch.setattr(
        dashboard_router_module,
        "fetch_technical_indicators",
        lambda *_args, **_kwargs: {"close": 101, "support_levels": [99], "resistance_levels": [105]},
    )
    monkeypatch.setattr(
        dashboard_router_module,
        "fetch_peer_comparison",
        lambda *_args, **_kwargs: {"subject_symbol": "AAPL", "peers": []},
    )
    monkeypatch.setattr(
        dashboard_router_module,
        "fetch_earnings_history",
        lambda *_args, **_kwargs: [
            {"quarter": "2026-03-31", "eps_estimate": 1.1, "eps_actual": 1.2, "surprise_pct": 9.1}
        ],
    )
    monkeypatch.setattr(
        dashboard_router_module,
        "fetch_analyst_targets",
        lambda *_args, **_kwargs: {"low": 90, "current": 101, "mean": 110, "median": 108, "high": 125},
    )
    monkeypatch.setattr(
        dashboard_router_module,
        "fetch_recommendations",
        lambda *_args, **_kwargs: {"buy": 5, "hold": 2, "sell": 1, "strong_buy": 3, "strong_sell": 0},
    )
    monkeypatch.setattr(
        dashboard_router_module,
        "fetch_indicator_series",
        lambda *_args, **_kwargs: {
            "dates": ["2026-03-31"],
            "rsi": [55],
            "macd": [0.2],
            "macd_signal": [0.1],
            "macd_histogram": [0.1],
            "bb_upper": [105],
            "bb_middle": [101],
            "bb_lower": [97],
        },
    )
    monkeypatch.setattr(
        dashboard_router_module,
        "fetch_news",
        lambda *_args, **_kwargs: {"market": [], "impact": []},
    )
    monkeypatch.setattr(dashboard_router_module, "fetch_macro_snapshot", lambda *_args, **_kwargs: {})

    response = await dashboard_router_module.get_dashboard(symbol="AAPL", type=None)

    assert response.data.meta is not None
    assert response.data.meta["earnings_history"]["provider"] == "yfinance"
    assert response.data.meta["analyst_targets"]["source_type"] == "analyst_consensus"
    assert response.data.meta["recommendations"]["fallback_used"] is False
    assert response.data.meta["indicator_series"]["provider"] == "market_data"

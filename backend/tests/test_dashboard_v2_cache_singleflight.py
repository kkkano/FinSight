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

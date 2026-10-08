"""供应商到看板的币种、实际财期、计算和缓存状态回归。"""
from __future__ import annotations

import pytest
import pandas as pd

from backend.dashboard import data_service, snapshot
from backend.dashboard.cache import DashboardCache
from backend.services.market_data_gateway import MarketDataGateway, _quote_from_kline_provider
from backend.services.data_contract import DataResult


@pytest.mark.parametrize("status", ["ok", "empty", "missing", "error", "degraded"])
def test_declared_data_status_survives_result_projection(status):
    assert DataResult.from_payload({"status": status, "data": []}).status == status


def table(ends, rows, *, frequency="annual", currency="CNY"):
    return {"columns": ends, "index": list(rows), "data": [dict(zip(ends, values)) for values in rows.values()],
            "frequency": frequency, "currency": currency}


def financial_view(monkeypatch, ends, income, balance=None, *, frequency="annual"):
    gateway = MarketDataGateway(
        providers={}, primary_provider="", financial_providers={"fixture": lambda _symbol: {
            "currency": "CNY", "financials": table(ends, income, frequency=frequency),
            "balance_sheet": table(ends, balance or {}, frequency="instant"),
        }}, financial_primary_provider="fixture", financial_trusted_providers={"fixture"}, financial_cache_ttl_seconds=0,
    )
    monkeypatch.setattr("backend.services.market_data_gateway.get_market_data_gateway", lambda: gateway)
    return data_service.fetch_financial_statements("0700.HK")


def test_annual_currency_period_and_yoy_survive_projection(monkeypatch):
    view = financial_view(monkeypatch, ["2024-12-31", "2025-12-31"], {"Total Revenue": [100, 200], "Net Income": [20, None]})
    assert view["periods"] == ["2025-12-31", "2024-12-31"]
    assert view["period_ends"] == view["periods"]
    assert view["currency"] == "CNY" and view["frequency"] == "annual"
    assert view["revenue"] == [200, 100]
    assert view["yoy"]["revenue"] == [1.0, None]
    assert view["net_margin"] == [None, 20]


def test_irregular_fiscal_year_and_missing_intermediate_quarter(monkeypatch):
    view = financial_view(monkeypatch, ["2026-08-01", "2026-05-02", "2025-08-02"],
                          {"Total Revenue": [200, 180, 100]}, frequency="quarterly")
    assert view["yoy"]["revenue"] == [1.0, None, None]
    assert view["periods"][0] == "2026-08-01"


def test_yfinance_timestamp_row_keys_and_mixed_date_formats_match_the_same_period(monkeypatch):
    end = pd.Timestamp("2025-12-31")
    gateway = MarketDataGateway(
        providers={}, primary_provider="", financial_providers={"fixture": lambda _symbol: {
            "currency": "CNY", "financials": {"columns": [str(end)], "index": ["Total Revenue"],
                "data": [{end: 200}], "frequency": "annual"},
            "balance_sheet": table(["2025-12-31"], {"Total Assets": [500], "Total Liabilities": [200]}, frequency="instant"),
        }}, financial_primary_provider="fixture", financial_trusted_providers={"fixture"}, financial_cache_ttl_seconds=0,
    )
    monkeypatch.setattr("backend.services.market_data_gateway.get_market_data_gateway", lambda: gateway)
    view = data_service.fetch_financial_statements("0700.HK")
    assert view["periods"] == ["2025-12-31"]
    assert view["revenue"] == [200]
    assert view["balance_summary"]["equity"] == 300


def test_balance_calculation_never_mixes_periods(monkeypatch):
    view = financial_view(monkeypatch, ["2025-12-31", "2024-12-31"], {"Total Revenue": [100, 80]},
                          {"Total Assets": [500, None], "Total Liabilities": [None, 200]})
    summary = view["balance_summary"]
    assert summary["period"] == "2025-12-31"
    assert summary["total_assets"] == 500 and summary["total_liabilities"] is None
    assert summary["equity"] is None and summary["de_ratio"] is None


def test_same_period_balance_calculation(monkeypatch):
    view = financial_view(monkeypatch, ["2025-12-31"], {"Total Revenue": [100]},
                          {"Total Assets": [500], "Total Liabilities": [200]})
    assert view["balance_summary"]["equity"] == 300
    assert view["balance_summary"]["de_ratio"] == pytest.approx(2 / 3)


@pytest.mark.asyncio
async def test_cache_roundtrip_preserves_failure_and_source_metadata(monkeypatch):
    cache = DashboardCache()
    monkeypatch.setattr(snapshot, "dashboard_cache", cache)
    calls = 0

    async def fetch(name, *_args, **_kwargs):
        nonlocal calls
        calls += 1
        return {
            "fetch_snapshot": None,
            "fetch_market_chart": [{"time": 1_700_000_000, "close": 100, "currency": "HKD"}],
            "fetch_news": {"market": [], "impact": []},
            "fetch_macro_snapshot": {"status": "unavailable", "as_of": "2026-01-01T00:00:00Z"},
        }.get(name, [])

    monkeypatch.setattr(snapshot, "_run_blocking", fetch)
    first = await snapshot.get_dashboard("0700.HK", type="index")
    call_count = calls
    second = await snapshot.get_dashboard("0700.HK", type="index")
    assert calls == call_count
    for key in ("snapshot", "market_chart", "macro_snapshot"):
        a, b = first.data.meta[key], second.data.meta[key]
        assert {k: v for k, v in a.items() if k != "cached"} == {k: v for k, v in b.items() if k != "cached"}
    assert second.data.meta["snapshot"]["status"] == "error"
    assert second.data.meta["snapshot"]["confidence"] == 0
    assert second.data.meta["snapshot"]["as_of"] == ""
    assert second.data.meta["market_chart"]["currency"] == "HKD"
    assert cache.get_result("0700.HK", "snapshot").status == "error"


def test_daily_quote_cannot_claim_intraday_capability():
    def provider(symbol, period, interval):
        assert (period, interval) == ("1mo", "1d")
        return {"currency": "HKD", "kline_data": [
            {"time": "2026-10-07", "open": 100, "high": 110, "low": 90, "close": 105, "volume": 1000},
        ]}
    gateway = MarketDataGateway(providers={}, primary_provider="", quote_providers={"fixture": _quote_from_kline_provider(provider)},
                                quote_primary_provider="fixture", quote_trusted_providers={"fixture"}, quote_cache_ttl_seconds=0)
    result = gateway.get_quote("0700.HK")
    assert result["data_kind"] == "daily_close"
    assert result["asset"]["calendar_name"] == "HKEX"
    assert result["data"]["currency"] == "HKD"


def test_in_progress_daily_bar_is_not_published_as_a_completed_close():
    from datetime import datetime, timezone
    def provider(_symbol, _period, _interval):
        return {"currency": "USD", "kline_data": [
            {"time": "2026-10-06", "open": 100, "high": 101, "low": 99, "close": 100, "volume": 100},
            {"time": "2026-10-07", "open": 100, "high": 103, "low": 99, "close": 102, "volume": 100},
            {"time": "2026-10-08", "open": 102, "high": 120, "low": 99, "close": 110, "volume": 10},
        ]}
    quote = _quote_from_kline_provider(provider, clock=lambda: datetime(2026, 10, 8, 15, tzinfo=timezone.utc))("AAPL")
    assert quote["data"]["price"] == 102 and quote["data"]["change"] == 2
    assert quote["as_of"] == "2026-10-07" and quote["data"]["market_session"] == "regular_close"


def test_quote_without_source_time_does_not_become_current():
    gateway = MarketDataGateway(providers={}, primary_provider="", quote_providers={"fixture": lambda _: {"price": 100}},
                                quote_primary_provider="fixture", quote_trusted_providers={"fixture"}, quote_cache_ttl_seconds=0)
    result = gateway.get_quote("AAPL")
    assert result["as_of"] is None and result["freshness_seconds"] is None
    assert result["observed_at"] and result["data_kind"] == "unknown"

from datetime import date, datetime, timezone
import json
from types import SimpleNamespace

import pytest
import httpx

from backend.services.prediction_store import PredictionStore
from backend.services.prediction_report_view import track_record_view
from backend.services.prediction_calendar import window_for_date
from backend.tests.test_prediction_pipeline import collect, bars_for


@pytest.mark.asyncio
async def test_track_record_time_range_summary_is_not_current_page_and_hides_private_fields(tmp_path):
    store = PredictionStore(tmp_path / "ledger.db")
    for day in (date(2026, 10, 2), date(2026, 10, 30)):
        window = window_for_date(day)
        await collect(store, window, tickers=("AAPL", "NVDA"))
    for row in store._rows():
        if not row.get("payload"):
            continue
        window = window_for_date(date.fromisoformat(row["batch_date"]))
        store.settle(row["id"], {"hit": True, "baseline_hit": False, "settled_at": window.window_end},
                     [{**bar, "secret": "private-market-field"} for bar in bars_for(window)])
    result = track_record_view(store, limit=1, days=28, now=datetime(2026, 11, 7, tzinfo=timezone.utc))
    assert len(result["records"]) == 1
    assert result["summary"]["predictions"] == 4
    assert sum(group["n"] for group in result["groups"]) == 4
    assert result["daily_series"][-1]["n"] == 2
    assert result["metadata"]["frequency"] == "trading_day"
    assert result["metadata"]["prediction_types_per_symbol"] == 2
    assert result["metadata"]["collection_start_et"] == "08:45"
    assert result["metadata"]["horizon_sessions"] == 5
    assert "must-not-be-public" not in json.dumps(result)
    assert "private-endpoint" not in json.dumps(result)
    assert "private-market-field" not in json.dumps(result)


@pytest.mark.asyncio
async def test_company_dividend_yield_uses_unambiguous_ratio(monkeypatch):
    from backend.services.company_profile import _fetch
    monkeypatch.setattr("backend.tools.yfinance_client.create_ticker", lambda ticker: SimpleNamespace(get_info=lambda: {
        "longName": "Apple Inc.", "fullExchangeName": "NasdaqGS", "regularMarketPrice": 100,
        "trailingAnnualDividendRate": 1, "dividendYield": 9.9, "regularMarketTime": 1793998800,
        "currency": "USD", "marketCap": 123000, "trailingPE": 20,
    }))
    result = _fetch("AAPL")
    assert result["exchange"] == "NasdaqGS"
    assert result["dividend_yield"] == .01
    assert result["name_zh"] is None


@pytest.mark.asyncio
async def test_auth_provider_route_uses_actual_enabled_settings_and_exposes_no_key(monkeypatch):
    import backend.api.auth_provider_router as module
    module._cache = None
    monkeypatch.setattr(module, "security_settings", lambda: SimpleNamespace(supabase_url="https://project.example", vite_supabase_url="",
        supabase_publishable_key="private-config-key", vite_supabase_publishable_key=""))
    real_client = httpx.AsyncClient
    def handler(request):
        assert request.headers["apikey"] == "private-config-key"
        return httpx.Response(200, json={"external": {"github": True, "email": True}, "unrelated_private": "secret"})
    monkeypatch.setattr(module.httpx, "AsyncClient", lambda **kwargs: real_client(transport=httpx.MockTransport(handler), **kwargs))
    result = await module.auth_providers()
    assert result == {"github": True, "email": True, "status": "ok"}
    assert "private" not in json.dumps(result)
    module._cache = None

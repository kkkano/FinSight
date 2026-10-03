from datetime import date, timedelta

import httpx
import pytest
from fastapi import FastAPI

from backend.services.prediction_calendar import iso, timestamp, window_for_date
from backend.services.prediction_runner import collect_batch
from backend.services.prediction_settlement import settle_due
from backend.services.prediction_store import PredictionStore


async def sample_store(tmp_path):
    store = PredictionStore(tmp_path / "ledger.db")
    first = window_for_date(date(2026, 10, 2))
    second = window_for_date(date(2026, 10, 5))
    for window in (first, second):
        async def forecast(agent, context, data):
            if context["ticker"] == "MSFT" and agent == "risk" and window == first:
                return {"status": "failed", "retryable": False, "error_code": "fixture_failure"}
            return {"status": "predicted", "prediction_type": "direction" if agent == "technical" else "drawdown",
                    "direction": "down" if agent == "technical" else None,
                    "event_occurs": agent == "risk", "issued_at": iso(timestamp(window.collection_at)),
                    "prompt_version": "fixture-v1", "reason": "测试样本，非真实战绩", "evidence_refs": [],
                    "metadata": {"actual_model": "fixture-model", "model_confirmed": True,
                                 "api_key": "private-fixture", "endpoint_url": "https://private.example"}}
        await collect_batch(store, window=window, clock=lambda: timestamp(window.collection_at),
                            tickers=("AAPL", "MSFT"), snapshot_loader=lambda *args: {"bars": []}, forecast=forecast)
    settle_due(store, now=timestamp(first.window_end) + timedelta(minutes=25), loader=lambda *args: [
        {"time": day, "open": 100, "close": close, "high": 101, "low": 90, "volume": 1}
        for day, close in zip(first.sessions, (100, 98, 94, 96, 97))
    ])
    return store


@pytest.mark.asyncio
async def test_filters_page_matching_records_without_changing_global_stats(tmp_path):
    store = await sample_store(tmp_path)
    all_history = store.public_report()
    first = store.public_report(ticker="AAPL", status="pending", limit=1)
    second = store.public_report(ticker="AAPL", status="pending", limit=1, offset=1)
    assert first["summary"] == second["summary"] == all_history["summary"]
    assert first["groups"] == second["groups"] == all_history["groups"]
    assert all_history["summary"]["opportunities"] == 8
    assert first["pagination"] == {"limit": 1, "offset": 0, "total": 2, "has_more": True}
    assert second["pagination"] == {"limit": 1, "offset": 1, "total": 2, "has_more": False}
    assert first["records"][0]["id"] != second["records"][0]["id"]
    for page in (first, second):
        assert page["records"][0]["ticker"] == "AAPL"
        assert page["records"][0]["status"] == "pending"
    failures = store.public_report(ticker="MSFT", status="failed", prediction_type="drawdown")
    assert failures["pagination"]["total"] == 1
    assert failures["records"][0]["error_code"] == "fixture_failure"
    empty = store.public_report(ticker="AAOI")
    assert empty["records"] == [] and empty["pagination"]["total"] == 0
    assert empty["summary"] == all_history["summary"]


@pytest.mark.asyncio
async def test_public_filter_api_normalizes_ticker_and_rejects_invalid_filters(tmp_path, monkeypatch):
    import backend.api.prediction_router as module
    store = await sample_store(tmp_path)
    monkeypatch.setattr(module, "get_prediction_store", lambda: store)
    monkeypatch.setattr(module, "enabled", lambda: False)
    app = FastAPI()
    app.include_router(module.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/benchmarks/us20-v1/track-record?ticker=aapl&status=settled&prediction_type=direction")
        assert response.status_code == 200
        data = response.json()
        assert data["enabled"] is False
        assert data["pagination"]["total"] == len(data["records"]) == 1
        assert data["records"][0]["ticker"] == "AAPL"
        assert data["summary"]["opportunities"] == 8
        for private in ("private-fixture", "private.example", "api_key", "endpoint_url"):
            assert private not in response.text
        for suffix in ("status=not-real", "prediction_type=price", "ticker=%27%3BDROP", "offset=-1"):
            assert (await client.get("/api/benchmarks/us20-v1/track-record?" + suffix)).status_code == 422

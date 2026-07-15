# -*- coding: utf-8 -*-
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api import backtest_router as backtest_router_module


def _build_client(*, user_id: str = "alice") -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user_id = user_id
        return await call_next(request)

    app.include_router(backtest_router_module.backtest_router)
    return TestClient(app)


def test_backtest_router_list_strategies(monkeypatch):
    class _FakeEngine:
        @staticmethod
        def list_strategies():
            return [{"id": "ma_cross"}]

    monkeypatch.setattr(backtest_router_module, "BacktestEngine", _FakeEngine)
    client = _build_client()

    response = client.get("/api/backtest/strategies")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["strategies"][0]["id"] == "ma_cross"


def test_backtest_router_run(monkeypatch):
    class _FakeEngine:
        @staticmethod
        def list_strategies():
            return []

        def run(self, **kwargs):
            return {
                "success": True,
                "ticker": kwargs["ticker"],
                "strategy": kwargs["strategy"],
                "metrics": {"total_return_pct": 12.3},
            }

    monkeypatch.setattr(backtest_router_module, "BacktestEngine", _FakeEngine)
    client = _build_client()

    response = client.post(
        "/api/backtest/run",
        json={
            "ticker": "AAPL",
            "strategy": "ma_cross",
            "params": {},
            "initial_cash": 100000,
            "t_plus_one": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["ticker"] == "AAPL"
    assert payload["metrics"]["total_return_pct"] == 12.3


def test_backtest_router_prefill_from_report(monkeypatch):
    class _Store:
        def get_report_by_id(self, *, report_id, user_id):
            assert report_id == "rpt-1"
            assert user_id == "alice"
            return {
                "report_id": report_id,
                "title": "Apple research",
                "ticker": "AAPL",
                "generated_at": "2026-07-11T08:30:00Z",
                "recommendation": "BUY",
            }

    monkeypatch.setattr(backtest_router_module, "get_report_index_store", lambda: _Store())
    response = _build_client().post("/api/backtest/prefill-from-report", json={"report_id": "rpt-1"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["strategy"] == "buy_and_hold"
    assert payload["config"]["tickers"] == ["AAPL"]


def test_backtest_router_prefill_handles_missing_report(monkeypatch):
    class _Store:
        def get_report_by_id(self, *, report_id, user_id):
            assert user_id == "alice"
            return None

    monkeypatch.setattr(backtest_router_module, "get_report_index_store", lambda: _Store())
    response = _build_client().post("/api/backtest/prefill-from-report", json={"report_id": "missing"})
    assert response.status_code == 404

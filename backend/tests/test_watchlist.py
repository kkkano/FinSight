# -*- coding: utf-8 -*-
"""WP6-F2 自选股存储与 API 契约。"""
from __future__ import annotations

import json
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from backend.api.morning_brief_router import MorningBriefRouterDeps, create_morning_brief_router
from backend.api.watchlist_router import WatchlistRouterDeps, create_watchlist_router
from backend.services import monitor_engine
from backend.services.watchlist_store import LegacyWatchlistStore as WatchlistStore


def _client(store: WatchlistStore) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def fake_identity(request: Request, call_next):
        request.state.user_id = request.headers.get("x-test-user", "public")
        return await call_next(request)

    app.include_router(create_watchlist_router(WatchlistRouterDeps(get_store=lambda: store)))
    return TestClient(app)


def test_watchlist_add_remove_and_idempotency(tmp_path):
    store = WatchlistStore(tmp_path / "watchlist.db")
    client = _client(store)

    created = client.post("/api/watchlist", json={"ticker": "aapl", "note": "核心观察"})
    assert created.status_code == 201
    assert created.json()["item"]["ticker"] == "AAPL"

    duplicate = client.post("/api/watchlist", json={"ticker": "AAPL", "note": "不覆盖"})
    assert duplicate.status_code == 200
    assert duplicate.json()["item"]["note"] == "核心观察"
    assert client.get("/api/watchlist").json()["items"][0]["ticker"] == "AAPL"

    removed = client.delete("/api/watchlist/aapl")
    assert removed.status_code == 204
    assert removed.content == b""
    assert client.get("/api/watchlist").json() == {"items": []}


def test_watchlist_is_isolated_by_authenticated_user(tmp_path):
    store = WatchlistStore(tmp_path / "watchlist.db")
    client = _client(store)

    assert client.post(
        "/api/watchlist",
        headers={"x-test-user": "alice"},
        json={"ticker": "NVDA"},
    ).status_code == 201
    assert client.post(
        "/api/watchlist",
        headers={"x-test-user": "bob"},
        json={"ticker": "MSFT"},
    ).status_code == 201

    alice = client.get("/api/watchlist", headers={"x-test-user": "alice"}).json()
    bob = client.get("/api/watchlist", headers={"x-test-user": "bob"}).json()
    public = client.get("/api/watchlist").json()

    assert [item["ticker"] for item in alice["items"]] == ["NVDA"]
    assert [item["ticker"] for item in bob["items"]] == ["MSFT"]
    assert public == {"items": []}


def test_morning_brief_prefers_watchlist_over_positions():
    fetched: list[str] = []
    app = FastAPI()

    @app.middleware("http")
    async def fake_identity(request: Request, call_next):
        request.state.user_id = "alice"
        return await call_next(request)

    app.include_router(
        create_morning_brief_router(
            MorningBriefRouterDeps(
                resolve_thread_id=lambda value: value or "session",
                get_portfolio_positions=lambda _session, _user: [{"ticker": "TSLA"}],
                get_stock_price=lambda ticker: fetched.append(ticker) or f"{ticker} Current Price: $10.00",
                get_company_news=lambda _ticker, _limit: [],
                get_watchlist=lambda user_id: [{"ticker": "NVDA"}] if user_id == "alice" else [],
            )
        )
    )

    response = TestClient(app).post(
        "/api/morning-brief/generate",
        json={"session_id": "session", "tickers": []},
    )

    assert response.status_code == 200
    assert fetched == ["NVDA"]
    assert response.json()["brief"]["ticker_count"] == 1


@pytest.mark.asyncio
async def test_monitor_uses_watchlist_as_default_targets(monkeypatch):
    captured: dict[str, dict] = {}

    class FakeStore:
        def list_targets(self, _session_id, user_id="public"):
            return []

    async def capture_sentiment(_session, _store, _positions, config_map, user_id="public"):
        captured.update(config_map)
        return []

    async def no_findings(*_args, **_kwargs):
        return []

    monkeypatch.setattr(monitor_engine, "get_monitor_store", lambda: FakeStore())
    monkeypatch.setattr(monitor_engine, "_get_positions_for_user", lambda *_args: [])
    monkeypatch.setattr(monitor_engine, "list_watchlist", lambda user_id="public": [{"ticker": "AAPL"}])
    monkeypatch.setattr(monitor_engine, "price_rules_active", lambda _session: False)
    monkeypatch.setattr(monitor_engine, "_scan_concentration", no_findings)
    monkeypatch.setattr(monitor_engine, "_scan_sentiment_shift", capture_sentiment)
    monkeypatch.setattr(monitor_engine, "_scan_earnings_near", no_findings)
    monkeypatch.setattr(monitor_engine, "_scan_macro_event", no_findings)

    result = await monitor_engine.run_l1_scan(
        "session",
        enable_l2=False,
        market_session="closed",
        user_id="alice",
    )

    assert result == []
    assert "AAPL" in captured


def test_watchlist_migrates_legacy_memory_profiles(tmp_path):
    memory_dir = tmp_path / "memory"
    memory_dir.mkdir()
    (memory_dir / "alice.json").write_text(
        json.dumps({"user_id": "alice", "watchlist": ["aapl", "NVDA"]}),
        encoding="utf-8",
    )
    store = WatchlistStore(tmp_path / "watchlist.db")

    assert store.migrate_legacy_profiles(memory_dir) == 2
    assert store.migrate_legacy_profiles(memory_dir) == 0
    assert [item["ticker"] for item in store.list_items("alice")] == ["AAPL", "NVDA"]

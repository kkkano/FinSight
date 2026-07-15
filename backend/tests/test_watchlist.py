# -*- coding: utf-8 -*-
"""WP6-F2 自选股存储与 API 契约。"""
from __future__ import annotations

import json
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.morning_brief_router import MorningBriefRouterDeps, create_morning_brief_router
from backend.api.watchlist_router import WatchlistRouterDeps, create_watchlist_router
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

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.watchlist_router import WatchlistRouterDeps, create_watchlist_router
from backend.services.watchlist_store import WatchlistStore


class _MemoryStore:
    def __init__(self) -> None:
        self.items: dict[tuple[str, str], dict] = {}

    def list_items(self, user_id: str = "public") -> list[dict]:
        return [dict(item) for (owner, _), item in self.items.items() if owner == user_id]

    def add_item(self, ticker: str, note: str = "", user_id: str = "public"):
        normalized = ticker.strip().upper()
        if not normalized:
            raise ValueError("ticker is required")
        key = (user_id, normalized)
        created = key not in self.items
        self.items.setdefault(key, {
            "ticker": normalized,
            "note": note.strip(),
            "added_at": "2026-07-15T00:00:00+00:00",
        })
        return dict(self.items[key]), created

    def remove_item(self, ticker: str, user_id: str = "public") -> bool:
        return self.items.pop((user_id, ticker.strip().upper()), None) is not None


def _client(store: _MemoryStore) -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user_id = request.headers.get("x-test-user", "public")
        return await call_next(request)

    app.include_router(create_watchlist_router(WatchlistRouterDeps(get_store=lambda: store)))
    return TestClient(app)


def test_watchlist_router_add_list_remove_and_tenant_isolation():
    client = _client(_MemoryStore())
    alice = {"x-test-user": "alice"}
    bob = {"x-test-user": "bob"}

    assert client.post("/api/watchlist", headers=alice, json={"ticker": "aapl", "note": "core"}).status_code == 201
    duplicate = client.post("/api/watchlist", headers=alice, json={"ticker": "AAPL", "note": "ignored"})
    assert duplicate.status_code == 200
    assert duplicate.json()["item"]["note"] == "core"
    assert client.post("/api/watchlist", headers=bob, json={"ticker": "MSFT"}).status_code == 201

    assert [item["ticker"] for item in client.get("/api/watchlist", headers=alice).json()["items"]] == ["AAPL"]
    assert [item["ticker"] for item in client.get("/api/watchlist", headers=bob).json()["items"]] == ["MSFT"]
    assert client.delete("/api/watchlist/AAPL", headers=alice).status_code == 204
    assert client.get("/api/watchlist", headers=alice).json() == {"items": []}


class _Result:
    def __init__(self, *, rows=None, row=None, rowcount=0):
        self.rows = list(rows or [])
        self.row = row
        self.rowcount = rowcount

    def mappings(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.row

    def one(self):
        if self.row is None:
            raise AssertionError("expected one row")
        return self.row


class _Connection:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return self.results.pop(0)


class _Engine:
    def __init__(self, *results):
        self.connection = _Connection(results)

    @contextmanager
    def connect(self):
        yield self.connection

    @contextmanager
    def begin(self):
        yield self.connection


def test_postgres_watchlist_queries_are_tenant_scoped_and_run_no_schema_ddl():
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    engine = _Engine(
        _Result(rows=[{"ticker": "AAPL", "note": "core", "added_at": now}]),
        _Result(row={"ticker": "MSFT", "note": "", "added_at": now}),
        _Result(rowcount=1),
    )
    store = WatchlistStore(engine=engine)
    assert engine.connection.calls == []

    assert store.list_items("alice")[0]["ticker"] == "AAPL"
    item, created = store.add_item("msft", user_id="alice")
    assert created is True and item["ticker"] == "MSFT"
    assert store.remove_item("AAPL", user_id="alice") is True

    for sql, params in engine.connection.calls:
        assert "user_id" in sql
        assert params["user_id"] == "alice"
        assert "CREATE TABLE" not in sql.upper()

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api import portfolio_router as portfolio_router_module
from backend.services import portfolio_store


def test_ensure_column_is_idempotent() -> None:
    from backend.data.migrations import ensure_column

    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE sample (id TEXT PRIMARY KEY)")

    ensure_column(conn, "sample", "user_id", "user_id TEXT NOT NULL DEFAULT 'public'")
    ensure_column(conn, "sample", "user_id", "user_id TEXT NOT NULL DEFAULT 'public'")

    columns = [row[1] for row in conn.execute("PRAGMA table_info(sample)")]
    assert columns.count("user_id") == 1


def test_portfolio_isolated_between_users(
    tmp_path: Path,
    monkeypatch,
) -> None:
    if portfolio_store._conn is not None:
        portfolio_store._conn.close()
    monkeypatch.setattr(portfolio_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(portfolio_store, "_DB_PATH", tmp_path / "portfolio.db")
    monkeypatch.setattr(portfolio_store, "_conn", None)

    portfolio_store.update_position("shared", "AAPL", 10, user_id="alice")
    portfolio_store.update_position("shared", "TSLA", 5, user_id="bob")
    portfolio_store.update_position("shared", "AAPL", 2, user_id="bob")

    assert [row["ticker"] for row in portfolio_store.get_positions("shared", user_id="alice")] == ["AAPL"]
    assert [row["ticker"] for row in portfolio_store.get_positions("shared", user_id="bob")] == ["AAPL", "TSLA"]
    assert portfolio_store.get_positions("shared") == []

    portfolio_store.remove_position("shared", "AAPL", user_id="alice")
    assert portfolio_store.get_positions("shared", user_id="alice") == []
    assert [row["ticker"] for row in portfolio_store.get_positions("shared", user_id="bob")] == ["AAPL", "TSLA"]


def test_portfolio_router_forwards_request_user_to_store(
    tmp_path: Path,
    monkeypatch,
) -> None:
    if portfolio_store._conn is not None:
        portfolio_store._conn.close()
    monkeypatch.setattr(portfolio_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(portfolio_store, "_DB_PATH", tmp_path / "router-portfolio.db")
    monkeypatch.setattr(portfolio_store, "_conn", None)
    monkeypatch.setattr(
        portfolio_router_module,
        "resolve_live_quote",
        lambda _ticker, _fetcher: (None, None),
    )

    app = FastAPI()

    @app.middleware("http")
    async def inject_user(request: Request, call_next):
        request.state.user_id = request.headers.get("x-user-id", "public")
        return await call_next(request)

    app.include_router(portfolio_router_module.portfolio_router)
    with TestClient(app) as client:
        for user_id, ticker in (
            ("alice", "AAPL"),
            ("bob", "TSLA"),
        ):
            headers = {"x-user-id": user_id}
            assert client.post(
                "/api/portfolio/positions",
                headers=headers,
                json={
                    "session_id": "shared",
                    "positions": [{"ticker": ticker, "shares": 1}],
                },
            ).status_code == 200
        alice_headers = {"x-user-id": "alice"}
        assert [
            row["ticker"]
            for row in client.get(
                "/api/portfolio/summary?session_id=shared",
                headers=alice_headers,
            ).json()["positions"]
        ] == ["AAPL"]


def test_legacy_portfolio_rows_migrate_to_public_without_overwrite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    db_path = tmp_path / "legacy-portfolio.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE portfolio_positions (
            session_id TEXT NOT NULL, ticker TEXT NOT NULL, shares REAL NOT NULL,
            avg_cost REAL, updated_at TEXT NOT NULL,
            PRIMARY KEY (session_id, ticker)
        )"""
    )
    conn.execute(
        "INSERT INTO portfolio_positions VALUES ('shared', 'AAPL', 10, 100, 'legacy')"
    )
    conn.commit()
    conn.close()

    if portfolio_store._conn is not None:
        portfolio_store._conn.close()
    monkeypatch.setattr(portfolio_store, "_DB_DIR", tmp_path)
    monkeypatch.setattr(portfolio_store, "_DB_PATH", db_path)
    monkeypatch.setattr(portfolio_store, "_conn", None)

    assert portfolio_store.get_positions("shared")[0]["shares"] == 10
    portfolio_store.update_position("shared", "AAPL", 2, user_id="alice")
    assert portfolio_store.get_positions("shared")[0]["shares"] == 10
    assert portfolio_store.get_positions("shared", user_id="alice")[0]["shares"] == 2

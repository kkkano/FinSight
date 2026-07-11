from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api import portfolio_router as portfolio_router_module
from backend.api.conversation_router import ConversationRouterDeps, create_conversation_router
from backend.api.monitor_router import monitor_router
from backend.services import portfolio_store
from backend.services import monitor_store as monitor_store_module
from backend.services.conversation_store import ConversationStore
from backend.services.monitor_store import MonitorStore


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


def test_conversations_isolated_between_users(tmp_path: Path) -> None:
    store = ConversationStore(path=tmp_path / "conversations.json")
    store.upsert("shared", {"title": "Alice"}, user_id="alice")
    store.upsert("shared", {"title": "Bob"}, user_id="bob")

    assert store.get("shared", user_id="alice")["title"] == "Alice"
    assert store.get("shared", user_id="bob")["title"] == "Bob"
    assert store.get("shared") is None
    assert [row["title"] for row in store.list(user_id="alice")] == ["Alice"]

    assert store.delete("shared", user_id="alice") is True
    assert store.get("shared", user_id="alice") is None
    assert store.get("shared", user_id="bob")["title"] == "Bob"


def _finding(finding_id: str, title: str) -> dict[str, object]:
    return {
        "id": finding_id,
        "session_id": "shared",
        "target": "AAPL",
        "trigger_type": "price_move",
        "title": title,
    }


def test_monitor_data_isolated_between_users(tmp_path: Path) -> None:
    store = MonitorStore(db_path=str(tmp_path / "monitor.db"))
    store.insert_finding(_finding("alice-finding", "Alice"), user_id="alice")
    store.insert_finding(_finding("bob-finding", "Bob"), user_id="bob")

    assert [row["title"] for row in store.list_findings("shared", user_id="alice")] == ["Alice"]
    assert [row["title"] for row in store.list_findings("shared", user_id="bob")] == ["Bob"]
    assert store.list_findings("shared") == []
    assert store.update_finding_status("shared", "bob-finding", "viewed", user_id="alice") is False

    store.upsert_target(
        {"id": "alice-target", "session_id": "shared", "ticker": "AAPL"},
        user_id="alice",
    )
    store.upsert_target(
        {"id": "bob-target", "session_id": "shared", "ticker": "TSLA"},
        user_id="bob",
    )
    assert [row["ticker"] for row in store.list_targets("shared", user_id="alice")] == ["AAPL"]
    assert store.delete_target("shared", "bob-target", user_id="alice") is False

    store.upsert_settings("shared", "alice@example.com", True, user_id="alice")
    store.upsert_settings("shared", "bob@example.com", False, user_id="bob")
    assert store.get_settings("shared", user_id="alice")["notify_email"] == "alice@example.com"
    assert store.get_settings("shared", user_id="bob")["notify_email"] == "bob@example.com"


def test_routers_forward_request_user_to_all_three_stores(
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

    monitor_store = MonitorStore(db_path=str(tmp_path / "router-monitor.db"))
    monkeypatch.setattr(monitor_store_module, "_STORE", monitor_store)
    conversation_store = ConversationStore(path=tmp_path / "router-conversations.json")

    app = FastAPI()

    @app.middleware("http")
    async def inject_user(request: Request, call_next):
        request.state.user_id = request.headers.get("x-user-id", "public")
        return await call_next(request)

    app.include_router(portfolio_router_module.portfolio_router)
    app.include_router(monitor_router)
    app.include_router(
        create_conversation_router(
            ConversationRouterDeps(
                resolve_thread_id=lambda session_id: session_id or "generated",
                get_session_context=lambda _session_id: object(),
                list_session_contexts=lambda: [],
                clear_session_context=lambda _session_id: {},
                list_conversation_records=lambda user_id: conversation_store.list(user_id=user_id),
                get_conversation_record=lambda session_id, user_id: conversation_store.get(session_id, user_id=user_id),
                upsert_conversation_record=lambda session_id, payload, user_id: conversation_store.upsert(session_id, payload, user_id=user_id),
                patch_conversation_record=lambda session_id, payload, user_id: conversation_store.patch(session_id, payload, user_id=user_id),
                delete_conversation_record=lambda session_id, user_id: conversation_store.delete(session_id, user_id=user_id),
            )
        )
    )

    with TestClient(app) as client:
        for user_id, ticker, title in (
            ("alice", "AAPL", "Alice chat"),
            ("bob", "TSLA", "Bob chat"),
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
            assert client.post(
                "/api/monitor/targets",
                headers=headers,
                json={"session_id": "shared", "ticker": ticker},
            ).status_code == 200
            assert client.post(
                "/api/conversations",
                headers=headers,
                json={"session_id": "shared", "title": title},
            ).status_code == 200

        alice_headers = {"x-user-id": "alice"}
        assert [
            row["ticker"]
            for row in client.get(
                "/api/portfolio/summary?session_id=shared",
                headers=alice_headers,
            ).json()["positions"]
        ] == ["AAPL"]
        assert [
            row["ticker"]
            for row in client.get(
                "/api/monitor/targets?session_id=shared",
                headers=alice_headers,
            ).json()["targets"]
        ] == ["AAPL"]
        assert client.get(
            "/api/conversations/shared",
            headers=alice_headers,
        ).json()["conversation"]["title"] == "Alice chat"


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


def test_legacy_monitor_and_conversation_data_belong_to_public(tmp_path: Path) -> None:
    monitor_path = tmp_path / "legacy-monitor.db"
    conn = sqlite3.connect(monitor_path)
    conn.execute(
        """CREATE TABLE monitor_settings (
            session_id TEXT PRIMARY KEY, notify_email TEXT,
            notify_enabled INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL
        )"""
    )
    conn.execute(
        "INSERT INTO monitor_settings VALUES ('shared', 'legacy@example.com', 1, 'legacy')"
    )
    conn.commit()
    conn.close()

    monitor = MonitorStore(db_path=str(monitor_path))
    assert monitor.get_settings("shared")["notify_email"] == "legacy@example.com"
    monitor.upsert_settings("shared", "alice@example.com", True, user_id="alice")
    assert monitor.get_settings("shared")["notify_email"] == "legacy@example.com"
    assert monitor.get_settings("shared", user_id="alice")["notify_email"] == "alice@example.com"

    conversation_path = tmp_path / "legacy-conversations.json"
    conversation_path.write_text(
        json.dumps(
            {
                "conversations": {
                    "shared": {"session_id": "shared", "title": "Legacy", "updated_at": 1}
                }
            }
        ),
        encoding="utf-8",
    )
    conversations = ConversationStore(path=conversation_path)
    assert conversations.get("shared")["title"] == "Legacy"
    assert conversations.get("shared", user_id="alice") is None

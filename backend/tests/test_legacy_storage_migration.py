# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.report_router import ReportRouterDeps, create_report_router
from backend.services.report_index import ReportIndexStore, ReportIndexStoreUnavailable
from scripts.migrate_legacy_storage import (
    LegacyMigrationError,
    build_snapshot,
    read_snapshot,
    rollback_batch,
    write_snapshot,
)


def _legacy_sources(tmp_path, *, user_id: str = "public"):
    conversation_path = tmp_path / "conversations.json"
    conversation_path.write_text(
        json.dumps(
            {
                "conversations": {
                    "thread-1": {
                        "user_id": user_id,
                        "session_id": "web:alice:thread-1",
                        "title": "旧会话",
                        "messages": [{"role": "user", "content": "分析 AAPL"}],
                        "created_at": 1_752_206_400,
                        "updated_at": 1_752_206_460,
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    watchlist_path = tmp_path / "watchlist.db"
    with sqlite3.connect(watchlist_path) as conn:
        conn.execute(
            "CREATE TABLE watchlist (user_id TEXT,ticker TEXT,note TEXT,added_at TEXT)"
        )
        conn.execute(
            "INSERT INTO watchlist VALUES (?,?,?,?)",
            (user_id, "aapl", "核心仓", "2025-07-11T00:00:00Z"),
        )

    report_path = tmp_path / "report_index.sqlite"
    with sqlite3.connect(report_path) as conn:
        conn.execute(
            "CREATE TABLE report_index ("
            "report_id TEXT,session_id TEXT,ticker TEXT,title TEXT,summary TEXT,tags_json TEXT,"
            "generated_at TEXT,confidence_score REAL,is_favorite INTEGER,trace_digest_json TEXT,"
            "report_json TEXT,quality_state TEXT,publishable INTEGER,quality_reasons_json TEXT,"
            "source_type TEXT,filing_type TEXT,publisher TEXT,share_token TEXT,shared_at TEXT,"
            "created_at TEXT,updated_at TEXT)"
        )
        report = {
            "report_id": "rpt-1",
            "ticker": "AAPL",
            "title": "AAPL 报告",
            "citations": [],
        }
        conn.execute(
            "INSERT INTO report_index VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "rpt-1",
                "web:alice:thread-1",
                "AAPL",
                "AAPL 报告",
                "摘要",
                '["us-tech"]',
                "2025-07-11T00:00:00Z",
                0.8,
                0,
                "{}",
                json.dumps(report, ensure_ascii=False),
                "pass",
                1,
                "[]",
                "ai_generated",
                None,
                None,
                None,
                None,
                "2025-07-11T00:00:00Z",
                "2025-07-11T00:00:00Z",
            ),
        )
        conn.execute(
            "CREATE TABLE citation_index (report_id TEXT,session_id TEXT,source_id TEXT,title TEXT,"
            "url TEXT,snippet TEXT,published_date TEXT,confidence REAL,citation_json TEXT,created_at TEXT)"
        )
        conn.execute(
            "INSERT INTO citation_index VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "rpt-1",
                "web:alice:thread-1",
                None,
                "来源",
                "https://example.com/aapl",
                "证据",
                "2025-07-10",
                0.9,
                '{"title":"来源","url":"https://example.com/aapl"}',
                "2025-07-11T00:00:00Z",
            ),
        )
    return conversation_path, watchlist_path, report_path


def test_export_is_deterministic_and_assigns_authenticated_owner(tmp_path):
    conversation_path, watchlist_path, report_path = _legacy_sources(tmp_path)
    snapshot = build_snapshot(
        conversation_path=conversation_path,
        watchlist_path=watchlist_path,
        report_path=report_path,
        public_user_id="alice",
    )
    repeated = build_snapshot(
        conversation_path=conversation_path,
        watchlist_path=watchlist_path,
        report_path=report_path,
        public_user_id="alice",
    )

    assert snapshot["counts"] == {
        "conversation_threads": 1,
        "watchlist_items": 1,
        "reports": 1,
        "report_citations": 1,
    }
    assert snapshot["source_digest"] == repeated["source_digest"]
    assert not [item for item in snapshot["issues"] if item["severity"] == "blocker"]
    assert snapshot["rows"]["watchlist_items"][0]["ticker"] == "AAPL"
    assert snapshot["rows"]["reports"][0]["user_id"] == "alice"
    assert snapshot["rows"]["reports"][0]["session_id"] == "web:alice:thread-1"
    assert snapshot["rows"]["report_citations"][0]["source_id"].startswith("legacy-")

    output = tmp_path / "legacy-export.json"
    write_snapshot(snapshot, output)
    assert read_snapshot(output)["source_digest"] == snapshot["source_digest"]


def test_unowned_public_rows_block_export_and_tampering_is_detected(tmp_path):
    conversation_path, watchlist_path, report_path = _legacy_sources(tmp_path)
    snapshot = build_snapshot(
        conversation_path=conversation_path,
        watchlist_path=watchlist_path,
        report_path=report_path,
    )
    assert any(item["severity"] == "blocker" for item in snapshot["issues"])
    with pytest.raises(LegacyMigrationError, match="blocker"):
        write_snapshot(snapshot, tmp_path / "blocked.json")

    output = tmp_path / "allowed.json"
    write_snapshot(snapshot, output, allow_skips=True)
    payload = json.loads(output.read_text(encoding="utf-8"))
    payload["rows"]["reports"][0]["title"] = "篡改"
    output.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(LegacyMigrationError, match="摘要不匹配"):
        read_snapshot(output, allow_skips=True)


class _Result:
    def __init__(self, value=None):
        self.value = value

    def scalar(self):
        return self.value


class _Connection:
    def __init__(self):
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _Result({"report_id": "rpt-1"})


class _Engine:
    def __init__(self):
        self.connection = _Connection()

    @contextmanager
    def connect(self):
        yield self.connection


def test_report_id_lookup_always_requires_and_filters_authenticated_owner():
    engine = _Engine()
    store = ReportIndexStore(engine=engine)
    with pytest.raises(ReportIndexStoreUnavailable, match="authenticated user"):
        store.get_report_by_id(report_id="rpt-1")
    assert engine.connection.calls == []

    assert store.get_report_by_id(report_id="rpt-1", user_id="alice") == {"report_id": "rpt-1"}
    sql, params = engine.connection.calls[-1]
    assert "report_id=:report_id AND user_id=:user_id" in sql
    assert params == {"report_id": "rpt-1", "user_id": "alice"}


class _UpsertResult:
    def __init__(self, owner):
        self.owner = owner

    def scalar_one_or_none(self):
        return self.owner


class _UpsertConnection:
    def __init__(self, owner):
        self.owner = owner
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _UpsertResult(self.owner)


class _UpsertEngine:
    def __init__(self, owner):
        self.connection = _UpsertConnection(owner)

    @contextmanager
    def begin(self):
        yield self.connection


def test_report_upsert_rejects_cross_tenant_report_id_conflict_before_citation_write():
    engine = _UpsertEngine(owner=None)
    store = ReportIndexStore(engine=engine)

    with pytest.raises(ReportIndexStoreUnavailable, match="another authenticated user"):
        store.upsert_report(
            session_id="web:alice:thread-1",
            user_id="alice",
            report={"report_id": "rpt-owned-by-bob", "title": "conflict"},
        )

    assert len(engine.connection.calls) == 1
    sql, params = engine.connection.calls[0]
    assert "WHERE reports.user_id=excluded.user_id RETURNING user_id" in sql
    assert "SET user_id=excluded.user_id" not in sql
    assert params["user_id"] == "alice"


class _RollbackResult:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class _RollbackConnection:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _RollbackResult(self.row)


class _RollbackEngine:
    def __init__(self, row):
        self.connection = _RollbackConnection(row)

    @contextmanager
    def begin(self):
        yield self.connection


def test_repeated_rollback_is_idempotent_and_performs_no_delete(monkeypatch):
    monkeypatch.setattr(
        "scripts.migrate_legacy_storage.assert_core_schema_current",
        lambda **_kwargs: None,
    )
    batch_id = "c196c191-171a-4432-ae53-73730813d780"
    deleted = {
        "report_citations": 1,
        "reports": 1,
        "watchlist_items": 1,
        "conversation_threads": 1,
    }
    engine = _RollbackEngine(
        {
            "id": batch_id,
            "source_digest": "digest",
            "status": "rolled_back",
            "row_counts": {"rolled_back": deleted},
            "created_at": None,
            "completed_at": None,
        }
    )

    result = rollback_batch(engine=engine, batch_id=batch_id)

    assert result == {
        "batch_id": batch_id,
        "status": "rolled_back",
        "idempotent": True,
        "deleted": deleted,
    }
    assert len(engine.connection.calls) == 1
    assert engine.connection.calls[0][0].lstrip().startswith("SELECT")


def test_report_api_returns_404_before_cross_tenant_store_access():
    class Store:
        def __init__(self):
            self.calls = []

        def list_reports(self, **kwargs):
            self.calls.append(kwargs)
            return []

    store = Store()
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user_id = request.headers.get("x-test-user", "public")
        return await call_next(request)

    app.include_router(
        create_report_router(
            ReportRouterDeps(
                resolve_thread_id=lambda value: str(value),
                get_report_index_store=lambda: store,
            )
        )
    )
    client = TestClient(app)

    foreign = client.get(
        "/api/reports/index",
        params={"session_id": "web:bob:thread-1"},
        headers={"x-test-user": "alice"},
    )
    assert foreign.status_code == 404
    assert store.calls == []

    owned = client.get(
        "/api/reports/index",
        params={"session_id": "web:alice:thread-1"},
        headers={"x-test-user": "alice"},
    )
    assert owned.status_code == 200
    assert store.calls[-1]["user_id"] == "alice"
    assert store.calls[-1]["session_id"] == "web:alice:thread-1"

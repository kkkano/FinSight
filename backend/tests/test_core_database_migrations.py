# -*- coding: utf-8 -*-
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

import pytest

from backend.services.database import (
    DatabaseConfigurationError,
    DatabaseSchemaMismatch,
    alembic_heads,
    assert_core_schema_current,
    normalize_sync_postgres_dsn,
)


class _Result:
    def __init__(self, values):
        self.values = values

    def scalars(self):
        return self

    def all(self):
        return self.values


class _Connection:
    def __init__(self, revisions):
        self.revisions = revisions

    def execute(self, _statement):
        return _Result(self.revisions)


class _Engine:
    def __init__(self, revisions):
        self.connection = _Connection(revisions)

    @contextmanager
    def connect(self):
        yield self.connection


def test_alembic_head_and_core_tables_are_declared_once():
    assert alembic_heads() == ("20260715_0002",)
    source = (
        Path(__file__).resolve().parents[2]
        / "migrations"
        / "versions"
        / "20260715_0001_core_schema.py"
    ).read_text(encoding="utf-8")
    for table in (
        "conversation_threads",
        "watchlist_items",
        "reports",
        "report_citations",
        "agent_predictions",
        "agent_prediction_outcomes",
        "agent_run_archive",
        "monitor_page_leases",
        "monitor_comments",
        "llm_usage",
        "legacy_import_batches",
    ):
        assert f"CREATE TABLE IF NOT EXISTS {table}" in source
    assert "uq_legacy_import_batches_source_digest" in source
    assert "uq_agent_predictions_idempotency" in source


def test_schema_revision_mismatch_fails_fast():
    with pytest.raises(DatabaseSchemaMismatch, match="schema revision 不匹配"):
        assert_core_schema_current(engine=_Engine(["old-revision"]))
    status = assert_core_schema_current(engine=_Engine(["20260715_0002"]))
    assert status.is_current


def test_production_without_database_and_non_postgres_dsn_fail_closed(monkeypatch):
    monkeypatch.setenv("APP_MODE", "production")
    for name in (
        "FINSIGHT_POSTGRES_DSN",
        "AGENT_PREDICTION_POSTGRES_DSN",
        "RAG_V2_POSTGRES_DSN",
        "LANGGRAPH_CHECKPOINT_POSTGRES_DSN",
    ):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(DatabaseConfigurationError, match="production 必须配置"):
        assert_core_schema_current()
    with pytest.raises(DatabaseConfigurationError, match="只允许 PostgreSQL"):
        normalize_sync_postgres_dsn("sqlite:///data.db")

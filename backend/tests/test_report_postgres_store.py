from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from backend.services.report_index import ReportIndexStore


class _Result:
    def __init__(self, *, rows=None, scalar=None, rowcount=0):
        self.rows = list(rows or [])
        self.scalar_value = scalar
        self.rowcount = rowcount

    def mappings(self):
        return self

    def scalars(self):
        return self

    def all(self):
        return self.rows

    def first(self):
        return self.rows[0] if self.rows else None

    def scalar(self):
        return self.scalar_value


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


def _report_row():
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    return {
        "report_id": "rpt-1",
        "session_id": "web:alice:thread-1",
        "ticker": "AAPL",
        "title": "AAPL report",
        "summary": "summary",
        "generated_at": now,
        "confidence_score": 0.8,
        "tags": ["ai"],
        "source_type": "ai_generated",
        "quality_state": "pass",
        "publishable": True,
        "quality_reasons": [],
        "report": {"meta": {"analysis_depth": "report"}},
        "filing_type": None,
        "publisher": None,
        "created_at": now,
        "updated_at": now,
    }


def test_postgres_history_and_replay_queries_are_tenant_scoped():
    engine = _Engine(
        _Result(rows=[_report_row()]),
        _Result(rows=[{"report": {"report_id": "rpt-1"}, "trace_digest": {"span_count": 1}}]),
        _Result(rows=[{"source_id": "src-1", "url": "https://example.com"}]),
    )
    store = ReportIndexStore(engine=engine)

    items = store.list_reports(
        session_id="web:alice:thread-1",
        user_id="alice",
    )
    replay = store.get_report_replay(
        session_id="web:alice:thread-1",
        report_id="rpt-1",
        user_id="alice",
    )

    assert items[0]["report_id"] == "rpt-1"
    assert items[0]["analysis_depth"] == "report"
    assert replay["report"]["report_id"] == "rpt-1"
    assert replay["citations"][0]["source_id"] == "src-1"
    for sql, params in engine.connection.calls:
        assert "user_id=:user_id" in sql
        assert "session_id=:session_id" in sql
        assert params["user_id"] == "alice"
        assert params["session_id"] == "web:alice:thread-1"


def test_postgres_share_write_is_tenant_scoped_and_shared_read_is_token_scoped():
    write_engine = _Engine(_Result(scalar=None), _Result(rowcount=1))
    token = ReportIndexStore(engine=write_engine).create_share(
        report_id="rpt-1",
        user_id="alice",
    )

    assert token
    assert all("user_id=:user_id" in sql for sql, _ in write_engine.connection.calls)
    assert all(params["user_id"] == "alice" for _, params in write_engine.connection.calls)

    read_engine = _Engine(_Result(scalar={"report_id": "rpt-1"}))
    shared = ReportIndexStore(engine=read_engine).get_shared_report(token=token)
    sql, params = read_engine.connection.calls[0]
    assert shared == {"report_id": "rpt-1"}
    assert "share_token=:token AND publishable=true" in sql
    assert params == {"token": token}


def test_postgres_delete_session_removes_only_authenticated_tenant_rows():
    engine = _Engine(_Result(rowcount=2), _Result(rowcount=1))
    deleted = ReportIndexStore(engine=engine).delete_session(
        session_id="web:alice:thread-1",
        user_id="alice",
    )

    assert deleted == {"reports": 1, "citations": 2}
    for sql, params in engine.connection.calls:
        assert "user_id=:user_id" in sql
        assert "session_id=:session_id" in sql
        assert params == {"user_id": "alice", "session_id": "web:alice:thread-1"}

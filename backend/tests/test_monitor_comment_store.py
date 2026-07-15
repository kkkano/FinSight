from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.services.monitor_comment_store import (
    MonitorCommentStore,
    MonitorCommentStoreUnavailable,
    trigger_fingerprint,
)
from backend.services.monitor_commentator import produce_monitor_comments
from backend.services.monitor_signals import MarketSnapshot, MonitorTrigger


NOW = datetime(2026, 7, 11, 0, 0, tzinfo=timezone.utc)


class Result:
    def __init__(self, rows=None, rowcount=1, scalar_value=None):
        self.rows, self.rowcount, self.scalar_value = rows or [], rowcount, scalar_value
    def mappings(self): return self
    def all(self): return self.rows
    def scalar(self): return self.scalar_value


class Connection:
    def __init__(self): self.calls, self.rows, self.rowcount, self.scalar_value = [], [], 1, None
    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return Result(self.rows, self.rowcount, self.scalar_value)


class Engine:
    def __init__(self): self.conn, self.begin_calls = Connection(), 0
    @contextmanager
    def begin(self):
        self.begin_calls += 1
        yield self.conn
    @contextmanager
    def connect(self): yield self.conn


def test_constructor_never_runs_schema_ddl():
    engine = Engine()
    store = MonitorCommentStore(engine=engine)
    assert not hasattr(store, "ensure_schema")
    assert engine.conn.calls == []


def test_create_binds_original_trigger_and_dedupes_same_fingerprint():
    engine = Engine()
    store = MonitorCommentStore(engine=engine)
    first = store.create(
        user_id="alice", session_id="s1", symbol="aapl", ts=NOW,
        level="alert", text_value="突破", trigger_kind="level_break",
        trigger_detail="100 -> 101", trigger_observed_at="2026-07-11T00:00:00Z",
        source="agent", escalated=True,
    )
    assert first and first.trigger["kind"] == "level_break"
    params = engine.conn.calls[-1][1]
    assert len(params["trigger_fingerprint"]) == 64
    engine.conn.rowcount = 0
    duplicate = store.create(
        user_id="alice", session_id="s1", symbol="AAPL", ts=NOW,
        level="alert", text_value="重复", trigger_kind="level_break",
        trigger_detail="100 -> 101", trigger_observed_at="2026-07-11T00:00:00Z",
        source="agent", escalated=True,
    )
    assert duplicate is None
    assert trigger_fingerprint(symbol="AAPL", trigger_kind="level_break", trigger_detail="100 -> 101", observed_at="2026-07-11T00:00:00Z") == params["trigger_fingerprint"]


def test_list_supports_date_filter_desc_order_and_opaque_cursor():
    engine = Engine()
    store = MonitorCommentStore(engine=engine)
    engine.conn.rows = [
        {"id": "11111111-1111-1111-1111-111111111111", "user_id": "alice", "session_id": "s1",
         "symbol": "AAPL", "ts": NOW, "level": "info", "text": "new", "trigger_kind": "heartbeat",
         "trigger_detail": "ok", "trigger_observed_at": NOW.isoformat(), "source": "agent",
         "escalated": False, "prediction_id": None},
        {"id": "22222222-2222-2222-2222-222222222222", "user_id": "alice", "session_id": "s1",
         "symbol": "AAPL", "ts": NOW, "level": "warn", "text": "old", "trigger_kind": "macd_cross",
         "trigger_detail": "cross", "trigger_observed_at": NOW.isoformat(), "source": "agent",
         "escalated": False, "prediction_id": None},
    ]
    items, cursor = store.list(
        user_id="alice", session_id="s1", symbol="aapl", day=NOW.date(), limit=1,
    )
    assert [item.text for item in items] == ["new"]
    assert cursor and "alice" not in cursor
    store.list(user_id="alice", session_id="s1", symbol="AAPL", cursor=cursor, limit=1)
    sql, params = engine.conn.calls[-1]
    assert "(ts, id) <" in sql
    assert params["user_id"] == "alice" and params["session_id"] == "s1"
    assert params["symbol"] == "AAPL" and "symbol=:symbol" in sql


def test_list_and_list_after_are_read_only_without_schema_helpers(monkeypatch):
    engine = Engine()
    store = MonitorCommentStore(engine=engine)
    monkeypatch.setattr(
        store,
        "ensure_schema",
        lambda: pytest.fail("read path called ensure_schema"),
        raising=False,
    )

    assert store.list(user_id="alice", session_id="s1", symbol="AAPL") == ([], None)
    assert store.list_after(
        user_id="alice",
        session_id="s1",
        symbol="AAPL",
        last_event_id="11111111-1111-1111-1111-111111111111",
    ) == []
    assert engine.begin_calls == 0
    assert all(sql.lstrip().upper().startswith("SELECT") for sql, _ in engine.conn.calls)


def test_read_failure_is_stable_store_unavailable():
    class BrokenConnection(Connection):
        def execute(self, statement, params=None):
            raise RuntimeError("dsn and sql must stay private")

    engine = Engine()
    engine.conn = BrokenConnection()
    store = MonitorCommentStore(engine=engine)

    with pytest.raises(MonitorCommentStoreUnavailable, match="read unavailable"):
        store.list(user_id="alice", session_id="s1", symbol="AAPL")


def test_latest_comment_and_escalation_are_symbol_scoped():
    engine = Engine()
    engine.conn.scalar_value = NOW
    store = MonitorCommentStore(engine=engine)

    assert store.latest_comment_at(user_id="alice", session_id="s1", symbol="aapl") == NOW
    assert store.latest_escalation_at(user_id="alice", session_id="s1", symbol="AAPL") == NOW
    regular_sql, regular_params = engine.conn.calls[-2]
    escalation_sql, escalation_params = engine.conn.calls[-1]
    assert regular_params["symbol"] == escalation_params["symbol"] == "AAPL"
    assert "escalated IS TRUE" not in regular_sql
    assert "escalated IS TRUE" in escalation_sql


@pytest.mark.asyncio
async def test_producer_rejects_llm_owned_server_fields_and_keeps_server_escalation():
    captured = []
    store = SimpleNamespace(create=lambda **kwargs: captured.append(kwargs) or kwargs)
    target = SimpleNamespace(user_id="alice", session_id="s1", symbol="AAPL")
    snapshot = MarketSnapshot("AAPL", NOW.isoformat(), 101.0)
    trigger = MonitorTrigger(
        "prediction_level_break", "突破 100", NOW.isoformat(), "alert", True,
    )
    prediction = SimpleNamespace(id="11111111-1111-1111-1111-111111111111")

    async def foreign(_prompt):
        return {"level": "alert", "text": "突破", "source": "agent", "escalated": True,
                "prediction_id": "22222222-2222-2222-2222-222222222222"}

    assert await produce_monitor_comments(
        target,
        snapshot,
        [trigger],
        prediction,
        prediction_escalated=True,
        generator=foreign,
        store=store,
    ) == 1
    assert captured[0]["source"] == "system"
    assert captured[0]["level"] == "error"
    assert captured[0]["escalated"] is True
    assert captured[0]["prediction_id"] == prediction.id
    assert captured[0]["trigger_kind"] == "prediction_level_break"


@pytest.mark.asyncio
async def test_heartbeat_must_be_info_and_valid_comment_keeps_prediction():
    captured = []
    store = SimpleNamespace(create=lambda **kwargs: captured.append(kwargs) or kwargs)
    target = SimpleNamespace(user_id="alice", session_id="s1", symbol="AAPL")
    snapshot = MarketSnapshot("AAPL", NOW.isoformat(), 101.0)
    trigger = MonitorTrigger("heartbeat", "无事", NOW.isoformat(), "info")
    prediction = SimpleNamespace(id="11111111-1111-1111-1111-111111111111")

    async def valid(_prompt):
        return {"level": "info", "text": "价格平稳"}

    assert await produce_monitor_comments(target, snapshot, [trigger], prediction, generator=valid, store=store) == 1
    assert captured[0]["level"] == "info"
    assert captured[0]["prediction_id"] == prediction.id

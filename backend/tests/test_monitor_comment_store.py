from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from backend.services import monitor_comment_store as module
from backend.services.monitor_comment_store import (
    MonitorCommentStore,
    MonitorCommentStoreUnavailable,
    trigger_fingerprint,
)
from backend.services.monitor_commentator import produce_monitor_comments
from backend.services.monitor_signals import MarketSnapshot, MonitorTrigger


NOW = datetime(2026, 7, 11, 0, 0, tzinfo=timezone.utc)


class Result:
    def __init__(self, rows=None, rowcount=1): self.rows, self.rowcount = rows or [], rowcount
    def mappings(self): return self
    def all(self): return self.rows


class Connection:
    def __init__(self): self.calls, self.rows, self.rowcount = [], [], 1
    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return Result(self.rows, self.rowcount)


class Engine:
    def __init__(self): self.conn, self.begin_calls = Connection(), 0
    @contextmanager
    def begin(self):
        self.begin_calls += 1
        yield self.conn
    @contextmanager
    def connect(self): yield self.conn


@pytest.fixture(autouse=True)
def prediction_schema(monkeypatch):
    monkeypatch.setattr(module, "get_agent_prediction_store", lambda: SimpleNamespace(ensure_schema=lambda: True))


def test_schema_has_tenant_fk_cursor_index_and_trigger_dedupe():
    engine = Engine()
    store = MonitorCommentStore(engine=engine)
    store.ensure_schema()
    sql = "\n".join(call[0] for call in engine.conn.calls)
    assert "FOREIGN KEY(prediction_id, user_id) REFERENCES agent_predictions(id, user_id)" in sql
    assert "UNIQUE(user_id, session_id, trigger_fingerprint)" in sql
    assert "user_id, session_id, ts DESC, id DESC" in sql


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
    store.ensure_schema()
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
    items, cursor = store.list(user_id="alice", session_id="s1", day=NOW.date(), limit=1)
    assert [item.text for item in items] == ["new"]
    assert cursor and "alice" not in cursor
    store.list(user_id="alice", session_id="s1", cursor=cursor, limit=1)
    sql, params = engine.conn.calls[-1]
    assert "(ts, id) <" in sql
    assert params["user_id"] == "alice" and params["session_id"] == "s1"


def test_list_and_list_after_are_read_only_without_schema_helpers(monkeypatch):
    engine = Engine()
    store = MonitorCommentStore(engine=engine)
    monkeypatch.setattr(store, "ensure_schema", lambda: pytest.fail("read path called ensure_schema"))

    assert store.list(user_id="alice", session_id="s1") == ([], None)
    assert store.list_after(
        user_id="alice",
        session_id="s1",
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
        store.list(user_id="alice", session_id="s1")


@pytest.mark.asyncio
async def test_producer_validates_output_and_writes_system_error_for_foreign_prediction():
    captured = []
    store = SimpleNamespace(create=lambda **kwargs: captured.append(kwargs) or kwargs)
    target = SimpleNamespace(user_id="alice", session_id="s1", symbol="AAPL")
    snapshot = MarketSnapshot("AAPL", NOW.isoformat(), 101.0)
    trigger = MonitorTrigger("level_break", "突破 100", NOW.isoformat(), "alert")
    prediction = SimpleNamespace(id="11111111-1111-1111-1111-111111111111")

    async def foreign(_prompt):
        return {"level": "alert", "text": "突破", "source": "agent", "escalated": True,
                "prediction_id": "22222222-2222-2222-2222-222222222222"}

    assert await produce_monitor_comments(target, snapshot, [trigger], prediction, generator=foreign, store=store) == 1
    assert captured[0]["source"] == "system"
    assert captured[0]["level"] == "error"
    assert captured[0]["prediction_id"] is None
    assert captured[0]["trigger_kind"] == "level_break"


@pytest.mark.asyncio
async def test_heartbeat_must_be_info_and_valid_comment_keeps_prediction():
    captured = []
    store = SimpleNamespace(create=lambda **kwargs: captured.append(kwargs) or kwargs)
    target = SimpleNamespace(user_id="alice", session_id="s1", symbol="AAPL")
    snapshot = MarketSnapshot("AAPL", NOW.isoformat(), 101.0)
    trigger = MonitorTrigger("heartbeat", "无事", NOW.isoformat(), "info")
    prediction = SimpleNamespace(id="11111111-1111-1111-1111-111111111111")

    async def valid(_prompt):
        return {"level": "info", "text": "价格平稳", "source": "agent", "escalated": False,
                "prediction_id": prediction.id}

    assert await produce_monitor_comments(target, snapshot, [trigger], prediction, generator=valid, store=store) == 1
    assert captured[0]["level"] == "info"
    assert captured[0]["prediction_id"] == prediction.id

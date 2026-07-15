# -*- coding: utf-8 -*-
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from backend.services.monitor_lease_store import MonitorLeaseStore


NOW = datetime(2026, 7, 10, 15, 0, tzinfo=timezone.utc)


class Result:
    def __init__(self, *, rowcount=1, rows=None, scalar_value=True):
        self.rowcount = rowcount
        self._rows = rows or []
        self._scalar = scalar_value

    def mappings(self): return self
    def all(self): return self._rows
    def scalar(self): return self._scalar


class Connection:
    def __init__(self):
        self.calls = []
        self.rowcount = 1

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return Result(rowcount=self.rowcount)


class Engine:
    def __init__(self): self.conn = Connection()
    @contextmanager
    def begin(self): yield self.conn
    @contextmanager
    def connect(self): yield self.conn


def test_lease_constructor_has_no_ddl_and_acquire_stores_only_token_hash():
    engine = Engine()
    store = MonitorLeaseStore(engine=engine)
    assert engine.conn.calls == []
    first = store.acquire(user_id="alice", session_id="s1", symbol="aapl", now=NOW)
    second = store.acquire(user_id="alice", session_id="s1", symbol="aapl", now=NOW)

    sql = "\n".join(item[0] for item in engine.conn.calls)
    assert "CREATE TABLE" not in sql
    assert sql.count("INSERT INTO monitor_page_leases") == 2
    assert first["lease_token"] != second["lease_token"]
    insert_params = [params for statement, params in engine.conn.calls if statement.lstrip().startswith("INSERT")]
    assert all("lease_token" not in params for params in insert_params)
    assert all(len(params["lease_token_hash"]) == 64 for params in insert_params)
    assert first["expires_at"] == NOW + timedelta(seconds=90)


def test_renew_and_release_are_tenant_and_token_scoped():
    engine = Engine()
    store = MonitorLeaseStore(engine=engine)
    assert store.renew("lease-1", user_id="alice", lease_token="x" * 32, now=NOW)
    assert store.release("lease-1", user_id="alice", lease_token="x" * 32)

    update = next(call for call in engine.conn.calls if call[0].lstrip().startswith("UPDATE"))
    delete = next(call for call in engine.conn.calls if call[0].lstrip().startswith("DELETE"))
    assert "user_id = :user_id" in update[0] and "lease_token_hash" in update[0]
    assert "user_id = :user_id" in delete[0] and "lease_token_hash" in delete[0]
    assert update[1]["user_id"] == delete[1]["user_id"] == "alice"


def test_expired_renew_fails_and_cleanup_is_bounded_by_now():
    engine = Engine()
    store = MonitorLeaseStore(engine=engine)
    engine.conn.rowcount = 0
    assert store.renew("expired", user_id="alice", lease_token="x" * 32, now=NOW) is None
    assert store.cleanup_expired(now=NOW) == 0
    cleanup = [call for call in engine.conn.calls if "expires_at <= :now" in call[0]][0]
    assert cleanup[1]["now"] == NOW

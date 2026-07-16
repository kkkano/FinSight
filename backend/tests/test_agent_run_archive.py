# -*- coding: utf-8 -*-
from contextlib import contextmanager

from backend.services.agent_run_archive import AgentRunArchive


class Result:
    def __init__(self, row=None): self.row = row
    def mappings(self): return self
    def first(self): return self.row


class Connection:
    def __init__(self): self.calls = []; self.row = None
    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return Result(self.row)


class Engine:
    def __init__(self): self.conn = Connection()
    @contextmanager
    def begin(self): yield self.conn
    @contextmanager
    def connect(self): yield self.conn


def test_archive_constructor_has_no_ddl_and_upsert_is_tenant_safe():
    engine = Engine()
    store = AgentRunArchive(engine=engine)
    assert not hasattr(store, "ensure_schema")
    assert engine.conn.calls == []

    summary = {"usage_by_attribution": [{"agent": "risk_agent", "layer": "research", "prediction_id": None, "model": "gpt-4o", "prompt": 100, "completion": 20, "calls": 2, "failed_calls": 1, "duration_ms": 90}]}
    assert store.archive_usage_summary(run_id="run-1", user_id="alice", summary=summary) == 1
    assert len(engine.conn.calls) == 2
    archive_sql, archive_params = engine.conn.calls[0]
    usage_sql, usage_params = engine.conn.calls[1]
    assert "ON CONFLICT(run_id,user_id,agent,layer,model)" in archive_sql
    assert "ON CONFLICT(run_id,user_id,logical_role,attempt)" in usage_sql
    assert archive_params["user_id"] == usage_params["user_id"] == "alice"
    assert archive_params["run_id"] == usage_params["run_id"] == "run-1"
    assert archive_params["failed_call_count"] == 1
    assert usage_params["error_code"] == "llm_call_failed"


def test_cost_summary_is_tenant_agent_and_window_scoped():
    engine = Engine()
    engine.conn.row = {"tokens": 120, "cost": 0.25, "run_count": 2, "call_count": 3, "failed_call_count": 1, "unscored_runs": 1}
    result = AgentRunArchive(engine=engine).cost_summary(user_id="alice", agent="risk_agent", days=30)
    sql, params = engine.conn.calls[-1]
    assert "user_id=:user_id AND agent=:agent" in sql
    assert ":days * interval '1 day'" in sql
    assert params == {"user_id": "alice", "agent": "risk_agent", "days": 30}
    assert result["tokens"] == 120 and result["unscored_runs"] == 1

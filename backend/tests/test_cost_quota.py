# -*- coding: utf-8 -*-
"""WP5：按用户隔离的每日 LLM 成本配额。"""

from __future__ import annotations

import asyncio
import sqlite3
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.execution_router import ExecutionRouterDeps, create_execution_router
from backend.services import cost_audit
from backend.services.cost_audit import (
    CostAuditStore,
    UserDailyCostLimitExceeded,
    check_user_quota,
)


def _summary(cost: float) -> dict:
    return {
        "total_prompt_tokens": 100,
        "total_completion_tokens": 50,
        "total_tokens": 150,
        "llm_token_calls": 1,
        "total_cost_usd": cost,
        "tokens_by_model": {},
    }


@pytest.fixture()
def quota_store(tmp_path, monkeypatch) -> CostAuditStore:
    store = CostAuditStore(db_path=str(tmp_path / "cost_audit.db"))
    monkeypatch.setattr(cost_audit, "_STORE", store)
    return store


def test_cost_records_are_isolated_by_user_and_utc_day(quota_store):
    quota_store.record(
        session_id="alice-today",
        source="chat",
        summary=_summary(0.75),
        user_id="alice",
    )
    quota_store.record(
        session_id="bob-today",
        source="chat",
        summary=_summary(0.25),
        user_id="bob",
    )
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    quota_store._db().execute(
        """INSERT INTO cost_records
           (created_at, session_id, source, total_tokens, prompt_tokens,
            completion_tokens, llm_calls, cost_usd, model_breakdown, user_id)
           VALUES (?, 'alice-yesterday', 'chat', 150, 100, 50, 1, 9.0, NULL, 'alice')""",
        (yesterday,),
    )
    quota_store._db().commit()

    assert quota_store.today_cost_usd("alice") == pytest.approx(0.75)
    assert quota_store.today_cost_usd("bob") == pytest.approx(0.25)
    assert cost_audit.today_cost_usd("alice") == pytest.approx(0.75)


def test_legacy_cost_table_migrates_rows_to_public(tmp_path):
    db_path = tmp_path / "legacy.db"
    conn = sqlite3.connect(db_path)
    conn.execute(
        """CREATE TABLE cost_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            session_id TEXT NOT NULL,
            source TEXT NOT NULL DEFAULT 'other',
            total_tokens INTEGER NOT NULL DEFAULT 0,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            llm_calls INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0.0,
            model_breakdown TEXT
        )"""
    )
    conn.execute(
        """INSERT INTO cost_records
           (created_at, session_id, source, total_tokens, cost_usd)
           VALUES (?, 'legacy', 'chat', 10, 0.4)""",
        (datetime.now(timezone.utc).isoformat(),),
    )
    conn.commit()
    conn.close()

    store = CostAuditStore(db_path=str(db_path))
    assert store.today_cost_usd("public") == pytest.approx(0.4)
    assert store.today_cost_usd("alice") == 0.0
    indexes = {row[1] for row in store._db().execute("PRAGMA index_list(cost_records)")}
    assert "idx_cost_user_created" in indexes


def test_quota_disabled_and_admin_exempt(quota_store, monkeypatch):
    quota_store.record(
        session_id="expensive",
        source="chat",
        summary=_summary(99.0),
        user_id="alice",
    )
    monkeypatch.setenv("USER_DAILY_COST_LIMIT_USD", "0")
    check_user_quota("alice")

    monkeypatch.setenv("USER_DAILY_COST_LIMIT_USD", "1")
    check_user_quota("admin")
    with pytest.raises(UserDailyCostLimitExceeded):
        check_user_quota("alice")


def _execution_client(monkeypatch, seen_user_ids: list[str]) -> TestClient:
    async def fake_pipeline(**kwargs):
        seen_user_ids.append(kwargs["user_id"])
        yield {"type": "done", "response": "ok"}

    monkeypatch.setattr("backend.api.execution_router.run_graph_pipeline", fake_pipeline)

    async def unused_runner():
        raise AssertionError("配额路由测试不应启动真实图或 LLM")

    app = FastAPI()

    @app.middleware("http")
    async def inject_test_user(request: Request, call_next):
        request.state.user_id = request.headers.get("X-Test-User", "public")
        return await call_next(request)

    app.include_router(
        create_execution_router(
            ExecutionRouterDeps(
                get_graph_runner=unused_runner,
                resolve_thread_id=lambda value: value or "session-test",
                schedule_report_index=lambda **_kwargs: None,
                update_session_context=lambda **_kwargs: None,
                redact_sensitive_payload=lambda value: value,
                is_raw_trace_event=lambda _event: False,
                contract_info=lambda: {},
                sse_event_schema_version="test",
            )
        )
    )
    return TestClient(app)


def test_execution_entry_rejects_only_user_over_daily_limit(
    quota_store, monkeypatch
):
    quota_store.record(
        session_id="alice-cost",
        source="chat",
        summary=_summary(1.0),
        user_id="alice",
    )
    monkeypatch.setenv("USER_DAILY_COST_LIMIT_USD", "1.0")
    seen_user_ids: list[str] = []
    client = _execution_client(monkeypatch, seen_user_ids)

    blocked = client.post(
        "/api/execute",
        headers={"X-Test-User": "alice"},
        json={"query": "不会进入下游"},
    )
    assert blocked.status_code == 429
    assert "1.00 USD/天" in blocked.json()["detail"]
    assert seen_user_ids == []

    allowed = client.post(
        "/api/execute",
        headers={"X-Test-User": "bob"},
        json={"query": "允许进入离线桩"},
    )
    assert allowed.status_code == 200
    assert seen_user_ids == ["bob"]


def test_execution_entry_allows_over_limit_user_when_quota_disabled(
    quota_store, monkeypatch
):
    quota_store.record(
        session_id="alice-cost",
        source="chat",
        summary=_summary(50.0),
        user_id="alice",
    )
    monkeypatch.setenv("USER_DAILY_COST_LIMIT_USD", "0")
    seen_user_ids: list[str] = []
    client = _execution_client(monkeypatch, seen_user_ids)

    response = client.post(
        "/api/execute",
        headers={"X-Test-User": "alice"},
        json={"query": "配额关闭"},
    )
    assert response.status_code == 200
    assert seen_user_ids == ["alice"]


def test_execution_pipeline_records_cost_for_current_user(monkeypatch):
    from backend.graph import report_builder, runner
    from backend.graph import store as graph_store
    from backend.services import execution_service
    from backend.services.llm_usage import get_token_accumulator

    async def fake_run_graph_traced(_runner, **kwargs):
        accumulator = get_token_accumulator()
        assert accumulator is not None
        accumulator.add("gpt-4o-mini", 100, 50)
        return {
            "query": kwargs["query"],
            "output_mode": "chat",
            "artifacts": {"draft_markdown": "ok"},
        }

    monkeypatch.setattr(runner, "run_graph_traced", fake_run_graph_traced)
    monkeypatch.setattr(report_builder, "build_report_payload", lambda **_kwargs: None)
    monkeypatch.setattr(graph_store, "persist_memory_snapshot", lambda **_kwargs: None)

    recorded: list[dict] = []

    class AuditSpy:
        def record(self, **kwargs):
            recorded.append(kwargs)

    monkeypatch.setattr(cost_audit, "get_cost_audit_store", lambda: AuditSpy())

    async def get_runner():
        return object()

    deps = execution_service.ExecutionDeps(
        get_graph_runner=get_runner,
        schedule_report_index=lambda **_kwargs: None,
        update_session_context=lambda **_kwargs: None,
        redact_sensitive_payload=lambda value: value,
        is_raw_trace_event=lambda _event: False,
        contract_info=lambda: {},
        sse_event_schema_version="test",
    )

    async def collect():
        return [
            event
            async for event in execution_service.run_graph_pipeline(
                deps=deps,
                query="离线成本测试",
                thread_id="session-alice",
                source="execute",
                user_id="alice",
            )
        ]

    asyncio.run(collect())
    assert len(recorded) == 1
    assert recorded[0]["user_id"] == "alice"
    assert recorded[0]["summary"]["total_tokens"] == 150

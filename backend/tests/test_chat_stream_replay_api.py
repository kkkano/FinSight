from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import backend.api.execution_router as execution_router
from backend.api.execution_router import ExecutionRouterDeps, create_execution_router


def _events(response) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]


def _client(monkeypatch) -> TestClient:
    async def fake_pipeline(**kwargs):
        run_id = kwargs["run_id"]
        yield {"type": "token", "content": "A", "run_id": run_id}
        yield {"type": "token", "content": "B", "run_id": run_id}
        yield {"type": "done", "response": "AB", "run_id": run_id}

    monkeypatch.setattr(execution_router, "run_graph_pipeline", fake_pipeline)
    monkeypatch.setattr(
        execution_router,
        "_enforce_user_quota",
        lambda request: str(getattr(request.state, "user_id", "public")),
    )
    execution_router._RUN_OWNERS.clear()
    execution_router._STREAM_TASKS_BY_RUN.clear()

    async def unused_runner():
        raise AssertionError("流重放 API 测试不应启动真实图或 LLM")

    app = FastAPI()

    @app.middleware("http")
    async def bind_user(request: Request, call_next):
        request.state.user_id = request.headers.get("x-test-user", "user-a")
        return await call_next(request)

    app.include_router(
        create_execution_router(
            ExecutionRouterDeps(
                get_graph_runner=unused_runner,
                resolve_thread_id=lambda value: value or "session-replay-test",
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


def test_execute_stream_replays_only_events_after_cursor(monkeypatch):
    client = _client(monkeypatch)
    initial = client.post(
        "/api/execute",
        json={"query": "offline replay", "run_id": "wp6-replay"},
    )
    assert initial.status_code == 200
    assert [event["seq"] for event in _events(initial)] == [1, 2, 3]

    resumed = client.get("/api/execute/runs/wp6-replay/events", params={"after_seq": 1})
    assert resumed.status_code == 200
    resumed_events = _events(resumed)
    assert [event["seq"] for event in resumed_events] == [2, 3]
    assert [event["content"] for event in resumed_events if event["type"] == "token"] == ["B"]
    assert resumed_events[-1]["type"] == "done"


def test_execute_run_is_not_visible_or_cancellable_across_users(monkeypatch):
    client = _client(monkeypatch)
    created = client.post(
        "/api/execute",
        json={"query": "tenant isolation", "run_id": "wp6-owner"},
        headers={"x-test-user": "user-a"},
    )
    assert created.status_code == 200

    replay = client.get(
        "/api/execute/runs/wp6-owner/events",
        headers={"x-test-user": "user-b"},
    )
    cancel = client.post(
        "/api/execute/runs/wp6-owner/cancel",
        headers={"x-test-user": "user-b"},
    )
    assert replay.status_code == 404
    assert cancel.status_code == 404


def test_execute_rejects_unknown_run(monkeypatch):
    client = _client(monkeypatch)
    response = client.get("/api/execute/runs/missing-run/events")
    assert response.status_code == 404

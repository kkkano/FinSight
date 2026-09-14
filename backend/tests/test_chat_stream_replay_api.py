from __future__ import annotations

import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import backend.api.execution_router as execution_router
import backend.api.session_context as session_context
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
                resolve_thread_id=session_context._resolve_thread_id,
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


def test_stream_pump_redacts_upstream_exception(monkeypatch):
    client = _client(monkeypatch)

    async def leaking_pipeline(**_kwargs):
        raise RuntimeError("postgresql://user:password@db.example/finsight?token=secret")
        yield  # pragma: no cover

    monkeypatch.setattr(execution_router, "run_graph_pipeline", leaking_pipeline)
    response = client.post(
        "/api/execute",
        json={"query": "stream failure", "run_id": "stream-error"},
        headers={"x-test-user": "user-a"},
    )

    assert response.status_code == 200
    payload = _events(response)[-1]
    assert payload["type"] == "error"
    assert payload["code"] == "execution_failed"
    assert payload["message"] == "执行失败，请稍后重试。"
    assert "password" not in str(payload).lower()
    assert "postgresql://" not in str(payload).lower()


def test_execute_binds_new_authenticated_session_to_request_user(monkeypatch):
    client = _client(monkeypatch)
    response = client.post(
        "/api/execute",
        json={"query": "owner binding", "run_id": "owner-new"},
        headers={"x-test-user": "user-a"},
    )

    assert response.status_code == 200
    session_ids = {event["session_id"] for event in _events(response)}
    assert len(session_ids) == 1
    assert next(iter(session_ids)).startswith("public:user-a:")


def test_execute_rejects_cross_user_session_without_disclosing_owner(monkeypatch):
    client = _client(monkeypatch)
    response = client.post(
        "/api/execute",
        json={"query": "cross owner", "session_id": "public:user-b:thread-1"},
        headers={"x-test-user": "user-a"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == {
        "code": "session_not_found",
        "message": "session not found",
    }


def test_execute_confines_anonymous_session_namespace(monkeypatch):
    client = _client(monkeypatch)
    rejected = client.post(
        "/api/execute",
        json={"query": "anonymous escape", "session_id": "public:user-a:thread-1"},
        headers={"x-test-user": "public"},
    )
    accepted = client.post(
        "/api/execute",
        json={"query": "anonymous local", "session_id": "thread-1", "run_id": "anon-thread"},
        headers={"x-test-user": "public"},
    )

    assert rejected.status_code == 404
    assert accepted.status_code == 200
    assert {event["session_id"] for event in _events(accepted)} == {"public:anonymous:thread-1"}


def test_execute_ignores_forged_user_id_in_request_context(monkeypatch):
    client = _client(monkeypatch)
    captured: dict = {}

    async def capture_pipeline(**kwargs):
        captured.update(kwargs)
        yield {"type": "done", "response": "ok", "run_id": kwargs["run_id"]}

    monkeypatch.setattr(execution_router, "run_graph_pipeline", capture_pipeline)
    response = client.post(
        "/api/execute",
        json={
            "query": "identity binding",
            "run_id": "owner-context",
            "context": {"active_symbol": "AAPL", "__user_id": "victim"},
        },
        headers={"x-test-user": "user-a"},
    )

    assert response.status_code == 200
    assert captured["user_id"] == "user-a"
    assert captured["ui_context"]["__user_id"] == "user-a"

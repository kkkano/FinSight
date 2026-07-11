from __future__ import annotations

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.chat_router import ChatRouterDeps, create_chat_router


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

    monkeypatch.setattr("backend.services.execution_service.run_graph_pipeline", fake_pipeline)
    monkeypatch.setattr("backend.api.chat_router._ensure_llm_available", lambda: None)

    class EmptyContext:
        def get_last_n_turns(self, _limit):
            return []

    async def unused_runner():
        raise AssertionError("流重放 API 测试不应启动真实图或 LLM")

    app = FastAPI()
    app.include_router(
        create_chat_router(
            ChatRouterDeps(
                get_graph_runner=unused_runner,
                resolve_thread_id=lambda value: value or "session-replay-test",
                build_ui_context=lambda _request: {},
                resolve_query_reference=lambda query, _thread_id: query,
                schedule_report_index=lambda **_kwargs: None,
                update_session_context=lambda **_kwargs: None,
                contract_info=lambda: {},
                resolve_trace_raw_enabled=lambda _request: False,
                is_raw_trace_event=lambda _event: False,
                redact_sensitive_payload=lambda value: value,
                get_session_context=lambda _thread_id: EmptyContext(),
                chat_response_schema_version="test",
                sse_event_schema_version="test",
            )
        )
    )
    return TestClient(app)


def test_chat_stream_replay_returns_only_events_after_cursor(monkeypatch):
    client = _client(monkeypatch)
    initial = client.post("/chat/supervisor/stream", json={"query": "offline replay"})
    assert initial.status_code == 200
    initial_events = _events(initial)
    assert [event["seq"] for event in initial_events] == [1, 2, 3]
    run_id = initial.headers["x-run-id"]

    resumed = client.get(f"/api/chat/stream/{run_id}", params={"after_seq": 1})
    assert resumed.status_code == 200
    resumed_events = _events(resumed)

    assert [event["seq"] for event in resumed_events] == [2, 3]
    assert [event["content"] for event in resumed_events if event["type"] == "token"] == ["B"]
    assert resumed_events[-1]["type"] == "done"


def test_chat_stream_replay_returns_410_for_unknown_run(monkeypatch):
    client = _client(monkeypatch)
    response = client.get("/api/chat/stream/missing-run", params={"after_seq": 0})
    assert response.status_code == 410

"""验证终态保存、跨进程恢复和快照兼容；所有模型与存储均隔离。"""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api import execution_router
from backend.api.execution_router import ExecutionRouterDeps, create_execution_router
from backend.api.session_context import _resolve_thread_id
from backend.api.stream_replay import ReplayBuffer
from backend.services import execution_service
from backend.services.conversation_store import _merge_messages
from backend.services.research_run_store import public_run, terminal_status


class MemoryRunStore:
    """API 契约测试替身；真正 PostgreSQL 事务由独立 integration suite 验证。"""
    def __init__(self):
        self.rows = {}
        self.fail_finish = False
        self.fail_begin = False
        self.finish_calls = 0

    def get(self, run_id, *, user_id):
        return deepcopy(self.rows.get((user_id, run_id)))

    def begin(self, *, user_id, run_id, session_id, query, fingerprint, user_message_id=None, assistant_message_id=None):
        if self.fail_begin:
            raise RuntimeError("private database credentials")
        key = (user_id, run_id)
        if key in self.rows:
            return self.rows[key], False
        self.rows[key] = {
            "run_id": run_id, "session_id": session_id, "query": query, "status": "running",
            "request_fingerprint": fingerprint, "user_message_id": user_message_id or "server-user",
            "assistant_message_id": assistant_message_id or "server-assistant", "final_payload": None,
        }
        return deepcopy(self.rows[key]), True

    def finish(self, run_id, event, *, user_id):
        self.finish_calls += 1
        if self.fail_finish:
            raise RuntimeError("private database credentials")
        row = self.rows[(user_id, run_id)]
        if row["status"] != "running":
            return deepcopy(row["final_payload"])
        row["status"] = terminal_status(event)
        row["final_payload"] = {
            **event, "persistence_status": "saved", "run_status": row["status"], "conversation_version": 2,
            "user_message_id": row["user_message_id"], "assistant_message_id": row["assistant_message_id"],
            "assistant_message": {"id": row["assistant_message_id"], "content": event.get("response", "failed")},
        }
        return deepcopy(row["final_payload"])

    def heartbeat(self, run_id, *, user_id):
        return self.rows[(user_id, run_id)]["status"] == "running"


def events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


@pytest.fixture
def delivery_client(monkeypatch):
    store = MemoryRunStore()
    calls = {"graph": 0, "preflight": 0}
    monkeypatch.setattr(execution_router, "get_research_run_store", lambda: store)
    monkeypatch.setattr(execution_router, "replay_buffer", ReplayBuffer())
    # OrderedDict 是生产 LRU 的契约，测试保留相同行为。
    from collections import OrderedDict
    monkeypatch.setattr(execution_router, "_RUN_OWNERS", OrderedDict())
    monkeypatch.setattr(execution_router, "_STREAM_TASKS_BY_RUN", {})
    monkeypatch.setattr(execution_router, "_enforce_user_quota", lambda _request: "user-a")

    async def preflight():
        calls["preflight"] += 1

    async def pipeline(**kwargs):
        calls["graph"] += 1
        yield {"type": "token", "content": "完整研究结果"}
        yield {"type": "done", "response": "完整研究结果", "publishable": True}

    monkeypatch.setattr(execution_router, "ensure_model_available", preflight)
    monkeypatch.setattr(execution_router, "run_graph_pipeline", pipeline)
    app = FastAPI()

    @app.middleware("http")
    async def owner(request: Request, call_next):
        request.state.user_id = request.headers.get("x-test-user", "user-a")
        return await call_next(request)

    app.include_router(create_execution_router(ExecutionRouterDeps(
        get_graph_runner=lambda: None, resolve_thread_id=_resolve_thread_id,
        schedule_report_index=lambda **_kw: None, update_session_context=lambda **_kw: None,
        redact_sensitive_payload=lambda value: value, is_raw_trace_event=lambda _value: False,
        contract_info=lambda: {}, sse_event_schema_version="test",
    )))
    with TestClient(app) as client:
        yield client, store, calls


def request_body(**extra):
    return {"query": "英特尔四个维度分别怎么样", "run_id": "delivery-run", "session_id": "public:user-a:thread",
            "client_user_message_id": "user-message", "client_assistant_message_id": "assistant-message", **extra}


def test_terminal_saved_and_duplicate_post_never_restarts_graph(delivery_client):
    client, store, calls = delivery_client
    first = client.post("/api/execute", json=request_body())
    done = events(first)[-1]
    assert done["persistence_status"] == "saved"
    assert done["assistant_message_id"] == "assistant-message"
    assert store.rows[("user-a", "delivery-run")]["status"] == "completed"
    retry = client.post("/api/execute", json=request_body())
    assert retry.status_code == 200
    assert events(retry)[-1]["response"] == "完整研究结果"
    assert calls == {"graph": 1, "preflight": 1}


def test_completed_run_recovers_after_in_memory_replay_and_owner_cache_lost(delivery_client, monkeypatch):
    client, _store, calls = delivery_client
    client.post("/api/execute", json=request_body())
    monkeypatch.setattr(execution_router, "replay_buffer", ReplayBuffer())
    execution_router._RUN_OWNERS.clear()
    recovered = client.get("/api/execute/runs/delivery-run/events?after_seq=500")
    assert recovered.status_code == 200
    payload = events(recovered)[0]
    assert payload["recovered"] is True and payload["seq"] == 501
    assert payload["response"] == "完整研究结果"
    read = client.get("/api/execute/runs/delivery-run").json()
    assert read["status"] == "completed" and read["result"]["persistence_status"] == "saved"
    assert calls["graph"] == 1


def test_persistent_run_owner_is_enforced_after_restart(delivery_client, monkeypatch):
    client, _store, _calls = delivery_client
    client.post("/api/execute", json=request_body())
    monkeypatch.setattr(execution_router, "replay_buffer", ReplayBuffer())
    execution_router._RUN_OWNERS.clear()
    for endpoint in ("", "/events"):
        assert client.get(f"/api/execute/runs/delivery-run{endpoint}", headers={"x-test-user": "user-b"}).status_code == 404
    assert client.post("/api/execute/runs/delivery-run/cancel", headers={"x-test-user": "user-b"}).status_code == 404


def test_same_run_cannot_be_reused_for_different_query(delivery_client):
    client, _store, calls = delivery_client
    client.post("/api/execute", json=request_body())
    response = client.post("/api/execute", json=request_body(query="另一个付费报告"))
    assert response.status_code == 409
    assert calls["graph"] == 1


def test_store_failure_prevents_graph_and_failed_save_preserves_preview(delivery_client):
    client, store, calls = delivery_client
    store.fail_begin = True
    rejected = client.post("/api/execute", json=request_body())
    assert rejected.status_code == 503 and calls["graph"] == 0
    assert calls["preflight"] == 0
    assert "credentials" not in rejected.text
    store.fail_begin = False
    store.fail_finish = True
    done = events(client.post("/api/execute", json=request_body()))[-1]
    assert done["response"] == "完整研究结果"
    assert done["persistence_status"] == "failed"
    assert done["error_code"] == "conversation_persistence_failed"
    assert done["publishable"] is False
    assert "credentials" not in str(done)


def test_failed_preflight_is_durable_and_recovery_never_calls_model_again(delivery_client, monkeypatch):
    from fastapi import HTTPException
    client, store, calls = delivery_client
    probes = []

    async def unavailable():
        probes.append(True)
        raise HTTPException(503, detail={"code": "model_unavailable", "message": "模型暂时不可用。"})

    monkeypatch.setattr(execution_router, "ensure_model_available", unavailable)
    failed = client.post("/api/execute", json=request_body())
    assert failed.status_code == 503 and calls["graph"] == 0
    row = store.rows[("user-a", "delivery-run")]
    assert row["status"] == "failed" and row["final_payload"]["error_code"] == "model_unavailable"
    replay = events(client.post("/api/execute", json=request_body()))[-1]
    assert replay["error_code"] == "model_unavailable" and not replay["publishable"]
    assert probes == [True]


def test_unexpected_pipeline_end_is_persisted_as_interrupted(delivery_client, monkeypatch):
    client, store, _calls = delivery_client

    async def incomplete(**_kwargs):
        yield {"type": "token", "content": "未完成"}

    monkeypatch.setattr(execution_router, "run_graph_pipeline", incomplete)
    payload = events(client.post("/api/execute", json=request_body()))[-1]
    assert payload["code"] == "run_interrupted"
    assert payload["run_status"] == "interrupted"
    assert payload["response"] == "未完成"
    assert payload["assistant_message"]["content"] == "未完成"
    assert store.rows[("user-a", "delivery-run")]["status"] == "interrupted"


def test_snapshot_cannot_overwrite_server_reply_and_retry_is_in_place():
    user = {"id": "u", "role": "user", "content": "问题"}
    first = {"id": "a1", "role": "assistant", "content": "旧回答", "reply_to": "u", "run_sequence": 1}
    latest = {"id": "a2", "role": "assistant", "content": "最新完整回答", "reply_to": "u", "run_sequence": 2}
    other = {"id": "u2", "role": "user", "content": "后一个问题"}
    # 旧运行最后完成、旧浏览器快照又迟到，仍只能显示更新运行的答案。
    merged = _merge_messages([user, first, other], [{**latest, "content": "被截断"}], [user, latest, first])
    assert [message["id"] for message in merged] == ["u", "a2", "u2"]
    assert merged[1]["content"] == "最新完整回答"


def test_public_run_omits_internal_identity_and_request_fields():
    row = {"run_id": "r", "session_id": "s", "status": "completed", "user_message_id": "u", "assistant_message_id": "a",
           "user_id": "private-owner", "worker_id": "private-worker", "query": "private", "final_payload": {"response": "saved"}}
    result = public_run(row)
    assert result["result"] == {"response": "saved"}
    assert not {"worker_id", "user_id", "query", "request_fingerprint"} & result.keys()


def test_chat_quality_block_is_not_replaced_by_empty_report_success():
    quality, blocked = execution_service._apply_quality_gate(
        state={"output_mode": "chat", "artifacts": {"draft_markdown": "有限预览", "result_quality": {
            "state": "block", "reasons": [{"code": "TASK_NOT_COVERED", "severity": "block", "message": "缺少维度"}],
        }}}, report=None, source="test",
    )
    assert blocked and quality["state"] == "block"
    assert quality["answer_status"] == "blocked"


def test_pipeline_awaits_final_commit_before_exposing_done(monkeypatch):
    from backend.graph import runner, report_builder
    order = []

    async def graph(*_args, **_kwargs):
        return {"output_mode": "chat", "artifacts": {"draft_markdown": "正文"}}

    async def get_runner():
        return object()

    async def persist(event):
        await asyncio.sleep(0)
        order.append("committed")
        return {**event, "persistence_status": "saved"}

    monkeypatch.setattr(runner, "run_graph_traced", graph)
    monkeypatch.setattr(report_builder, "build_report_payload", lambda **_kwargs: None)
    deps = execution_service.ExecutionDeps(
        get_graph_runner=get_runner, schedule_report_index=lambda **_kwargs: None,
        update_session_context=lambda **_kwargs: None, redact_sensitive_payload=lambda value: value,
        is_raw_trace_event=lambda _value: False, contract_info=lambda: {}, sse_event_schema_version="test",
        persist_run_event=persist,
    )

    async def collect():
        async for event in execution_service.run_graph_pipeline(deps=deps, query="问题", thread_id="public:u:t"):
            if event.get("type") == "done":
                assert order == ["committed"]
                assert event["persistence_status"] == "saved"
                order.append("done")

    asyncio.run(collect())
    assert order == ["committed", "done"]

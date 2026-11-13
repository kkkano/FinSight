"""验证终态保存、跨进程恢复和快照兼容；所有模型与存储均隔离。"""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from contextlib import asynccontextmanager
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api import execution_router
from backend.api.execution_router import ExecutionRouterDeps, create_execution_router
from backend.api.session_context import _resolve_thread_id
from backend.api.stream_replay import ReplayBuffer
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
    from backend.agent_runtime import service
    store = MemoryRunStore()
    calls = {"runtime": 0, "preflight": 0}
    monkeypatch.setattr(execution_router, "get_research_run_store", lambda: store)
    monkeypatch.setattr(execution_router, "replay_buffer", ReplayBuffer())
    # OrderedDict 是生产 LRU 的契约，测试保留相同行为。
    from collections import OrderedDict
    monkeypatch.setattr(execution_router, "_RUN_OWNERS", OrderedDict())
    monkeypatch.setattr(execution_router, "_STREAM_TASKS_BY_RUN", {})
    monkeypatch.setattr(execution_router, "_enforce_user_quota", lambda _request: "user-a")

    async def preflight(_context):
        calls["preflight"] += 1

    async def pipeline(**kwargs):
        calls["runtime"] += 1
        yield {"type": "token", "content": "完整研究结果"}
        yield {"type": "done", "response": "完整研究结果", "publishable": True}

    monkeypatch.setattr(service, "cached_model_capability", lambda: None)
    monkeypatch.setattr(service, "preflight", preflight)
    monkeypatch.setattr(service, "run_agent_pipeline", pipeline)
    app = FastAPI()

    @app.middleware("http")
    async def owner(request: Request, call_next):
        request.state.user_id = request.headers.get("x-test-user", "user-a")
        return await call_next(request)

    app.include_router(create_execution_router(ExecutionRouterDeps(
        resolve_thread_id=_resolve_thread_id,
        schedule_report_index=lambda **_kw: None, update_session_context=lambda **_kw: None,
    )))
    with TestClient(app) as client:
        yield client, store, calls


def request_body(**extra):
    return {"query": "英特尔四个维度分别怎么样", "run_id": "delivery-run", "session_id": "public:user-a:thread",
            "client_user_message_id": "user-message", "client_assistant_message_id": "assistant-message", **extra}


@pytest.mark.parametrize("tamper", [None, "answer", "findings", "message", "owner"])
def test_revision_post_uses_owned_saved_review_and_exact_original(delivery_client, tamper):
    import hashlib
    client, store, calls = delivery_client
    answer = "  原答案 42。\n"
    findings = [{"quote": "原答案 42。", "issue": "需要核对", "evidence": "[1]", "suggestion": "读回资料"}]
    coverage = [{"requirement": "说明价格", "met": True}]
    parent, _ = store.begin(user_id="user-a", run_id="parent-run", session_id="public:user-a:thread",
                           query="原问题", fingerprint="original", assistant_message_id="parent-message")
    store.finish("parent-run", {"type": "done", "response": answer,
        "blocks": [{"id": "review-1", "kind": "review", "review": {"review_id": "review-1", "status": "completed",
            "verdict": "revise", "answer_sha256": hashlib.sha256(answer.encode()).hexdigest(),
            "findings": findings, "coverage": coverage}}]}, user_id="user-a")
    revision = {"source_run_id": "parent-run", "source_message_id": "parent-message", "review_id": "review-1",
                "answer": answer, "findings": deepcopy(findings), "coverage": coverage}
    if tamper == "answer":
        revision["answer"] = answer.strip()
    elif tamper == "findings":
        revision["findings"][0]["suggestion"] = "不同的记录"
    elif tamper == "message":
        revision["source_message_id"] = "other-message"
    elif tamper == "owner":
        store.rows[("another-user", "parent-run")] = store.rows.pop(("user-a", "parent-run"))
    response = client.post("/api/execute", json=request_body(
        query="按核查意见修订", resume_from_run_id="parent-run", review_revision=revision))
    assert response.status_code == (200 if tamper is None else 404 if tamper == "owner" else 409)
    assert calls["runtime"] == (1 if tamper is None else 0)


def test_terminal_saved_and_duplicate_post_never_restarts_runtime(delivery_client):
    client, store, calls = delivery_client
    first = client.post("/api/execute", json=request_body())
    done = events(first)[-1]
    assert done["persistence_status"] == "saved"
    assert done["assistant_message_id"] == "assistant-message"
    assert store.rows[("user-a", "delivery-run")]["status"] == "completed"
    retry = client.post("/api/execute", json=request_body())
    assert retry.status_code == 200
    assert events(retry)[-1]["response"] == "完整研究结果"
    assert calls == {"runtime": 1, "preflight": 1}


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
    assert calls["runtime"] == 1


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
    assert calls["runtime"] == 1


def test_store_failure_prevents_runtime_and_failed_save_preserves_preview(delivery_client):
    client, store, calls = delivery_client
    store.fail_begin = True
    rejected = client.post("/api/execute", json=request_body())
    assert rejected.status_code == 503 and calls["runtime"] == 0
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
    from backend.agent_runtime import service
    client, store, calls = delivery_client
    probes = []

    async def unavailable(_context):
        probes.append(True)
        raise HTTPException(503, detail={"code": "model_unavailable", "message": "模型暂时不可用。"})

    monkeypatch.setattr(service, "preflight", unavailable)
    failed = client.post("/api/execute", json=request_body())
    assert failed.status_code == 200
    assert events(failed)[-1]["type"] == "error"
    assert calls["runtime"] == 0
    row = store.rows[("user-a", "delivery-run")]
    assert row["status"] == "failed" and row["final_payload"]["error_code"] == "model_unavailable"
    replay = events(client.post("/api/execute", json=request_body()))[-1]
    assert replay["error_code"] == "model_unavailable" and not replay["publishable"]
    assert probes == [True]


def test_unexpected_pipeline_end_is_persisted_as_interrupted(delivery_client, monkeypatch):
    from backend.agent_runtime import service
    client, store, _calls = delivery_client

    async def incomplete(**_kwargs):
        yield {"type": "token", "content": "未完成"}

    monkeypatch.setattr(service, "run_agent_pipeline", incomplete)
    payload = events(client.post("/api/execute", json=request_body()))[-1]
    assert payload["code"] == "run_interrupted"
    assert payload["run_status"] == "interrupted"
    assert payload["response"] == "未完成"
    assert payload["assistant_message"]["content"] == "未完成"
    assert store.rows[("user-a", "delivery-run")]["status"] == "interrupted"


def test_cancelling_streamed_preflight_saves_terminal_state(delivery_client, monkeypatch):
    from backend.agent_runtime import service
    client, store, calls = delivery_client
    started = Event()
    contexts = []

    async def pending_preflight(context):
        contexts.append(context)
        started.set()
        await asyncio.sleep(10)

    monkeypatch.setattr(service, "preflight", pending_preflight)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(client.post, "/api/execute", json=request_body())
        assert started.wait(timeout=5)
        cancelled = client.post("/api/execute/runs/delivery-run/cancel")
        assert cancelled.status_code == 200
        terminal = events(pending.result(timeout=5))[-1]
    assert terminal["type"] == "cancelled"
    assert terminal["persistence_status"] == "saved"
    assert terminal["publishable"] is False
    assert store.rows[("user-a", "delivery-run")]["status"] == "cancelled"
    assert contexts[0].status == "cancelled"
    assert calls["runtime"] == 0


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


class FixtureRuntime:
    """模型/工具替身，交付仍经过真实服务、事件和持久化适配。"""

    def __init__(self, *, context, session_id, query, model, emit, **_kwargs):
        self.context, self.session_id, self.query = context, session_id, query
        self.model, self.emit = model, emit
        self.root_content = "正文"
        self.report_title = None
        self.report_revision, self.reviews, self.ui_context = None, [], {}
        self.observed_tickers, self.actions = [], {}
        self.tool_count = 0
        self.registry = SimpleNamespace(attempts=[])
        self.data = SimpleNamespace(sources={}, artifacts=[], results={}, save=lambda: None)
        self.limiter = SimpleNamespace(slot=self.slot)

    @asynccontextmanager
    async def slot(self, *_args, **_kwargs):
        yield

    async def run_agent(self):
        await self.emit("content.delta", {"block_id": "root-answer", "delta": self.root_content})
        await self.emit("content.block_finished", {"block_id": "root-answer", "content_phase": "final",
            "finish_reason": "stop", "completion_status": "completed"})
        return {"stopped": "completed"}

    async def close(self):
        pass


def test_authoritative_commit_preserves_verbatim_reviewed_answer_and_revision_link(monkeypatch):
    from backend.services import research_run_store as module
    answer = "  原文 42。\n\n"
    review = {"review_id": "review-1", "status": "completed", "verdict": "pass", "findings": [], "coverage": []}
    blocks = [{"id": "text-1", "kind": "text", "content": answer, "revision": 0},
              {"id": "review-1", "kind": "review", "review": review, "revision": 1}]
    revision = {"source_run_id": "parent", "review_id": "parent-review"}
    inserted, written = [], []
    store = object.__new__(module.PostgresResearchRunStore)
    monkeypatch.setattr(store, "_insert_message", lambda _conn, _owner, _row, message, **kwargs: inserted.append(deepcopy(message)))
    monkeypatch.setattr(module, "_canonical_messages", lambda *_args: inserted)
    monkeypatch.setattr(module, "_write_thread", lambda _conn, _owner, _sid, _current, messages:
                        written.extend(deepcopy(messages)) or {"version": 2})
    conn = SimpleNamespace(execute=lambda *_args: None)
    row = {"assistant_message_id": "assistant", "user_message_id": "user", "run_id": "run", "session_id": "session", "sequence": 1}
    result = store._finish_locked(conn, "owner", row, {"messages": []},
        {"type": "done", "response": answer, "blocks": blocks, "review_revision": revision})
    assert result["response"] == result["assistant_message"]["content"] == inserted[0]["content"] == written[0]["content"] == answer
    assert result["assistant_message"]["blocks"] == blocks
    assert result["assistant_message"]["review_revision"] == revision


def test_chat_quality_block_is_not_replaced_by_empty_report_success():
    from backend.agent_runtime.events import EventSink
    from backend.agent_runtime.finalize import completed_event
    context = execution_router.NativeRunContext.create(owner="public", entry="chat")
    sink = EventSink(asyncio.Queue(), run_id=context.run_id, session_id="public:anonymous:thread")
    runtime = FixtureRuntime(context=context, session_id=sink.session_id, query="问题",
        model=SimpleNamespace(config=SimpleNamespace(model="fixture")), emit=sink.emit)
    runtime.root_content = "有限预览 [999]"
    sink.runtime = runtime
    event = asyncio.run(completed_event(runtime, {"stopped": "completed"}, sink,
        SimpleNamespace(update_session_context=lambda **_kwargs: None)))
    assert event["quality_blocked"] and event["quality"]["state"] == "block"
    assert event["publishable"] is False
    assert event["report"] is None
    assert event["response"] == runtime.root_content


def test_pipeline_awaits_final_commit_before_exposing_done(monkeypatch):
    from backend.agent_runtime import service
    order = []

    async def persist(event):
        await asyncio.sleep(0)
        order.append("committed")
        return {**event, "persistence_status": "saved"}

    monkeypatch.setattr(service, "AgentRuntime", FixtureRuntime)
    monkeypatch.setattr(service, "resolve_model", lambda: SimpleNamespace(model="fixture"))
    monkeypatch.setattr(service, "ModelTransport", lambda config: SimpleNamespace(config=config))
    deps = execution_router.RuntimeDeliveryDeps(
        schedule_report_index=lambda **_kwargs: None,
        update_session_context=lambda **_kwargs: None,
        persist_run_event=persist,
    )

    async def collect():
        context = execution_router.NativeRunContext.create(owner="public", entry="chat", run_id="commit-run")
        async for event in service.run_agent_pipeline(deps=deps, query="问题", thread_id="public:anonymous:t",
                                                       run_id=context.run_id, run_context=context):
            if event.get("type") == "done":
                assert order == ["committed"]
                assert event["persistence_status"] == "saved"
                assert event["response"] == "正文"
                order.append("done")

    asyncio.run(collect())
    assert order == ["committed", "done"]

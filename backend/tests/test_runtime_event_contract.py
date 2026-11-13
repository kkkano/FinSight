"""真实事件与服务交付合同：原文、检查点、取消及提交顺序。"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from copy import deepcopy
from types import SimpleNamespace

import pytest
import pytest_asyncio

from backend.agent_runtime import events as events_module, loop, service
from backend.agent_runtime.events import EventSink
from backend.services.run_context import RunContext
from backend.tests.test_runtime_loop_contract import RAW_ANSWER, ScriptedModel, runtime_environment, text_turn, tool_turn


TERMINALS = {"done", "error", "cancelled"}


@pytest_asyncio.fixture
async def make_pipeline(monkeypatch, runtime_environment):
    opened = []
    monkeypatch.setattr(loop, "financial_tools", lambda: {})
    monkeypatch.setattr(service, "_ACTIVE", {})
    monkeypatch.setattr(service, "_ACTIONS", OrderedDict())

    def create(turns, *, persist=None, after_chunk=None, output_mode=None, initial_seq=0, index_report=None, tools=None):
        monkeypatch.setattr(loop, "financial_tools", lambda: tools or {})
        model = ScriptedModel(turns, after_chunk=after_chunk)
        monkeypatch.setattr(service, "resolve_model", lambda: model.config)
        monkeypatch.setattr(service, "ModelTransport", lambda config: model)
        context = RunContext.create(owner="event-owner", entry="chat", budget_seconds=120)
        context.quota_checker = lambda _owner: None
        saved, attempted, updates, order = [], [], [], []

        async def commit(event):
            attempted.append(deepcopy(event))
            order.append("commit-start")
            result = await persist(event) if persist else {**event, "persistence_status": "saved"}
            saved.append(deepcopy(result))
            order.append("commit-finished")
            return result

        deps = SimpleNamespace(persist_run_event=commit,
            update_session_context=lambda **kwargs: updates.append(kwargs),
            schedule_report_index=index_report or (lambda **_kwargs: True))
        stream = service.run_agent_pipeline(deps=deps, query="协议请求", thread_id="event-session",
            run_id=context.run_id, run_context=context, initial_seq=initial_seq, message_id="server-message",
            output_mode=output_mode)
        opened.append(stream)
        return SimpleNamespace(stream=stream, context=context, model=model, saved=saved, attempted=attempted,
                               updates=updates, order=order)

    yield create
    for stream in opened:
        await stream.aclose()


@pytest.mark.asyncio
async def test_event_sequences_and_checkpoints_keep_exact_model_text(monkeypatch):
    queue, checkpoints, clock = asyncio.Queue(), [], [100.0]
    monkeypatch.setattr(events_module, "time", SimpleNamespace(monotonic=lambda: clock[0]))
    sink = EventSink(queue, run_id="run", session_id="session", message_id="message", initial_seq=7,
                     checkpoint=lambda snapshot: checkpoints.append(snapshot))
    sink.runtime = SimpleNamespace(root_content="", data=SimpleNamespace(artifacts=[]))
    await sink.emit("activity.started", {"activity_id": "read", "title": "读取资料"})
    sink.runtime.root_content = RAW_ANSWER
    clock[0] += 2
    await sink.emit("content.delta", {"block_id": "raw-text", "delta": RAW_ANSWER})
    clock[0] += 2
    await sink.emit("content.block_finished", {"block_id": "raw-text", "finish_reason": "stop",
        "completion_status": "complete", "content_phase": "answer"})
    emitted = [queue.get_nowait() for _ in range(queue.qsize())]
    assert [item["seq"] for item in emitted] == [8, 9, 10]
    assert len({item["event_id"] for item in emitted}) == 3
    assert all(item["schema_version"] == "2" and item["message_id"] == "message" for item in emitted)
    assert emitted[1]["type"] == "token" and emitted[1]["content"] == RAW_ANSWER
    assert [item["committed_seq"] for item in checkpoints] == [8, 9, 10]
    assert checkpoints[-1]["response"] == checkpoints[-1]["blocks"][0]["content"] == RAW_ANSWER
    assert checkpoints[0]["blocks"] == []
    assert "completion_status" not in checkpoints[1]["blocks"][0]


@pytest.mark.asyncio
async def test_checkpoint_failure_has_unique_sequence_and_preserves_raw_snapshot(monkeypatch):
    queue = asyncio.Queue()

    async def failed_checkpoint(_snapshot):
        raise RuntimeError("postgresql://private:password@database.invalid")

    sink = EventSink(queue, run_id="checkpoint-run", session_id="session", checkpoint=failed_checkpoint)
    sink.runtime = SimpleNamespace(root_content=RAW_ANSWER, data=SimpleNamespace(artifacts=[]))
    await sink.emit("content.delta", {"block_id": "raw", "delta": RAW_ANSWER})
    emitted = [queue.get_nowait() for _ in range(queue.qsize())]
    assert [item["seq"] for item in emitted] == [1, 2]
    assert emitted[-1]["type"] == "delivery.persistence_unconfirmed"
    assert "password" not in str(emitted)
    assert sink.snapshot()["response"] == sink.snapshot()["blocks"][0]["content"] == RAW_ANSWER


@pytest.mark.asyncio
async def test_done_waits_for_real_commit_and_keeps_raw_content_in_every_projection(make_pipeline):
    started, release = asyncio.Event(), asyncio.Event()

    async def pending_commit(event):
        started.set()
        await release.wait()
        return {**event, "persistence_status": "saved"}

    run = make_pipeline([text_turn(RAW_ANSWER)], persist=pending_commit, initial_seq=2)
    emitted = []

    async def consume():
        async for event in run.stream:
            if event["type"] == "done":
                assert run.order == ["commit-start", "commit-finished"]
            emitted.append(event)

    task = asyncio.create_task(consume())
    try:
        await asyncio.wait_for(started.wait(), timeout=2)
        assert not any(event["type"] in TERMINALS for event in emitted)
        assert not task.done()
        release.set()
        await asyncio.wait_for(task, timeout=2)
    finally:
        release.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    terminal = [item for item in emitted if item["type"] in TERMINALS]
    assert len(terminal) == len(run.saved) == 1
    assert terminal[0]["type"] == "done" and terminal[0]["persistence_status"] == "saved", {
        key: terminal[0].get(key) for key in ("type", "error_code", "message")}
    assert terminal[0]["response"] == run.saved[0]["response"] == RAW_ANSWER
    assert terminal[0]["blocks"][0]["content"] == RAW_ANSWER
    assert run.updates[0]["response_markdown"] == RAW_ANSWER
    assert [item["seq"] for item in emitted] == list(range(3, 3 + len(emitted)))
    assert run.context.status == "completed"


@pytest.mark.asyncio
async def test_cancellation_after_streaming_keeps_partial_and_publishes_one_terminal(make_pipeline):
    partial = "已经流出的 12.50，h_partial 保留"

    async def cancel_after_first_chunk(turn, index):
        if turn == index == 0:
            asyncio.current_task().cancel()
            await asyncio.sleep(0)

    run = make_pipeline([text_turn(partial)], after_chunk=cancel_after_first_chunk)
    emitted = [event async for event in run.stream]
    terminal = [item for item in emitted if item["type"] in TERMINALS]
    assert len(terminal) == len(run.saved) == 1
    assert terminal[0]["type"] == "cancelled"
    assert terminal[0]["response"] == run.saved[0]["response"] == partial
    assert terminal[0]["blocks"][0]["content"] == partial
    assert terminal[0]["publishable"] is False
    assert run.context.status == "cancelled" and run.context.cancelled.is_set()
    assert not service._ACTIVE


@pytest.mark.asyncio
async def test_closing_stream_cancels_producer_and_commits_partial_once(make_pipeline):
    waiting = asyncio.Event()

    async def hold_after_text(turn, index):
        if turn == index == 0:
            await waiting.wait()

    run = make_pipeline([text_turn(RAW_ANSWER)], after_chunk=hold_after_text)
    emitted = []
    async for event in run.stream:
        emitted.append(event)
        if event["type"] == "token":
            break
    await asyncio.wait_for(run.stream.aclose(), timeout=2)
    assert [event["type"] for event in emitted if event["type"] in TERMINALS] == []
    assert len(run.saved) == 1 and run.saved[0]["type"] == "cancelled"
    assert run.saved[0]["response"] == RAW_ANSWER
    assert run.saved[0]["publishable"] is False
    assert run.context.status == "cancelled" and not service._ACTIVE


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_mode", ["exception", "returned_failure"])
async def test_failed_final_persistence_never_emits_done_or_publishable(make_pipeline, failure_mode):
    async def failed_commit(event):
        if failure_mode == "exception":
            raise RuntimeError("private database failure")
        return {**event, "persistence_status": "failed", "run_status": "persistence_failed",
                "success": False, "publishable": False}

    run = make_pipeline([text_turn(RAW_ANSWER)], persist=failed_commit)
    emitted = [event async for event in run.stream]
    assert len(run.attempted) == 1 and run.attempted[0]["type"] == "done"
    terminal = [item for item in emitted if item["type"] in TERMINALS]
    assert len(terminal) == 1
    assert terminal[0]["type"] == "error"
    assert terminal[0]["publishable"] is False
    assert terminal[0]["run_status"] == run.context.status == "persistence_failed"
    assert terminal[0]["response"] == RAW_ANSWER
    assert "private database" not in str(emitted)


@pytest.mark.asyncio
async def test_report_index_failure_cannot_become_publishable_done(make_pipeline):
    review = {"verdict": "pass", "findings": [], "coverage": []}
    run = make_pipeline([text_turn(RAW_ANSWER), tool_turn(("review", "submit_review", review))],
                        output_mode="investment_report", index_report=lambda **_kwargs: False)
    emitted = [event async for event in run.stream]
    terminal = [item for item in emitted if item["type"] in TERMINALS]
    assert len(terminal) == len(run.saved) == 1
    assert terminal[0]["type"] == "error"
    assert terminal[0]["error_code"] == "report_persistence_failed"
    assert terminal[0]["publishable"] is False
    assert terminal[0]["response"] == RAW_ANSWER
    assert run.context.status == "failed"

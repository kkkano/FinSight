from __future__ import annotations

import asyncio
from threading import Event
from types import SimpleNamespace

import pytest

from backend.llm_config import EndpointConfig, EndpointManager, EndpointRuntime
from backend.services.llm_retry import LLMCallContext, ainvoke_llm, invoke_configured_llm
from backend.services.run_context import RunCancelledError, RunContext, RunDeadlineExceeded, run_context_scope


def manager() -> EndpointManager:
    return EndpointManager(endpoints=[EndpointRuntime(cfg=EndpointConfig(
        "fixture", "openai_compatible", "https://fixture.test/v1", "fixture-key", "fixture-model"
    ))], fingerprint="run-context-fixture")


@pytest.mark.asyncio
async def test_structural_repair_and_slow_call_share_one_deadline():
    run = RunContext.create(owner="alice", entry="chat", budget_seconds=0.2)
    run.quota_checker = lambda _owner: None
    calls = []

    async def invoke(_client, _messages):
        calls.append(run.remaining_seconds)
        if len(calls) == 1:
            await asyncio.sleep(0.05)
            return SimpleNamespace(usage_metadata={"input_tokens": 10, "output_tokens": 5})
        await asyncio.sleep(1)

    with run_context_scope(run):
        for index in range(2):
            call = LLMCallContext.create(stage=f"repair-{index}", max_provider_attempts=1)
            if index == 0:
                await ainvoke_llm(messages=[], context=call, endpoint_manager=manager(),
                                  client_factory=lambda _endpoint: object(), invoke=invoke)
            else:
                with pytest.raises(TimeoutError):
                    await ainvoke_llm(messages=[], context=call, endpoint_manager=manager(),
                                      client_factory=lambda _endpoint: object(), invoke=invoke)
        with pytest.raises(RunDeadlineExceeded):
            run.guard()
    assert len(calls) == 2 and calls[1] < calls[0]
    assert run.usage.call_count == 2
    assert run.usage.total_tokens == 15


@pytest.mark.asyncio
async def test_quota_refusal_prevents_client_construction_and_provider_call():
    run = RunContext.create(owner="alice", entry="prediction")
    calls = []

    def refuse(_owner):
        raise RuntimeError("quota_refused")

    run.quota_checker = refuse
    with run_context_scope(run), pytest.raises(RuntimeError, match="quota_refused"):
        await ainvoke_llm(messages=[], context=LLMCallContext.create(stage="prediction"),
                          endpoint_manager=manager(), client_factory=lambda _endpoint: calls.append("client"),
                          invoke=lambda _client, _messages: calls.append("provider"))
    assert calls == [] and run.usage.call_count == 0


@pytest.mark.asyncio
async def test_cancelled_context_is_shared_with_tool_thread_and_prohibits_new_call():
    run = RunContext.create(owner="alice", entry="chat")
    with run_context_scope(run):
        run.finish("cancelled")
        with pytest.raises(RunCancelledError):
            await asyncio.to_thread(invoke_configured_llm, [], context=LLMCallContext.create(stage="financial_extraction"))
    assert run.usage.call_count == 0


@pytest.mark.asyncio
async def test_sync_extraction_uses_same_owner_usage_and_deadline(monkeypatch):
    from backend.services import llm_retry

    run = RunContext.create(owner="alice", entry="investment_report", budget_seconds=2)
    run.quota_checker = lambda _owner: None
    seen = []

    class Client:
        model_name = "fixture-model"

        def invoke(self, _messages):
            return SimpleNamespace(content="{}", usage_metadata={"input_tokens": 7, "output_tokens": 3})

    def factory(_endpoint, **kwargs):
        seen.append(kwargs["request_timeout"])
        return Client()

    monkeypatch.setattr(llm_retry, "get_endpoint_manager", lambda **_kwargs: manager())
    monkeypatch.setattr(llm_retry, "create_llm_for_endpoint", factory)
    with run_context_scope(run):
        await asyncio.to_thread(invoke_configured_llm, [], context=LLMCallContext.create(
            stage="financial_extraction", agent="disclosure_financial_facts", layer="collection"),
            request_timeout=60, acquire_token=False)
    assert run.usage.user_id == "alice" and run.usage.total_tokens == 10
    assert 0 < seen[0] <= 2
    assert run.usage.summary()["usage_by_attribution"][0]["agent"] == "disclosure_financial_facts"


@pytest.mark.asyncio
async def test_in_flight_sync_completion_after_cancellation_updates_durable_usage(monkeypatch):
    from backend.services import llm_retry

    run = RunContext.create(owner="alice", entry="chat", budget_seconds=2)
    run.quota_checker = lambda _owner: None
    started, release = Event(), Event()
    archived = []

    class Client:
        model_name = "fixture-model"

        def invoke(self, _messages):
            started.set()
            release.wait(1)
            return SimpleNamespace(content="{}", usage_metadata={"input_tokens": 7, "output_tokens": 3})

    async def archive():
        archived.append((run.status, run.usage.summary()))

    monkeypatch.setattr(run, "archive_usage", archive)
    monkeypatch.setattr(llm_retry, "get_endpoint_manager", lambda **_kwargs: manager())
    monkeypatch.setattr(llm_retry, "create_llm_for_endpoint", lambda _endpoint, **_kwargs: Client())
    with run_context_scope(run):
        task = asyncio.create_task(asyncio.to_thread(invoke_configured_llm, [], context=LLMCallContext.create(
            stage="financial_extraction", agent="disclosure_financial_facts", layer="collection"),
            request_timeout=60, acquire_token=False))
        assert await asyncio.to_thread(started.wait, 1)
        run.finish("cancelled")
        release.set()
        await task
    assert archived[0][0] == "cancelled"
    assert archived[0][1]["total_tokens"] == 10
    assert run.usage.call_count == 1


@pytest.mark.asyncio
async def test_deadline_partial_response_is_the_same_persisted_terminal_event(monkeypatch):
    from backend.graph.execution import partial_delivery
    from backend.graph import runner as runner_module
    from backend.services.execution_service import ExecutionDeps, run_graph_pipeline

    run = RunContext.create(owner="alice", entry="chat", budget_seconds=0.03)
    saved = []

    async def slow_graph(*_args, **_kwargs):
        await asyncio.sleep(1)

    async def partial(context):
        assert context is run and context.cancelled.is_set()
        return {"response": "已核验价格 100 USD；增长率尚未取到。", "answer_status": "partial",
                "task_results": [{"status": "partial", "missing_requirements": ["growth"]}]}

    async def persist(payload):
        saved.append(dict(payload))
        return {**payload, "persistence_status": "saved"}

    async def graph_runner():
        return object()

    monkeypatch.setattr(runner_module, "run_graph_traced", slow_graph)
    monkeypatch.setattr(partial_delivery, "build_partial_delivery", partial)
    deps = ExecutionDeps(get_graph_runner=graph_runner, schedule_report_index=lambda **_kwargs: None,
        update_session_context=lambda **_kwargs: None, redact_sensitive_payload=lambda payload: payload,
        is_raw_trace_event=lambda _payload: False, contract_info=lambda: {},
        sse_event_schema_version="chat.sse.v1", persist_run_event=persist)
    events = [event async for event in run_graph_pipeline(deps=deps, query="价格和增长", thread_id="s1",
                                                        user_id="alice", run_context=run)]
    error = next(event for event in events if event.get("type") == "error")
    assert error["response"] == saved[0]["response"]
    assert error["answer_status"] == "partial" and not error["publishable"]
    assert error["task_results"][0]["missing_requirements"] == ["growth"]
    assert run.status == "timed_out" and run.remaining_seconds == 0

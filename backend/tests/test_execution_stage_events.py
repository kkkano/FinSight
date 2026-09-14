# -*- coding: utf-8 -*-
import asyncio
import importlib

import pytest


def _run(coro):
    return asyncio.run(coro)


def test_executor_emits_executing_stage_events(monkeypatch):
    import backend.graph.dag_executor as dag_executor_mod

    events: list[dict] = []

    async def _fake_emit(payload: dict):
        events.append(payload)

    monkeypatch.setattr(dag_executor_mod, "emit_event", _fake_emit)

    artifacts, _trace = _run(
        dag_executor_mod.execute_plan_dag(
            {"steps": []},
            dry_run=True,
            tool_invokers={},
            agent_invokers={},
            cache={},
        )
    )

    assert isinstance(artifacts, dict)
    pipeline_events = [event for event in events if event.get("type") == "pipeline_stage"]
    assert any(event.get("stage") == "executing" and event.get("status") == "start" for event in pipeline_events)
    assert any(event.get("stage") == "executing" and event.get("status") == "done" for event in pipeline_events)


def test_executor_emits_progress_heartbeats_during_agent_step(monkeypatch):
    import backend.graph.dag_executor as dag_executor_mod
    import backend.graph.executor as executor_mod

    monkeypatch.setenv("LANGGRAPH_EXECUTION_PROGRESS_HEARTBEAT_SECONDS", "0.01")
    events: list[dict] = []

    async def _fake_emit(payload: dict):
        events.append(payload)

    async def _slow_agent(_inputs: dict):
        await asyncio.sleep(0.05)
        return {"summary": "done"}

    monkeypatch.setattr(dag_executor_mod, "emit_event", _fake_emit)
    monkeypatch.setattr(executor_mod, "emit_event", _fake_emit)

    artifacts, _trace = _run(
        dag_executor_mod.execute_plan_dag(
            {"steps": [{"id": "s1", "kind": "agent", "name": "news_agent", "inputs": {}}]},
            dry_run=False,
            tool_invokers={},
            agent_invokers={"news_agent": _slow_agent},
            cache={},
        )
    )

    assert artifacts["step_results"]["s1"]["status_reason"] == "done"
    progress_events = [
        event
        for event in events
        if event.get("type") == "pipeline_stage"
        and event.get("stage") == "executing"
        and event.get("status") == "running"
        and isinstance(event.get("progress_percent"), int)
    ]
    assert progress_events
    assert progress_events[0].get("agent") == "news_agent"


def test_executor_emits_cancelled_stage_when_cancel_event_is_set(monkeypatch):
    import backend.graph.dag_executor as dag_executor_mod

    events: list[dict] = []

    async def _fake_emit(payload: dict):
        events.append(payload)

    monkeypatch.setattr(dag_executor_mod, "emit_event", _fake_emit)

    cancel_event = asyncio.Event()
    cancel_event.set()

    async def _run_cancelled():
        with pytest.raises(asyncio.CancelledError):
            await dag_executor_mod.execute_plan_dag(
                {"steps": [{"id": "s1", "kind": "tool", "name": "slow", "inputs": {}}]},
                dry_run=True,
                cancel_event=cancel_event,
                tool_invokers={},
                agent_invokers={},
                cache={},
            )

    _run(_run_cancelled())

    pipeline_events = [event for event in events if event.get("type") == "pipeline_stage"]
    assert any(event.get("stage") == "executing" and event.get("status") == "start" for event in pipeline_events)
    assert any(event.get("stage") == "cancelled" and event.get("status") == "cancelled" for event in pipeline_events)
    assert not any(event.get("stage") == "executing" and event.get("status") == "done" for event in pipeline_events)


def test_synthesize_stub_emits_synthesizing_stage_events(monkeypatch):
    synth_mod = importlib.import_module("backend.graph.nodes.synthesize")

    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "stub")
    events: list[dict] = []

    async def _fake_emit(payload: dict):
        events.append(payload)

    monkeypatch.setattr(synth_mod, "emit_event", _fake_emit)

    state = {
        "query": "AAPL summary",
        "output_mode": "brief",
        "operation": {"name": "qa", "confidence": 0.8, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "artifacts": {"step_results": {}, "evidence_pool": []},
        "trace": {},
    }

    out = _run(synth_mod.synthesize(state))
    assert (out.get("artifacts") or {}).get("render_vars")

    pipeline_events = [event for event in events if event.get("type") == "pipeline_stage"]
    assert any(event.get("stage") == "synthesizing" and event.get("status") == "start" for event in pipeline_events)
    assert any(event.get("stage") == "synthesizing" and event.get("status") == "done" for event in pipeline_events)

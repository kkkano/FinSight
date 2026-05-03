# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import importlib


def _run(coro):
    return asyncio.run(coro)


async def _collect_events(generator):
    events = []
    async for item in generator:
        if isinstance(item, dict) and item.get("type") == "keep-alive":
            continue
        events.append(item)
    return events


def test_run_graph_pipeline_emits_cancelled_trace_when_graph_is_cancelled(monkeypatch):
    execution_service = importlib.import_module("backend.services.execution_service")
    runner_module = importlib.import_module("backend.graph.runner")
    cancellation = importlib.import_module("backend.graph.cancellation")
    seen: dict[str, object] = {}

    async def _cancelled_run_graph_traced(*_args, **_kwargs):
        seen["cancel_event"] = cancellation.get_cancel_event()
        raise asyncio.CancelledError()

    monkeypatch.setattr(runner_module, "run_graph_traced", _cancelled_run_graph_traced)

    async def _fake_get_graph_runner():
        return object()

    deps = execution_service.ExecutionDeps(
        get_graph_runner=_fake_get_graph_runner,
        schedule_report_index=lambda **_kwargs: None,
        update_session_context=lambda **_kwargs: None,
        redact_sensitive_payload=lambda payload: payload,
        is_raw_trace_event=lambda payload: False,
        contract_info=lambda: {"chat_response": "chat.response.v1"},
        sse_event_schema_version="chat.sse.v1",
    )

    events = _run(
        _collect_events(
            execution_service.run_graph_pipeline(
                deps=deps,
                query="AAPL news",
                thread_id="public:user:thread",
                source="cancel-test",
            )
        )
    )

    cancelled = [event for event in events if event.get("stage") == "cancelled"]
    assert cancelled
    assert cancelled[0]["type"] == "trace"
    assert cancelled[0]["status"] == "cancelled"
    assert any(
        event.get("type") == "pipeline_stage"
        and event.get("stage") == "cancelled"
        and event.get("status") == "cancelled"
        for event in events
    )
    assert seen.get("cancel_event") is not None
    assert seen["cancel_event"].is_set() is True

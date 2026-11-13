# -*- coding: utf-8 -*-
import asyncio
import importlib


def _run(coro):
    return asyncio.run(coro)


async def _collect_events(generator):
    items = []
    async for item in generator:
        if isinstance(item, dict) and item.get("type") == "keep-alive":
            continue
        items.append(item)
    return items


def test_run_graph_pipeline_emits_quality_blocked_and_skips_index(monkeypatch):
    execution_service = importlib.import_module("backend.services.execution_service")
    runner_module = importlib.import_module("backend.graph.runner")
    report_builder_module = importlib.import_module("backend.graph.report_builder")

    async def _fake_run_graph_traced(
        _runner,
        *,
        thread_id: str,
        query: str,
        ui_context=None,
        output_mode=None,
        strict_selection=None,
    ):
        return {
            "thread_id": thread_id,
            "query": query,
            "output_mode": output_mode or "investment_report",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
            "trace": {},
            "artifacts": {"draft_markdown": "blocked markdown"},
        }

    monkeypatch.setattr(runner_module, "run_graph_traced", _fake_run_graph_traced)
    monkeypatch.setattr(
        report_builder_module,
        "build_report_payload",
        lambda **kwargs: {
            "report_id": "rpt-block-1",
            "ticker": "AAPL",
            "title": "blocked report",
            "summary": "blocked",
            "generated_at": "2026-02-20T00:00:00Z",
            "citations": [],
            "meta": {},
            "report_quality": {
                "state": "block",
                "reasons": [
                    {
                        "code": "EVIDENCE_COVERAGE_BELOW_MIN",
                        "severity": "block",
                        "metric": "coverage",
                        "actual": 0.2,
                        "threshold": 0.8,
                        "message": "coverage too low",
                    }
                ],
            },
        },
    )

    indexed: list[dict] = []
    updated_context: list[dict] = []

    async def _fake_get_graph_runner():
        return object()

    deps = execution_service.ExecutionDeps(
        get_graph_runner=_fake_get_graph_runner,
        schedule_report_index=lambda **kwargs: indexed.append(kwargs),
        update_session_context=lambda **kwargs: updated_context.append(kwargs),
        redact_sensitive_payload=lambda payload: payload,
        is_raw_trace_event=lambda payload: False,
        contract_info=lambda: {"chat_response": "chat.response.v1"},
        sse_event_schema_version="chat.sse.v1",
    )

    events = _run(
        _collect_events(
            execution_service.run_graph_pipeline(
                deps=deps,
                query="生成 AAPL 投资报告",
                thread_id="tenant:user:thread",
                user_id="user",
                output_mode="investment_report",
                source="execute_test",
            )
        )
    )

    assert not indexed, "quality-blocked previews must never enter the report index"
    assert updated_context, "chat context should still be updated for conversation continuity"

    blocked_events = [event for event in events if isinstance(event, dict) and event.get("type") == "quality_blocked"]
    assert blocked_events, "SSE stream should emit quality_blocked"
    assert blocked_events[0].get("publishable") is False
    assert "EVIDENCE_COVERAGE_BELOW_MIN" in (blocked_events[0].get("blocked_reason_codes") or [])
    assert blocked_events[0].get("blocked_report_available") is True
    assert blocked_events[0].get("allow_continue_when_blocked") is True
    assert blocked_events[0].get("soft_blocked") is True

    pipeline_events = [event for event in events if isinstance(event, dict) and event.get("type") == "pipeline_stage"]
    assert any(
        event.get("stage") == "done" and event.get("status") == "done"
        for event in pipeline_events
    )

    done_events = [event for event in events if isinstance(event, dict) and event.get("type") == "done"]
    assert done_events, "pipeline should still emit done"
    done = done_events[0]
    assert done.get("quality_blocked") is True
    assert done.get("publishable") is False
    assert done.get("failure_kind") == "quality_gate"
    assert done.get("soft_blocked") is True
    assert done.get("response") != "", "soft-blocked should preserve markdown response"
    assert done.get("report") is None
    assert isinstance(done.get("blocked_report"), dict)
    assert done.get("allow_continue_when_blocked") is True

# -*- coding: utf-8 -*-
"""P1-4: 执行失败 vs 质量拦截区分

报告构建崩溃（执行失败）时，用户必须看到真实的失败原因，
而不是误导性的"质量门禁拦截"提示。

- 执行失败（report build 崩溃）→ quality_blocked 事件带 failure_kind="execution_error" + 真实错误信息
- 质量拦截（正常门控）→ failure_kind="quality_gate"
"""
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


def _make_deps(execution_service, indexed, updated_context, runner_factory):
    return execution_service.ExecutionDeps(
        get_graph_runner=runner_factory,
        schedule_report_index=lambda **kwargs: indexed.append(kwargs),
        update_session_context=lambda **kwargs: updated_context.append(kwargs),
        redact_sensitive_payload=lambda payload: payload,
        is_raw_trace_event=lambda payload: False,
        contract_info=lambda: {"chat_response": "chat.response.v1"},
        sse_event_schema_version="chat.sse.v1",
    )


def test_report_build_crash_is_reported_as_execution_error(monkeypatch):
    """P1-4: build_report_payload 抛异常 → 事件标记为执行失败，不是质量拦截"""
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
            "artifacts": {"draft_markdown": "partial markdown content"},
        }

    def _crashing_build_report(**kwargs):
        raise RuntimeError("postgresql://user:password@db.example/finsight?token=secret")

    monkeypatch.setattr(runner_module, "run_graph_traced", _fake_run_graph_traced)
    monkeypatch.setattr(report_builder_module, "build_report_payload", _crashing_build_report)

    indexed: list[dict] = []
    updated_context: list[dict] = []

    async def _fake_get_graph_runner():
        return object()

    deps = _make_deps(execution_service, indexed, updated_context, _fake_get_graph_runner)

    events = _run(
        _collect_events(
            execution_service.run_graph_pipeline(
                deps=deps,
                query="生成 AAPL 投资报告",
                thread_id="tenant:user:thread",
                output_mode="investment_report",
                source="execute_test",
            )
        )
    )

    blocked_events = [
        event for event in events
        if isinstance(event, dict) and event.get("type") == "quality_blocked"
    ]
    assert blocked_events, "execution failure should still emit a blocking event"

    blocked = blocked_events[0]
    # 核心断言：必须标记为执行失败，不能伪装成质量拦截
    assert blocked.get("failure_kind") == "execution_error", (
        f"expected failure_kind=execution_error, got {blocked.get('failure_kind')!r}"
    )
    # Internal exception details stay in logs; the client receives a stable code.
    assert blocked.get("failure_detail") is None
    assert blocked.get("code") == "report_build_failed"
    assert "password" not in str(blocked).lower()
    assert "postgresql://" not in str(blocked).lower()
    # message 不能是误导性的质量门禁文案
    assert "quality gate" not in str(blocked.get("message") or "").lower()
    done = next(event for event in events if isinstance(event, dict) and event.get("type") == "done")
    assert done.get("failure_kind") == "execution_error"
    assert done.get("quality_blocked") is False
    assert done.get("publishable") is False
    assert done.get("report") is None


def test_normal_quality_block_is_reported_as_quality_gate(monkeypatch):
    """P1-4: 正常质量门控拦截 → failure_kind="quality_gate"（与执行失败区分）"""
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

    deps = _make_deps(execution_service, indexed, updated_context, _fake_get_graph_runner)

    events = _run(
        _collect_events(
            execution_service.run_graph_pipeline(
                deps=deps,
                query="生成 AAPL 投资报告",
                thread_id="tenant:user:thread",
                output_mode="investment_report",
                source="execute_test",
            )
        )
    )

    blocked_events = [
        event for event in events
        if isinstance(event, dict) and event.get("type") == "quality_blocked"
    ]
    assert blocked_events, "quality gate should emit quality_blocked"

    blocked = blocked_events[0]
    assert blocked.get("failure_kind") == "quality_gate"
    assert blocked.get("failure_detail") is None
    assert blocked.get("publishable") is False
    assert indexed == []


def test_report_persistence_failure_is_not_claimed_as_archived(monkeypatch):
    execution_service = importlib.import_module("backend.services.execution_service")
    runner_module = importlib.import_module("backend.graph.runner")
    report_builder_module = importlib.import_module("backend.graph.report_builder")

    async def _fake_run_graph_traced(_runner, *, thread_id, query, ui_context=None, output_mode=None, strict_selection=None):
        return {
            "thread_id": thread_id,
            "query": query,
            "output_mode": output_mode or "investment_report",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
            "trace": {},
            "artifacts": {"draft_markdown": "# Private preview"},
        }

    monkeypatch.setattr(runner_module, "run_graph_traced", _fake_run_graph_traced)
    monkeypatch.setattr(
        report_builder_module,
        "build_report_payload",
        lambda **_kwargs: {
            "report_id": "rpt-persist-fail",
            "ticker": "AAPL",
            "title": "AAPL report",
            "citations": [],
            "report_quality": {"state": "pass", "reasons": []},
        },
    )
    monkeypatch.setattr(
        execution_service,
        "_apply_quality_gate",
        lambda **_kwargs: ({"state": "pass", "reasons": []}, False),
    )

    async def failing_persist(**_kwargs):
        raise RuntimeError("postgresql://user:password@db.example/finsight")

    async def _fake_get_graph_runner():
        return object()

    deps = execution_service.ExecutionDeps(
        get_graph_runner=_fake_get_graph_runner,
        schedule_report_index=failing_persist,
        update_session_context=lambda **_kwargs: None,
        redact_sensitive_payload=lambda payload: payload,
        is_raw_trace_event=lambda _payload: False,
        contract_info=lambda: {"chat_response": "chat.response.v1"},
        sse_event_schema_version="chat.sse.v1",
    )
    events = _run(
        _collect_events(
            execution_service.run_graph_pipeline(
                deps=deps,
                query="AAPL private report",
                thread_id="public:user-a:thread",
                user_id="user-a",
                output_mode="investment_report",
                source="execute_test",
            )
        )
    )

    persistence_events = [
        event for event in events
        if isinstance(event, dict)
        and event.get("type") == "pipeline_stage"
        and event.get("stage") == "persistence"
    ]
    assert persistence_events
    assert persistence_events[0]["error_code"] == "report_persistence_failed"
    assert "password" not in str(persistence_events[0]).lower()
    assert "postgresql://" not in str(persistence_events[0]).lower()
    done = next(event for event in events if isinstance(event, dict) and event.get("type") == "done")
    assert done["archived"] is False
    assert done["publishable"] is False
    assert done["failure_kind"] == "persistence_error"
    assert done["report"] is None
    assert isinstance(done["blocked_report"], dict)


def test_async_report_index_is_awaited_before_done(monkeypatch):
    execution_service = importlib.import_module("backend.services.execution_service")
    runner_module = importlib.import_module("backend.graph.runner")
    report_builder_module = importlib.import_module("backend.graph.report_builder")
    order: list[str] = []

    async def _fake_run_graph_traced(_runner, *, thread_id, query, ui_context=None, output_mode=None, strict_selection=None):
        return {
            "thread_id": thread_id,
            "query": query,
            "output_mode": output_mode or "investment_report",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
            "trace": {},
            "artifacts": {"draft_markdown": "# Persisted"},
        }

    monkeypatch.setattr(runner_module, "run_graph_traced", _fake_run_graph_traced)
    monkeypatch.setattr(
        report_builder_module,
        "build_report_payload",
        lambda **_kwargs: {"report_id": "rpt-persisted", "ticker": "AAPL", "citations": [], "report_quality": {"state": "pass", "reasons": []}},
    )
    monkeypatch.setattr(execution_service, "_apply_quality_gate", lambda **_kwargs: ({"state": "pass", "reasons": []}, False))

    async def persist(**_kwargs):
        await asyncio.sleep(0)
        order.append("persisted")
        return True

    async def _fake_get_graph_runner():
        return object()

    deps = execution_service.ExecutionDeps(
        get_graph_runner=_fake_get_graph_runner,
        schedule_report_index=persist,
        update_session_context=lambda **_kwargs: None,
        redact_sensitive_payload=lambda payload: payload,
        is_raw_trace_event=lambda _payload: False,
        contract_info=lambda: {"chat_response": "chat.response.v1"},
        sse_event_schema_version="chat.sse.v1",
    )
    events = _run(_collect_events(execution_service.run_graph_pipeline(
        deps=deps,
        query="AAPL report",
        thread_id="public:user-a:thread",
        user_id="user-a",
        output_mode="investment_report",
        source="execute_test",
    )))
    done = next(event for event in events if isinstance(event, dict) and event.get("type") == "done")
    assert order == ["persisted"]
    assert done["archived"] is True
    assert done["publishable"] is True

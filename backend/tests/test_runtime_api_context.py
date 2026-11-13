"""原生预算、结构授权和公开窗口元数据的跨层合同。"""
from collections import OrderedDict
import json
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
import pytest
from pydantic import ValidationError

from backend.api.execution_router import ExecuteRequest, NativeRunContext, _request_ui_context
from backend.api.schemas import ChatContext
from backend.config.settings import clear_settings_caches


def test_review_revision_is_explicit_structured_context_and_binds_resume_identity():
    revision = {"source_message_id": "assistant:prior", "source_run_id": "prior", "review_id": "reviewer_id",
                "answer": "原文 42。", "findings": [{"quote": "原文 42。", "issue": "核对", "evidence": "[1]", "suggestion": "重新核对"}],
                "coverage": [{"requirement": "说明价格", "met": True}]}
    request = ExecuteRequest(query="任意用户文字", resume_from_run_id="prior", review_revision=revision)
    assert _request_ui_context(request, "owner")["review_revision"] == revision
    ordinary = ExecuteRequest(query="按核查意见修订")
    assert "review_revision" not in _request_ui_context(ordinary, "owner")
    with pytest.raises(ValidationError, match="review_parent_mismatch"):
        ExecuteRequest(query="任意用户文字", resume_from_run_id="other", review_revision=revision)
    with pytest.raises(ValidationError):
        ExecuteRequest(query="任意用户文字", resume_from_run_id="prior",
                       review_revision={**revision, "coverage": [{"requirement": "说明价格", "met": "false"}]})


@pytest.fixture
def runtime_client(monkeypatch):
    from backend.agent_runtime import service
    from backend.api import execution_router, session_context
    from backend.api.stream_replay import ReplayBuffer
    from backend.services.run_context import current_run_context

    calls = {"preflight": [], "pipeline": []}

    async def preflight(context):
        assert current_run_context() is context
        calls["preflight"].append(context)

    async def pipeline(**kwargs):
        calls["pipeline"].append(kwargs)
        base = {"schema_version": "2", "run_id": kwargs["run_id"], "session_id": kwargs["thread_id"]}
        yield {**base, "seq": kwargs["initial_seq"] + 1, "type": "run.accepted",
               "payload": {"runtime": "agent_runtime", "status": "running"}}
        yield {**base, "seq": kwargs["initial_seq"] + 2, "type": "done", "response": "研究结果",
               "run_status": "completed", "success": True, "publishable": True}

    monkeypatch.setattr(service, "cached_model_capability", lambda: None)
    monkeypatch.setattr(service, "preflight", preflight)
    monkeypatch.setattr(service, "run_agent_pipeline", pipeline)
    monkeypatch.setattr(execution_router, "_store_for_user", lambda _owner: None)
    monkeypatch.setattr(execution_router, "_enforce_user_quota", lambda request: request.state.user_id)
    monkeypatch.setattr(execution_router, "replay_buffer", ReplayBuffer())
    monkeypatch.setattr(execution_router, "_RUN_OWNERS", OrderedDict())
    monkeypatch.setattr(execution_router, "_STREAM_TASKS_BY_RUN", {})
    app = FastAPI()

    @app.middleware("http")
    async def owner(request: Request, call_next):
        request.state.user_id = request.headers.get("x-test-user", "runtime-owner")
        return await call_next(request)

    app.include_router(execution_router.create_execution_router(execution_router.ExecutionRouterDeps(
        resolve_thread_id=session_context._resolve_thread_id,
        schedule_report_index=lambda **_kwargs: None,
        update_session_context=lambda **_kwargs: None,
    )))
    with TestClient(app) as client:
        yield client, calls, service


def _stream_events(response):
    return [json.loads(line[6:]) for line in response.text.splitlines() if line.startswith("data: ")]


@pytest.mark.parametrize("retired_value", ["legacy", "agent2", "invalid-runtime"])
def test_execute_uses_single_runtime_and_keeps_preflight_sequence(runtime_client, monkeypatch, retired_value):
    monkeypatch.setenv("FINSIGHT_RESEARCH_RUNTIME", retired_value)
    client, calls, _service = runtime_client
    response = client.post("/api/execute", json={"query": "协议请求", "run_id": "single-runtime",
        "client_assistant_message_id": "assistant-identity", "output_mode": "brief"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = _stream_events(response)
    assert [event["type"] for event in events] == [
        "activity.started", "activity.finished", "run.accepted", "done"]
    assert [event["seq"] for event in events] == [1, 2, 3, 4]
    assert all(event["run_id"] == "single-runtime" for event in events)
    assert events[-1]["persistence_status"] == "ephemeral"
    assert len(calls["pipeline"]) == len(calls["preflight"]) == 1
    arguments = calls["pipeline"][0]
    assert arguments["run_context"] is calls["preflight"][0]
    assert isinstance(arguments["run_context"], NativeRunContext)
    assert arguments["run_context"].owner == "runtime-owner"
    assert arguments["run_context"].entry == "brief"
    assert arguments["message_id"] == "assistant-identity"


def test_cached_capability_skips_probe_without_changing_pipeline(runtime_client, monkeypatch):
    client, calls, service = runtime_client
    monkeypatch.setattr(service, "cached_model_capability", lambda: {"tool_calling": True})
    response = client.post("/api/execute", json={"query": "协议请求", "run_id": "cached-capability"})
    events = _stream_events(response)
    assert [event["type"] for event in events] == ["run.accepted", "done"]
    assert [event["seq"] for event in events] == [1, 2]
    assert calls["preflight"] == []
    assert len(calls["pipeline"]) == 1


def test_failed_preflight_is_terminal_sse_and_does_not_start_runtime(runtime_client, monkeypatch):
    client, calls, service = runtime_client

    async def unavailable(context):
        calls["preflight"].append(context)
        raise HTTPException(503, detail={"code": "model_probe_timeout", "message": "模型暂时不可用"})

    monkeypatch.setattr(service, "preflight", unavailable)
    response = client.post("/api/execute", json={"query": "协议请求", "run_id": "failed-preflight"})
    assert response.status_code == 200
    events = _stream_events(response)
    assert [event["type"] for event in events] == ["activity.started", "activity.failed", "error"]
    assert [event["seq"] for event in events] == [1, 2, 3]
    assert events[-1]["error_code"] == "model_probe_timeout"
    assert events[-1]["publishable"] is False
    assert events[-1]["persistence_status"] == "ephemeral"
    assert calls["preflight"][0].status == "failed"
    assert calls["pipeline"] == []


def test_instruction_and_action_requests_keep_owner_and_hash_binding(runtime_client, monkeypatch):
    client, _calls, service = runtime_client
    client.post("/api/execute", json={"query": "协议请求", "run_id": "owned-runtime"})
    forwarded = []

    def instruction(*arguments):
        forwarded.append(("instruction", arguments))
        return {"accepted": True}

    async def confirm(*arguments):
        forwarded.append(("action", arguments))
        return {"confirmed": True}

    monkeypatch.setattr(service, "add_instruction", instruction)
    monkeypatch.setattr(service, "confirm_action", confirm)
    paths = ["/api/execute/runs/owned-runtime/instructions",
             "/api/execute/runs/owned-runtime/actions/action-id/confirm"]
    payloads = [{"instruction": "补充研究要求", "instruction_id": "instruction-id"},
                {"payload_hash": "a" * 64, "confirmed": True}]
    for path, payload in zip(paths, payloads):
        assert client.post(path, json=payload, headers={"x-test-user": "another-owner"}).status_code == 404
        assert client.post(path, json=payload).status_code == 200
    assert forwarded == [
        ("instruction", ("runtime-owner", "owned-runtime", "补充研究要求", "instruction-id")),
        ("action", ("runtime-owner", "owned-runtime", "action-id", "a" * 64, True)),
    ]


def test_ui_structured_permissions_are_preserved_and_default_to_confirmation():
    request = ExecuteRequest(query="协议请求", context=ChatContext(watchlist_auto_confirm=True,
                            show_provider_reasoning=False), show_provider_reasoning=True)
    context = _request_ui_context(request, "owner-fixture")
    assert context["watchlist_auto_confirm"] is True
    assert context["show_provider_reasoning"] is False
    defaults = _request_ui_context(ExecuteRequest(query="协议请求"), "owner-fixture")
    assert defaults["watchlist_auto_confirm"] is False
    assert defaults["show_provider_reasoning"] is False


def test_dashboard_handoff_keeps_explicit_metric_range_and_refs_as_data():
    payload = {"active_symbol": "AAPL", "selected_metric": {"id": "gross_margin", "value": 0.42, "unit": "ratio"},
               "time_range": {"period": "1y"}, "data_refs": ["dashboard-fixture"]}
    request = ExecuteRequest(query="协议请求", context=ChatContext.model_validate(payload))
    context = _request_ui_context(request, "fixture-owner")
    assert context["selected_metric"]["value"] == 0.42
    assert context["time_range"] == {"period": "1y"}
    assert context["data_refs"] == ["dashboard-fixture"]
    assert context["watchlist_auto_confirm"] is False


@pytest.mark.parametrize("value", ["true", 1, "yes"])
def test_watchlist_permission_requires_an_actual_json_boolean(value):
    with pytest.raises(ValidationError):
        ChatContext(watchlist_auto_confirm=value)


def test_native_report_promotion_uses_new_budget_without_restarting_clock(monkeypatch):
    monkeypatch.setenv("FINSIGHT_RUN_TIMEOUT_REPORT_SECONDS", "420")
    monkeypatch.setenv("LANGGRAPH_EXECUTION_TIMEOUT_REPORT_SECONDS", "300")
    clear_settings_caches()
    context = NativeRunContext.create(owner="fixture", entry="chat", budget_seconds=20)
    start = context.started_monotonic
    context.select_entry("investment_report")
    assert context.started_monotonic == start
    assert context.deadline == pytest.approx(start + 420)
    clear_settings_caches()


def test_native_brief_budget_is_distinct_from_chat_and_uses_original_start(monkeypatch):
    monkeypatch.setenv("FINSIGHT_RUN_TIMEOUT_BRIEF_SECONDS", "120")
    monkeypatch.setenv("FINSIGHT_RUN_TIMEOUT_SECONDS", "180")
    clear_settings_caches()
    context = NativeRunContext.create(owner="fixture", entry="chat", budget_seconds=180)
    context.select_entry("brief")
    assert context.entry == "brief"
    assert context.deadline == pytest.approx(context.started_monotonic + 120)
    clear_settings_caches()


def test_public_track_record_echoes_actual_filter_window_without_changing_statistics(monkeypatch):
    from backend.api import prediction_router
    payload = {"metadata": {"strategy_version": "forecast-v1", "horizon_sessions": 5},
               "stats": {"settled": 7}}
    calls = []
    monkeypatch.setattr(prediction_router, "get_prediction_store", lambda: SimpleNamespace())
    monkeypatch.setattr(prediction_router, "enabled", lambda: True)
    monkeypatch.setattr(prediction_router, "track_record_view", lambda store, **kwargs: calls.append(kwargs) or payload)
    result = prediction_router.track_record(limit=50, offset=0, ticker=None, status=None,
                                           prediction_type=None, days=84)
    assert calls[0]["days"] == 84
    assert result["metadata"]["window_days"] == 84
    assert result["stats"] is payload["stats"]
    assert "window_days" not in payload["metadata"]

# -*- coding: utf-8 -*-
import importlib
import os
import json

from fastapi.testclient import TestClient

from backend.contracts import CHAT_RESPONSE_SCHEMA_VERSION, SSE_EVENT_SCHEMA_VERSION


def _load_app():
    import backend.api.main as main
    importlib.reload(main)
    return main.app


def test_chat_supervisor_uses_langgraph_stub_when_enabled():
    app = _load_app()
    client = TestClient(app)

    resp = client.post("/chat/supervisor", json={"query": "分析影响"})
    assert resp.status_code == 200
    data = resp.json()

    assert data.get("schema_version") == CHAT_RESPONSE_SCHEMA_VERSION
    assert isinstance(data.get("contracts"), dict)
    assert data.get("contracts", {}).get("chat_response") == CHAT_RESPONSE_SCHEMA_VERSION
    assert data.get("classification", {}).get("method") == "langgraph"
    response = data.get("response") or ""
    assert isinstance(response, str) and response.strip()
    assert "待实现" not in response, "LangGraph path should not return placeholder output"


def test_chat_supervisor_stream_uses_langgraph_stub_when_enabled():
    app = _load_app()
    client = TestClient(app)

    resp = client.post("/chat/supervisor/stream", json={"query": "hello"})
    assert resp.status_code == 200
    body = resp.text
    assert "\"type\": \"token\"" in body
    assert "\"type\": \"done\"" in body
    assert f"\"schema_version\": \"{SSE_EVENT_SCHEMA_VERSION}\"" in body


def test_chat_supervisor_stream_respects_trace_raw_override_off():
    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/chat/supervisor/stream",
        json={
            "query": "分析影响",
            "options": {"trace_raw_override": "off"},
        },
    )
    assert resp.status_code == 200

    events = []
    for line in resp.text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[len("data: ") :])
        events.append(payload)

    assert events, "stream should include essential events"
    # startup thinking is emitted before override filter path; node-level thinking should be filtered.
    thinking_stages = [str(item.get("stage", "")) for item in events if item.get("type") == "thinking"]
    assert set(thinking_stages).issubset({"langgraph_start"})
    assert any(item.get("type") == "token" for item in events)
    assert any(item.get("type") == "done" for item in events)


def test_chat_supervisor_output_mode_option_overrides_default():
    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/chat/supervisor",
        json={
            "query": "分析影响",
            "options": {"output_mode": "investment_report", "strict_selection": False},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("graph", {}).get("output_mode") == "investment_report"


def test_chat_supervisor_default_output_mode_is_brief_and_trace_present():
    app = _load_app()
    client = TestClient(app)

    resp = client.post("/chat/supervisor", json={"query": "分析影响"})
    assert resp.status_code == 200
    data = resp.json()

    assert data.get("graph", {}).get("output_mode") == "brief"

    trace = data.get("graph", {}).get("trace")
    assert isinstance(trace, dict)
    assert trace.get("routing_chain") == ["langgraph"]
    spans = trace.get("spans")
    assert isinstance(spans, list) and spans, "trace.spans should exist in LangGraph stub path"
    assert any(span.get("node") == "decide_output_mode" for span in spans)


def test_chat_supervisor_trace_planner_runtime_contains_variant_field():
    app = _load_app()
    client = TestClient(app)

    resp = client.post("/chat/supervisor", json={"query": "分析苹果影响"})
    assert resp.status_code == 200
    data = resp.json()

    trace = (data.get("graph") or {}).get("trace") or {}
    planner_runtime = trace.get("planner_runtime") or {}
    assert planner_runtime.get("variant") in {"A", "B"}


def test_chat_supervisor_stream_done_event_contains_graph_output_mode():
    app = _load_app()
    client = TestClient(app)

    resp = client.post("/chat/supervisor/stream", json={"query": "分析影响"})
    assert resp.status_code == 200

    events = []
    for line in resp.text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[len("data: ") :])
        events.append(payload)

    assert any(e.get("type") == "thinking" and e.get("stage") == "langgraph_start" for e in events)
    assert any(
        e.get("type") == "thinking" and str(e.get("stage", "")).startswith("langgraph_build_initial_state_")
        for e in events
    )

    done = next((e for e in reversed(events) if e.get("type") == "done"), None)
    assert done is not None
    assert done.get("schema_version") == SSE_EVENT_SCHEMA_VERSION
    assert isinstance(done.get("contracts"), dict)
    assert done.get("graph", {}).get("output_mode") == "brief"
    trace = done.get("graph", {}).get("trace")
    assert isinstance(trace, dict)
    assert trace.get("routing_chain") == ["langgraph"]


def test_chat_supervisor_returns_report_in_investment_report_mode():
    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/chat/supervisor",
        json={
            "query": "分析苹果公司，生成投资报告",
            "options": {"output_mode": "investment_report", "strict_selection": False},
            "context": {"active_symbol": "AAPL", "view": "chat"},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("graph", {}).get("output_mode") == "investment_report"

    report = data.get("report")
    assert isinstance(report, dict)
    assert report.get("report_id")
    assert report.get("title")
    assert isinstance(report.get("sections"), list) and report.get("sections")
    assert isinstance(report.get("citations"), list)
    synthesis = report.get("synthesis_report") or ""
    assert isinstance(synthesis, str)
    from backend.graph import report_builder as report_builder_mod

    # No longer require 2000 chars — appendix padding was removed in favour of
    # real agent content.  A healthy stub report produces ~300-600 content chars.
    assert report_builder_mod._count_content_chars(synthesis) >= 200


def test_chat_supervisor_stream_done_event_contains_report_in_investment_report_mode():
    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/chat/supervisor/stream",
        json={
            "query": "对比 AAPL 和 MSFT，生成投资报告",
            "options": {"output_mode": "investment_report", "strict_selection": False},
        },
    )
    assert resp.status_code == 200

    done = None
    for line in resp.text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[len("data: ") :])
        if payload.get("type") == "done":
            done = payload
            break

    assert done is not None
    report = done.get("report")
    assert isinstance(report, dict)
    assert "synthesis_report" in report
    assert isinstance(report.get("sections"), list)


def test_chat_supervisor_stream_executor_step_inputs_are_structured_json_object():
    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/chat/supervisor/stream",
        json={
            "query": "详细分析苹果公司，生成投资报告",
            "options": {"output_mode": "investment_report", "strict_selection": False},
            "context": {"active_symbol": "AAPL", "view": "chat"},
        },
    )
    assert resp.status_code == 200

    events = []
    for line in resp.text.splitlines():
        if not line.startswith("data: "):
            continue
        payload = json.loads(line[len("data: ") :])
        events.append(payload)

    step_start = next(
        (
            e
            for e in events
            if e.get("type") == "thinking" and e.get("stage") == "executor_step_start"
        ),
        None,
    )
    assert step_start is not None, "expected executor_step_start in stream events"
    result = step_start.get("result")
    assert isinstance(result, dict)
    assert isinstance(result.get("inputs"), dict), "inputs must be an object, not a JSON string"


def test_chat_supervisor_investment_report_with_news_selection_renders_news_report_card():
    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/chat/supervisor",
        json={
            "query": "分析这条新闻对股价的影响，生成研报",
            "options": {"output_mode": "investment_report", "strict_selection": False},
            "context": {
                "active_symbol": "AAPL",
                "view": "chat",
                "selection": {
                    "type": "news",
                    "id": "n1",
                    "title": "Test News",
                    "url": "https://example.com/news",
                    "source": "unit-test",
                    "ts": "2026-02-04",
                    "snippet": "snippet",
                },
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    report = data.get("report")
    assert isinstance(report, dict)
    assert "新闻事件研报" in str(report.get("title") or "")
    assert "AAPL" in str(report.get("ticker") or "")


def test_chat_supervisor_investment_report_with_doc_selection_renders_doc_report_card():
    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/chat/supervisor",
        json={
            "query": "研读这个文档，生成研报",
            "options": {"output_mode": "investment_report", "strict_selection": False},
            "context": {
                "active_symbol": "AAPL",
                "view": "chat",
                "selection": {
                    "type": "doc",
                    "id": "d1",
                    "title": "Test Doc",
                    "url": "https://example.com/doc",
                    "source": "unit-test",
                    "ts": "2026-02-04",
                    "snippet": "snippet",
                },
            },
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    report = data.get("report")
    assert isinstance(report, dict)
    assert "文档研读报告" in str(report.get("title") or "")
    assert "AAPL" in str(report.get("ticker") or "")

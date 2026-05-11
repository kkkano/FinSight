# -*- coding: utf-8 -*-
import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_execute_plan_stub_preserves_context_artifacts_across_execution(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "false")

    from backend.graph.nodes.execute_plan_stub import execute_plan_stub

    state = {
        "query": "give recent news links",
        "plan_ir": {
            "goal": "x",
            "subject": {"subject_type": "company", "tickers": ["TSLA"], "selection_ids": [], "selection_types": [], "selection_payload": []},
            "output_mode": "chat",
            "steps": [],
            "tasks": [{"id": "task_1", "subject_type": "company", "tickers": ["TSLA"], "operation": "fetch"}],
            "budget": {"max_rounds": 1, "max_tools": 0},
            "synthesis": {"style": "concise", "sections": []},
        },
        "policy": {"allowed_tools": [], "budget": {"max_rounds": 1, "max_tools": 0}},
        "subject": {"subject_type": "company", "tickers": ["TSLA"], "selection_payload": []},
        "artifacts": {
            "alert_markdown": "Created alert for TSLA at 180.",
            "conversation_decision": {"lane": "source_grounded_answer"},
            "draft_markdown": "stale pre-execution draft",
            "step_results": {"stale": {"output": "old"}},
        },
        "trace": {},
    }

    out = _run(execute_plan_stub(state))
    artifacts = out.get("artifacts") or {}

    assert artifacts.get("alert_markdown") == "Created alert for TSLA at 180."
    assert artifacts.get("conversation_decision") == {"lane": "source_grounded_answer"}
    assert "draft_markdown" not in artifacts
    assert artifacts.get("step_results") == {}


def test_failed_url_fetch_goes_to_tool_diagnostics_not_evidence(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "true")

    class _FakeTool:
        def __init__(self, name: str):
            self.name = name

        def invoke(self, _inputs):
            return {
                "status": "failed",
                "error": "403 Forbidden",
                "url": "https://example.com/blocked",
                "content": "",
            }

    import backend.langchain_tools as tools_mod

    monkeypatch.setattr(tools_mod, "get_tool_by_name", lambda name: _FakeTool(name))

    from backend.graph.nodes.execute_plan_stub import execute_plan_stub

    state = {
        "query": "Read https://example.com/blocked",
        "reply_contract": {
            "lane": "source_grounded_answer",
            "citation_policy": "must_cite_or_disclose_unavailable",
        },
        "plan_ir": {
            "goal": "x",
            "subject": {"subject_type": "research_doc", "tickers": [], "selection_ids": [], "selection_types": [], "selection_payload": []},
            "output_mode": "chat",
            "steps": [
                {
                    "id": "s1",
                    "kind": "tool",
                    "name": "fetch_url_content",
                    "inputs": {"url": "https://example.com/blocked"},
                    "task_ids": ["task_1"],
                    "task_id": "task_1",
                    "why": "unit",
                    "optional": False,
                }
            ],
            "tasks": [{"id": "task_1", "subject_type": "research_doc", "operation": "qa"}],
            "budget": {"max_rounds": 1, "max_tools": 1},
            "synthesis": {"style": "concise", "sections": []},
        },
        "policy": {"allowed_tools": ["fetch_url_content"], "budget": {"max_rounds": 1, "max_tools": 1}},
        "subject": {"subject_type": "research_doc", "selection_payload": []},
        "trace": {},
    }

    out = _run(execute_plan_stub(state))
    artifacts = out.get("artifacts") or {}

    assert artifacts.get("evidence_pool") == []
    assert artifacts.get("evidence_by_task") == {}
    diagnostics = artifacts.get("tool_diagnostics") or []
    assert diagnostics
    assert diagnostics[0]["tool_name"] == "fetch_url_content"
    assert diagnostics[0]["status"] == "failed"
    assert diagnostics[0]["reason_code"] == "access_denied"
    assert "403" in diagnostics[0]["message"]


def test_rejected_empty_and_timeout_outputs_are_not_evidence(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "true")

    outputs = {
        "search": {"status": "rejected", "reason": "policy rejected"},
        "get_company_news": {"status": "empty", "articles": []},
        "get_stock_price": {"status": "timeout", "error": "request timeout"},
    }

    class _FakeTool:
        def __init__(self, name: str):
            self.name = name

        def invoke(self, _inputs):
            return outputs[self.name]

    import backend.langchain_tools as tools_mod

    monkeypatch.setattr(tools_mod, "get_tool_by_name", lambda name: _FakeTool(name))

    from backend.graph.nodes.execute_plan_stub import execute_plan_stub

    steps = [
        {"id": "s1", "kind": "tool", "name": "search", "inputs": {"query": "AAPL"}, "task_ids": ["task_1"], "optional": True},
        {"id": "s2", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "AAPL"}, "task_ids": ["task_1"], "optional": True},
        {"id": "s3", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "AAPL"}, "task_ids": ["task_1"], "optional": True},
    ]
    state = {
        "query": "AAPL latest news and price",
        "plan_ir": {
            "goal": "x",
            "subject": {"subject_type": "company", "tickers": ["AAPL"], "selection_ids": [], "selection_types": [], "selection_payload": []},
            "output_mode": "chat",
            "steps": steps,
            "tasks": [{"id": "task_1", "subject_type": "company", "tickers": ["AAPL"], "operation": "fetch"}],
            "budget": {"max_rounds": 1, "max_tools": 3},
            "synthesis": {"style": "concise", "sections": []},
        },
        "policy": {"allowed_tools": ["search", "get_company_news", "get_stock_price"], "budget": {"max_rounds": 1, "max_tools": 3}},
        "subject": {"subject_type": "company", "tickers": ["AAPL"], "selection_payload": []},
        "trace": {},
    }

    out = _run(execute_plan_stub(state))
    artifacts = out.get("artifacts") or {}

    assert artifacts.get("evidence_pool") == []
    diagnostics = artifacts.get("tool_diagnostics") or []
    assert {item["reason_code"] for item in diagnostics} == {"rejected", "empty", "timeout"}


def test_official_macro_releases_promote_nested_release_links_to_evidence(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "true")

    class _FakeTool:
        name = "get_official_macro_releases"

        def invoke(self, _inputs):
            return {
                "query": "Fed news",
                "source": "macro_official_feeds",
                "releases": [
                    {
                        "title": "Federal Reserve monetary policy releases",
                        "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary.htm",
                        "snippet": "Official Federal Reserve monetary policy releases page.",
                        "source": "Federal Reserve",
                        "is_official": True,
                        "type": "macro_release",
                    }
                ],
                "count": 1,
                "error": None,
            }

    import backend.langchain_tools as tools_mod

    monkeypatch.setattr(tools_mod, "get_tool_by_name", lambda name: _FakeTool())

    from backend.graph.nodes.execute_plan_stub import execute_plan_stub

    state = {
        "query": "Any latest Fed news that affects QQQ? Please cite sources.",
        "plan_ir": {
            "goal": "x",
            "subject": {"subject_type": "macro", "tickers": ["QQQ"], "selection_ids": [], "selection_types": [], "selection_payload": []},
            "output_mode": "chat",
            "steps": [
                {
                    "id": "s1",
                    "kind": "tool",
                    "name": "get_official_macro_releases",
                    "inputs": {"query": "Fed news"},
                    "task_ids": ["task_1"],
                    "optional": True,
                }
            ],
            "tasks": [{"id": "task_1", "subject_type": "macro", "tickers": ["QQQ"], "operation": "fetch"}],
            "budget": {"max_rounds": 1, "max_tools": 1},
            "synthesis": {"style": "concise", "sections": []},
        },
        "policy": {"allowed_tools": ["get_official_macro_releases"], "budget": {"max_rounds": 1, "max_tools": 1}},
        "subject": {"subject_type": "macro", "tickers": ["QQQ"], "selection_payload": []},
        "trace": {},
    }

    out = _run(execute_plan_stub(state))
    artifacts = out.get("artifacts") or {}
    evidence = artifacts.get("evidence_pool") or []

    assert evidence
    assert evidence[0]["type"] == "macro_release"
    assert evidence[0]["url"] == "https://www.federalreserve.gov/newsevents/pressreleases/monetary.htm"


def test_official_macro_releases_fed_query_has_official_fallback_when_feeds_empty(monkeypatch):
    from backend.tools import macro_official

    monkeypatch.setattr(macro_official, "_fetch_feed", lambda _url: "")

    out = macro_official.get_official_macro_releases("latest Fed news", max_results=2)
    releases = out.get("releases") or []

    assert out["count"] == 2
    assert all(item["url"].startswith("https://www.federalreserve.gov/") for item in releases)
    assert all(item.get("fallback") is True for item in releases)

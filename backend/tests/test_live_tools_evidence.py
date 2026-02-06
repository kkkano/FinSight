# -*- coding: utf-8 -*-
import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_execute_plan_stub_merges_tool_output_into_evidence_pool(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "true")

    class _FakeTool:
        def __init__(self, name: str):
            self.name = name

        def invoke(self, inputs):
            return f"{self.name} ok: {inputs}"

    import backend.langchain_tools as tools_mod

    monkeypatch.setattr(tools_mod, "get_tool_by_name", lambda name: _FakeTool(name))

    from backend.graph.nodes.execute_plan_stub import execute_plan_stub

    state = {
        "plan_ir": {
            "goal": "x",
            "subject": {"subject_type": "unknown", "tickers": [], "selection_ids": [], "selection_types": [], "selection_payload": []},
            "output_mode": "brief",
            "steps": [
                {
                    "id": "s1",
                    "kind": "tool",
                    "name": "search",
                    "inputs": {"query": "AAPL"},
                    "why": "unit",
                    "optional": False,
                }
            ],
            "budget": {"max_rounds": 1, "max_tools": 1},
            "synthesis": {"style": "concise", "sections": []},
        },
        "policy": {"allowed_tools": ["search"], "budget": {"max_rounds": 1, "max_tools": 1}},
        "subject": {"subject_type": "unknown", "selection_payload": []},
        "trace": {},
    }

    out = _run(execute_plan_stub(state))
    artifacts = out.get("artifacts") or {}
    pool = artifacts.get("evidence_pool") or []

    assert any(e.get("source") == "search" for e in pool), "tool output should be normalized into evidence_pool"


def test_execute_plan_stub_merges_agent_output_into_evidence_pool(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "true")

    import importlib

    execute_mod = importlib.import_module("backend.graph.nodes.execute_plan_stub")

    async def _fake_agent(_inputs):
        return {
            "agent_name": "fundamental",
            "summary": "Revenue: $100B",
            "confidence": 0.9,
            "as_of": "2026-02-04T00:00:00",
            "evidence": [{"text": "Revenue: $100B", "source": "yfinance", "timestamp": "2025-12-31"}],
        }

    monkeypatch.setattr(execute_mod, "build_agent_invokers", lambda allowed_agents, state: {"fundamental_agent": _fake_agent})

    from backend.graph.nodes.execute_plan_stub import execute_plan_stub

    state = {
        "plan_ir": {
            "goal": "x",
            "subject": {"subject_type": "company", "tickers": ["AAPL"], "selection_ids": [], "selection_types": [], "selection_payload": []},
            "output_mode": "investment_report",
            "steps": [
                {
                    "id": "s1",
                    "kind": "agent",
                    "name": "fundamental_agent",
                    "inputs": {"query": "fundamentals", "ticker": "AAPL"},
                    "why": "unit",
                    "optional": False,
                }
            ],
            "budget": {"max_rounds": 1, "max_tools": 1},
            "synthesis": {"style": "concise", "sections": []},
        },
        "policy": {"allowed_tools": [], "allowed_agents": ["fundamental_agent"], "budget": {"max_rounds": 1, "max_tools": 1}},
        "subject": {"subject_type": "company", "tickers": ["AAPL"], "selection_payload": []},
        "trace": {},
    }

    out = _run(execute_plan_stub(state))
    artifacts = out.get("artifacts") or {}
    pool = artifacts.get("evidence_pool") or []

    assert any(e.get("type") == "agent" and "Revenue" in str(e.get("snippet") or "") for e in pool)

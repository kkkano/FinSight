# -*- coding: utf-8 -*-

from backend.graph.trace import _span_data


def test_trace_policy_gate_includes_v2_fields():
    state = {
        "query": "分析苹果",
        "subject": {"tickers": ["AAPL"]},
        "ui_context": {"active_symbol": "AAPL"},
    }
    updates = {
        "policy": {
            "budget": {"max_tools": 8},
            "allowed_tools": ["price", "news"],
            "agent_selection": {
                "selected": ["price_agent"],
                "required": ["price_agent"],
                "scores": {"price_agent": 0.92},
                "reasons": {"price_agent": ["ticker present"]},
            },
        }
    }

    data = _span_data("policy_gate", state, updates)

    assert data.get("decision_type") == "policy_gate"
    assert isinstance(data.get("summary"), str) and data["summary"]
    assert data.get("fallback_reason") == "none"
    assert data.get("input_state") in {"explicit", "implicit", "redacted", "empty"}


def test_trace_planner_includes_parallel_group_in_preview_steps():
    state = {
        "query": "对比 AAPL 和 MSFT",
        "policy": {},
        "subject": {"tickers": ["AAPL", "MSFT"]},
    }
    updates = {
        "plan_ir": {
            "steps": [
                {
                    "id": "s1",
                    "kind": "tool",
                    "name": "price",
                    "why": "need latest quote",
                    "parallel_group": "g1",
                }
            ]
        },
        "trace": {"planner_runtime": {"mode": "stub", "variant": "B"}},
    }

    data = _span_data("planner", state, updates)

    assert data.get("decision_type") == "planner"
    assert isinstance(data.get("summary"), str) and data["summary"]
    assert "fallback_reason" in data
    runtime = data.get("planner_runtime") or {}
    assert runtime.get("variant") == "B"
    steps = data.get("steps") or []
    assert steps and steps[0].get("parallel_group") == "g1"


def test_trace_execute_plan_includes_duration_status_and_parallel_group():
    state = {
        "plan_ir": {
            "steps": [
                {"id": "s1", "kind": "tool", "name": "price", "parallel_group": "g1"}
            ]
        },
        "policy": {},
    }
    updates = {
        "artifacts": {
            "step_results": {
                "s1": {
                    "cached": False,
                    "duration_ms": 42,
                    "status_reason": "done",
                    "parallel_group": "g1",
                    "output": {"price": 123.4},
                }
            }
        },
        "trace": {"executor": {"mode": "live"}},
    }

    data = _span_data("execute_plan", state, updates)

    assert data.get("decision_type") == "execute_plan"
    assert isinstance(data.get("summary"), str) and data["summary"]
    assert data.get("fallback_reason") == "none"
    steps = data.get("steps") or []
    assert len(steps) == 1
    assert steps[0].get("duration_ms") == 42
    assert steps[0].get("status_reason") == "done"
    assert steps[0].get("parallel_group") == "g1"


def test_trace_synthesize_includes_v2_fields():
    state = {}
    updates = {
        "artifacts": {"render_vars": {"k1": "v1", "k2": "v2"}},
        "trace": {"synthesize_runtime": {"mode": "stub"}},
    }

    data = _span_data("synthesize", state, updates)

    assert data.get("decision_type") == "synthesize"
    assert data.get("summary") == "render_vars=2"
    assert data.get("fallback_reason") == "none"
    assert data.get("synthesize_runtime", {}).get("mode") == "stub"

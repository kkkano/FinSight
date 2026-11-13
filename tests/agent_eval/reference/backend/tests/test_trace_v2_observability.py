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


def test_trace_policy_gate_includes_skill_selection():
    state = {"query": "NVDA 估值贵不贵", "subject": {"tickers": ["NVDA"]}}
    updates = {
        "policy": {
            "budget": {"max_tools": 8},
            "allowed_tools": ["get_stock_price", "run_python_compute"],
            "allowed_agents": ["fundamental_agent", "risk_agent"],
            "agent_selection": {"selected": ["fundamental_agent", "risk_agent"], "required": []},
            "skill_selection": {
                "selected_skill": "valuation-sanity-check",
                "reason": "facet_match",
                "candidates": [{"name": "valuation-sanity-check", "score": 1.0}],
            },
        }
    }

    data = _span_data("policy_gate", state, updates)

    assert data["skill_selection"]["selected_skill"] == "valuation-sanity-check"
    assert data["skill_selection"]["reason"] == "facet_match"


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


def test_trace_execute_plan_summarizes_python_compute_outputs():
    state = {
        "plan_ir": {
            "steps": [
                {"id": "s1", "kind": "tool", "name": "run_python_compute", "parallel_group": "analysis"}
            ]
        },
        "policy": {},
    }
    updates = {
        "artifacts": {
            "step_results": {
                "s1": {
                    "cached": False,
                    "duration_ms": 12,
                    "status_reason": "done",
                    "parallel_group": "analysis",
                    "output": {
                        "metrics": {"price_to_sales": 18.2},
                        "input_refs": ["step:get_stock_price"],
                        "warnings": [],
                    },
                }
            }
        },
        "trace": {"executor": {"mode": "live"}},
    }

    data = _span_data("execute_plan", state, updates)

    python_rows = data.get("python_compute") or []
    assert python_rows[0]["step_id"] == "s1"
    assert python_rows[0]["duration_ms"] == 12
    assert python_rows[0]["input_refs"] == ["step:get_stock_price"]
    assert python_rows[0]["output_preview"]["metrics"]["price_to_sales"] == 18.2


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

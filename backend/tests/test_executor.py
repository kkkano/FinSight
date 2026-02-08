# -*- coding: utf-8 -*-
import asyncio
import time

from backend.graph.executor import execute_plan, group_steps_by_parallel_group


def _run(coro):
    return asyncio.run(coro)


def test_group_steps_by_parallel_group_contiguous_blocks():
    steps = [
        {"id": "s1", "parallel_group": "g1"},
        {"id": "s2", "parallel_group": "g1"},
        {"id": "s3"},
        {"id": "s4", "parallel_group": "g2"},
        {"id": "s5", "parallel_group": "g2"},
    ]
    groups = group_steps_by_parallel_group(steps)
    assert [[s.get("id") for s in g] for g in groups] == [["s1", "s2"], ["s3"], ["s4", "s5"]]


def test_execute_plan_parallel_group_runs_concurrently():
    async def slow_tool(inputs):
        await asyncio.sleep(0.2)
        return {"ok": inputs.get("x")}

    plan = {
        "steps": [
            {"id": "s1", "kind": "tool", "name": "slow", "inputs": {"x": 1}, "parallel_group": "g1", "optional": False},
            {"id": "s2", "kind": "tool", "name": "slow", "inputs": {"x": 2}, "parallel_group": "g1", "optional": False},
        ]
    }

    start = time.perf_counter()
    artifacts, _events = _run(execute_plan(plan, tool_invokers={"slow": slow_tool}, dry_run=False))
    duration = time.perf_counter() - start

    assert duration < 0.35, f"expected parallel execution; took {duration:.3f}s"
    assert set(artifacts.get("step_results", {}).keys()) == {"s1", "s2"}


def test_execute_plan_step_cache_dedupes_calls():
    calls = {"n": 0}

    def add_one(inputs):
        calls["n"] += 1
        return inputs["x"] + 1

    plan = {
        "steps": [
            {"id": "s1", "kind": "tool", "name": "add_one", "inputs": {"x": 1}, "optional": False},
            {"id": "s2", "kind": "tool", "name": "add_one", "inputs": {"x": 1}, "optional": False},
        ]
    }

    artifacts, _events = _run(execute_plan(plan, tool_invokers={"add_one": add_one}, dry_run=False))
    assert calls["n"] == 1
    assert artifacts["step_results"]["s1"]["cached"] is False
    assert artifacts["step_results"]["s2"]["cached"] is True


def test_execute_plan_optional_failure_does_not_stop():
    calls = {"ok": 0}

    def ok_tool(_inputs):
        calls["ok"] += 1
        return "ok"

    plan = {
        "steps": [
            {"id": "s1", "kind": "tool", "name": "missing", "inputs": {}, "optional": True},
            {"id": "s2", "kind": "tool", "name": "ok", "inputs": {}, "optional": False},
        ]
    }

    artifacts, _events = _run(execute_plan(plan, tool_invokers={"ok": ok_tool}, dry_run=False))
    assert calls["ok"] == 1
    assert len(artifacts.get("errors") or []) == 1
    assert "s1" == artifacts["errors"][0]["step_id"]


def test_execute_plan_required_failure_stops_following_steps():
    calls = {"ok": 0}

    def ok_tool(_inputs):
        calls["ok"] += 1
        return "ok"

    plan = {
        "steps": [
            {"id": "s1", "kind": "tool", "name": "missing", "inputs": {}, "optional": False},
            {"id": "s2", "kind": "tool", "name": "ok", "inputs": {}, "optional": False},
        ]
    }

    artifacts, _events = _run(execute_plan(plan, tool_invokers={"ok": ok_tool}, dry_run=False))
    assert calls["ok"] == 0
    assert len(artifacts.get("errors") or []) == 1
    assert "s1" == artifacts["errors"][0]["step_id"]


def test_execute_plan_supports_llm_summarize_selection_in_live_mode():
    plan = {
        "steps": [
            {
                "id": "s1",
                "kind": "llm",
                "name": "summarize_selection",
                "inputs": {"selection": [{"title": "T", "snippet": "S"}]},
                "optional": False,
            }
        ]
    }
    artifacts, _events = _run(execute_plan(plan, tool_invokers={}, dry_run=False))
    output = artifacts["step_results"]["s1"]["output"]
    assert "T" in str(output)


def test_execute_plan_runs_llm_summarize_selection_even_in_dry_run():
    plan = {
        "steps": [
            {
                "id": "s1",
                "kind": "llm",
                "name": "summarize_selection",
                "inputs": {"selection": [{"title": "T", "snippet": "S"}]},
                "optional": False,
            }
        ]
    }
    artifacts, _events = _run(execute_plan(plan, tool_invokers={}, dry_run=True))
    output = artifacts["step_results"]["s1"]["output"]
    assert "T" in str(output)


def test_execute_plan_supports_agent_steps_in_live_mode():
    async def fake_agent(inputs):
        return {"agent": "ok", "inputs": inputs}

    plan = {
        "steps": [
            {"id": "s1", "kind": "agent", "name": "fundamental_agent", "inputs": {"ticker": "AAPL"}, "optional": False},
        ]
    }
    artifacts, _events = _run(execute_plan(plan, agent_invokers={"fundamental_agent": fake_agent}, dry_run=False))
    output = artifacts["step_results"]["s1"]["output"]
    assert output.get("agent") == "ok"


def test_execute_plan_progressive_escalation_skips_high_cost_step_when_confidence_sufficient():
    calls = {"deep": 0}

    async def low_cost_agent(_inputs):
        return {"confidence": 0.9, "summary": "enough evidence"}

    async def deep_agent(_inputs):
        calls["deep"] += 1
        return {"confidence": 0.95, "summary": "deep search"}

    plan = {
        "steps": [
            {"id": "s1", "kind": "agent", "name": "price_agent", "inputs": {"ticker": "AAPL"}, "optional": False},
            {
                "id": "s2",
                "kind": "agent",
                "name": "deep_search_agent",
                "inputs": {
                    "ticker": "AAPL",
                    "__escalation_stage": "high_cost",
                    "__run_if_min_confidence": 0.8,
                    "__force_run": False,
                },
                "optional": True,
            },
        ]
    }

    artifacts, _events = _run(
        execute_plan(
            plan,
            agent_invokers={"price_agent": low_cost_agent, "deep_search_agent": deep_agent},
            dry_run=False,
        )
    )

    assert calls["deep"] == 0
    step2_output = artifacts["step_results"]["s2"]["output"]
    assert step2_output.get("skipped") is True
    assert step2_output.get("reason") == "escalation_not_needed"
    assert float((artifacts.get("signals") or {}).get("max_confidence") or 0.0) >= 0.9


def test_execute_plan_progressive_escalation_force_run_executes_high_cost_step():
    calls = {"deep": 0}

    async def low_cost_agent(_inputs):
        return {"confidence": 0.95, "summary": "enough evidence"}

    async def deep_agent(_inputs):
        calls["deep"] += 1
        return {"confidence": 0.96, "summary": "deep search"}

    plan = {
        "steps": [
            {"id": "s1", "kind": "agent", "name": "price_agent", "inputs": {"ticker": "AAPL"}, "optional": False},
            {
                "id": "s2",
                "kind": "agent",
                "name": "deep_search_agent",
                "inputs": {
                    "ticker": "AAPL",
                    "__escalation_stage": "high_cost",
                    "__run_if_min_confidence": 0.8,
                    "__force_run": True,
                },
                "optional": True,
            },
        ]
    }

    artifacts, _events = _run(
        execute_plan(
            plan,
            agent_invokers={"price_agent": low_cost_agent, "deep_search_agent": deep_agent},
            dry_run=False,
        )
    )

    assert calls["deep"] == 1
    step2_output = artifacts["step_results"]["s2"]["output"]
    assert step2_output.get("summary") == "deep search"

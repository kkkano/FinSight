# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from backend.graph.dag_executor import execute_plan_dag


@pytest.mark.asyncio
async def test_whitelisted_delegation_inserts_scoped_tool_and_delays_same_task_agent(monkeypatch):
    monkeypatch.setenv("FINSIGHT_AGENT_DELEGATION", "on")
    seen_inputs: dict[str, dict] = {}

    async def requester(_inputs):
        return {
            "summary": "需要同行清单",
            "requests": [{"type": "delegate", "evidence": "peer_tickers", "reason": "缺同行"}],
        }

    async def observer(inputs):
        seen_inputs[inputs["marker"]] = inputs
        return {"summary": "done"}

    async def search(_inputs):
        return {"summary": "同行包括 AMD 与 INTC"}

    plan = {"steps": [
        {"id": "a", "kind": "agent", "name": "price_agent", "inputs": {"ticker": "NVDA"}, "task_ids": ["t1"]},
        {"id": "b", "kind": "agent", "name": "technical_agent", "inputs": {"marker": "same"}, "depends_on": ["a"], "task_ids": ["t1"]},
        {"id": "c", "kind": "agent", "name": "news_agent", "inputs": {"marker": "other"}, "depends_on": ["a"], "task_ids": ["t2"]},
    ]}
    artifacts, _ = await execute_plan_dag(
        plan,
        tool_invokers={"search": search},
        agent_invokers={"price_agent": requester, "technical_agent": observer, "news_agent": observer},
        dry_run=False,
        context_bus={},
    )

    scheduled = [row for row in artifacts["delegation_trace"] if row["status"] == "scheduled"]
    assert len(scheduled) == 1
    dynamic_id = scheduled[0]["dynamic_step_id"]
    assert artifacts["step_results"][dynamic_id]["status_reason"] == "done"
    dynamic_step = next(step for step in plan["steps"] if step["id"] == dynamic_id)
    assert dynamic_step["depends_on"] == ["a"]
    assert dynamic_step["task_ids"] == ["t1"]
    assert "同行包括 AMD" in seen_inputs["same"]["__context_digest"]
    assert "同行包括 AMD" not in seen_inputs["other"].get("__context_digest", "")


@pytest.mark.asyncio
async def test_delegation_caps_dynamic_steps(monkeypatch):
    monkeypatch.setenv("FINSIGHT_AGENT_DELEGATION", "on")

    async def agent(inputs):
        return {
            "summary": "request",
            "requests": [{"type": "delegate", "evidence": inputs["evidence"], "reason": "gap"}],
        }

    async def tool(_inputs):
        return {"summary": "ok"}

    plan = {"steps": [
        {"id": "a", "kind": "agent", "name": "a", "inputs": {"evidence": "peer_tickers"}, "task_ids": ["t1"]},
        {"id": "b", "kind": "agent", "name": "b", "inputs": {"evidence": "event_context"}, "task_ids": ["t2"]},
        {"id": "c", "kind": "agent", "name": "c", "inputs": {"evidence": "macro_snapshot"}, "task_ids": ["t3"]},
    ]}
    artifacts, _ = await execute_plan_dag(
        plan,
        tool_invokers={"search": tool, "get_economic_events": tool},
        agent_invokers={name: agent for name in ("a", "b", "c")},
        dry_run=False,
        context_bus={},
    )
    scheduled = [row for row in artifacts.get("delegation_trace", []) if row["status"] == "scheduled"]
    assert len(scheduled) == 2
    assert [row["requesting_step_id"] for row in scheduled] == ["a", "b"]
    assert len([step for step in plan["steps"] if str(step["id"]).startswith("delegated_")]) == 2


@pytest.mark.asyncio
async def test_delegation_traces_unknown_evidence_without_adding_step(monkeypatch):
    monkeypatch.setenv("FINSIGHT_AGENT_DELEGATION", "on")

    async def agent(_inputs):
        return {
            "summary": "request",
            "requests": [{"type": "delegate", "evidence": "database_dump", "reason": "gap"}],
        }

    plan = {"steps": [
        {"id": "a", "kind": "agent", "name": "a", "inputs": {}, "task_ids": ["t1"]},
    ]}
    artifacts, _ = await execute_plan_dag(
        plan,
        agent_invokers={"a": agent},
        dry_run=False,
        context_bus={},
    )

    assert artifacts["delegation_trace"] == [
        {"requesting_step_id": "a", "evidence": "database_dump", "status": "ignored_not_whitelisted"}
    ]
    assert [step for step in plan["steps"] if str(step["id"]).startswith("delegated_")] == []


@pytest.mark.asyncio
async def test_delegation_without_task_ids_keeps_business_task_ids_empty(monkeypatch):
    monkeypatch.setenv("FINSIGHT_AGENT_DELEGATION", "on")

    async def agent(_inputs):
        return {
            "summary": "request",
            "requests": [{"type": "delegate", "evidence": "macro_snapshot", "reason": "gap"}],
        }

    async def tool(_inputs):
        return {"summary": "macro ok"}

    plan = {"steps": [{"id": "a", "kind": "agent", "name": "a", "inputs": {}}]}
    artifacts, _ = await execute_plan_dag(
        plan,
        tool_invokers={"get_economic_events": tool},
        agent_invokers={"a": agent},
        dry_run=False,
        context_bus={},
    )

    dynamic_id = artifacts["delegation_trace"][0]["dynamic_step_id"]
    dynamic_step = next(step for step in plan["steps"] if step["id"] == dynamic_id)
    assert dynamic_step["task_ids"] == []
    assert "task_id" not in dynamic_step


@pytest.mark.asyncio
async def test_delegation_is_off_by_default(monkeypatch):
    monkeypatch.delenv("FINSIGHT_AGENT_DELEGATION", raising=False)

    async def agent(_inputs):
        return {
            "summary": "request",
            "requests": [{"type": "delegate", "evidence": "macro_snapshot", "reason": "gap"}],
        }

    plan = {"steps": [{"id": "a", "kind": "agent", "name": "a", "inputs": {}, "task_ids": ["t1"]}]}
    artifacts, _ = await execute_plan_dag(
        plan,
        agent_invokers={"a": agent},
        dry_run=False,
        context_bus={},
    )

    assert "delegation_trace" not in artifacts
    assert len(plan["steps"]) == 1

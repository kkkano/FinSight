# -*- coding: utf-8 -*-
"""WP2-Task7: 证据黑板——后续 agent 能读到前序 agent 的产出摘要。"""
import pytest

from backend.graph.context_bus import digest_agent_output, render_bus
from backend.graph.dag_executor import execute_plan_dag


def test_digest_truncates_and_formats():
    d = digest_agent_output("price_agent", {"summary": "AAPL " + "x" * 500, "evidence": [{"title": "Q3 beat"}]})
    assert d.startswith("price_agent: AAPL")
    assert len(d) <= 300


@pytest.mark.asyncio
async def test_later_agent_sees_earlier_agent_digest():
    seen = {}

    async def price_agent(inputs):
        return {"summary": "AAPL at $200 after earnings beat", "evidence": []}

    async def risk_agent(inputs):
        seen["digest"] = inputs.get("__context_digest", "")
        return {"summary": "risk ok", "evidence": []}

    plan = {"steps": [
        {"id": "s1", "kind": "agent", "name": "price_agent", "inputs": {"query": "q", "ticker": "AAPL"}, "depends_on": []},
        {"id": "s2", "kind": "agent", "name": "risk_agent", "inputs": {"query": "q", "ticker": "AAPL"}, "depends_on": ["s1"]},
    ]}
    await execute_plan_dag(plan, tool_invokers={}, agent_invokers={"price_agent": price_agent, "risk_agent": risk_agent},
                           dry_run=False, context_bus={})
    assert "price_agent: AAPL at $200" in seen["digest"]


@pytest.mark.asyncio
async def test_context_bus_isolated_by_task_id():
    seen: dict[str, str] = {}

    async def price_agent(_inputs):
        return {"summary": "AAPL price evidence", "evidence": []}

    async def news_agent(_inputs):
        return {"summary": "MSFT news evidence", "evidence": []}

    async def risk_agent(inputs):
        seen[inputs["ticker"]] = inputs.get("__context_digest", "")
        return {"summary": "done", "evidence": []}

    plan = {
        "steps": [
            {"id": "a1", "kind": "agent", "name": "price_agent", "inputs": {"ticker": "AAPL"}, "task_ids": ["t1"]},
            {"id": "b1", "kind": "agent", "name": "news_agent", "inputs": {"ticker": "MSFT"}, "task_ids": ["t2"]},
            {"id": "a2", "kind": "agent", "name": "risk_agent", "inputs": {"ticker": "AAPL"}, "task_ids": ["t1"], "depends_on": ["a1"]},
            {"id": "b2", "kind": "agent", "name": "risk_agent", "inputs": {"ticker": "MSFT"}, "task_ids": ["t2"], "depends_on": ["b1"]},
        ]
    }
    await execute_plan_dag(
        plan,
        tool_invokers={},
        agent_invokers={"price_agent": price_agent, "news_agent": news_agent, "risk_agent": risk_agent},
        dry_run=False,
        context_bus={},
    )

    assert "AAPL price evidence" in seen["AAPL"]
    assert "MSFT news evidence" not in seen["AAPL"]
    assert "MSFT news evidence" in seen["MSFT"]
    assert "AAPL price evidence" not in seen["MSFT"]

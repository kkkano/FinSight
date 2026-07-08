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

# -*- coding: utf-8 -*-

import asyncio
from datetime import datetime

from backend.agents.base_agent import AgentOutput, EvidenceItem
from backend.orchestration.plan import PlanBuilder, PlanExecutor


class DummyAgent:
    def __init__(self, name: str):
        self.name = name

    async def research(self, query: str, ticker: str):
        return AgentOutput(
            agent_name=self.name,
            summary=f"{self.name} summary",
            evidence=[EvidenceItem(text="evidence", source="dummy")],
            confidence=0.9,
            data_sources=["dummy"],
            as_of=datetime.now().isoformat(),
            fallback_used=False,
            risks=[],
        )


class DummyForum:
    async def synthesize(self, outputs, user_profile=None):
        return {"consensus": "ok", "confidence": 0.8}


def test_plan_executor_runs_steps():
    agents = {"price": DummyAgent("price"), "news": DummyAgent("news")}
    plan = PlanBuilder.build_report_plan("query", "AAPL", list(agents.keys()))
    executor = PlanExecutor(agents, DummyForum())

    result = asyncio.run(executor.execute(plan, "query", "AAPL"))

    assert set(result["agent_outputs"].keys()) == {"price", "news"}
    assert result["plan"]["steps"][0]["status"] in {"completed", "failed"}
    assert any(event["event"] == "step_start" for event in result["trace"])

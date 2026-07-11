# -*- coding: utf-8 -*-
"""WP2-Task6: AgentBrief 注入——brief 必须到达 agent 的分析 prompt。"""
import pytest

from backend.graph.intent.frame import AgentBrief


@pytest.mark.asyncio
async def test_brief_reaches_llm_analyze_prompt(monkeypatch):
    """brief.context_digest 与 objective 必须出现在 _llm_analyze 的 prompt <context> 中。"""
    from backend.agents.base_agent import BaseFinancialAgent
    captured = {}

    class FakeLLM:
        model_name = "fake"

        async def ainvoke(self, messages, **kw):
            captured["prompt"] = messages[0].content

            class R:
                content = "x" * 100
            return R()

    agent = BaseFinancialAgent(FakeLLM(), cache=None)
    monkeypatch.setenv("AGENT_LLM_ANALYZE_ENABLED", "true")
    from backend.config.settings import agent_settings
    agent_settings.cache_clear()
    agent._current_brief = AgentBrief(query="q", ticker="AAPL", objective="earnings_impact",
                                      context_digest="price_agent: AAPL $200, +3% on earnings beat")
    await agent._llm_analyze("data summary", role="analyst", focus="f")
    assert "earnings_impact" in captured["prompt"]
    assert "price_agent: AAPL $200" in captured["prompt"]


@pytest.mark.asyncio
async def test_adapter_builds_brief_from_step_inputs():
    from backend.graph.adapters.agent_adapter import brief_from_inputs
    inputs = {"query": "q", "ticker": "AAPL", "objective": "compare",
              "required_evidence": ["price_snapshot"], "__context_digest": "news_agent: ..."}
    brief = brief_from_inputs(inputs, default_query="q", default_ticker="AAPL", output_mode="chat")
    assert brief.objective == "compare"
    assert brief.context_digest.startswith("news_agent")

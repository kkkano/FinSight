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
    async def invoke_with_fixture(messages, **_kwargs):
        return await agent.llm.ainvoke(messages)

    monkeypatch.setattr(
        "backend.services.llm_retry.ainvoke_configured_llm",
        invoke_with_fixture,
    )
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


def test_prediction_memory_context_is_tenant_agent_and_ticker_scoped(monkeypatch):
    from backend.graph.adapters.agent_adapter import _prediction_memory_context

    class Store:
        def prediction_history(self, **kwargs):
            assert kwargs == {
                "agent": "technical_agent", "ticker": "AAPL", "user_id": "alice", "limit": 1,
            }
            return [{
                "direction": "long",
                "thesis": "趋势延续，等待确认",
                "anchor": {"time": "2026-07-10", "price": 103.0},
                "entry": 104.0,
                "stop": 99.0,
                "target1": 114.0,
                "status": "hit_target",
            }]

    monkeypatch.setattr(
        "backend.services.agent_prediction_store.get_agent_prediction_store",
        lambda: Store(),
    )

    text = _prediction_memory_context(user_id="alice", agent="technical_agent", ticker="aapl")
    assert "你上次(2026-07-10)对AAPL判断 long" in text
    assert "entry/stop/T1=104.0/99.0/114.0" in text
    assert "outcome=hit_target" in text
    assert "不得自动继承" in text
    assert _prediction_memory_context(user_id="public", agent="technical_agent", ticker="AAPL") == ""

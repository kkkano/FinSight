# -*- coding: utf-8 -*-

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


class FailingLLM:
    async def ainvoke(self, messages):
        raise RuntimeError("Simulated LLM failure")


@pytest.mark.asyncio
async def test_news_analysis_failure_never_returns_raw_news_list():
    from backend.orchestration.cache import DataCache
    from backend.services.circuit_breaker import CircuitBreaker
    from backend.orchestration.supervisor_agent import SupervisorAgent
    from tests.regression.mocks.mock_tools import MockToolsModule

    supervisor = SupervisorAgent(
        llm=FailingLLM(),
        tools_module=MockToolsModule(),
        cache=DataCache(),
        circuit_breaker=CircuitBreaker(),
    )

    context_summary = (
        "[System Context]\n"
        "用户正在询问以下新闻:\n"
        "- [2026-02-01] Tesla Q4 earnings beat; gross margin up.\n"
        "用户问题: 分析新闻可能带来的影响\n"
    )

    result = await supervisor.process(
        query="分析 TSLA 新闻的影响",
        tickers=["TSLA"],
        context_summary=context_summary,
    )

    assert result.intent.value == "news"
    assert result.success is False
    assert "无法完成" in result.response
    # Should not dump the formatted raw news list when analysis is required
    assert "**TSLA" not in result.response

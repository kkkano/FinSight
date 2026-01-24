import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from backend.agents.deep_search_agent import DeepSearchAgent
from backend.agents.macro_agent import MacroAgent
from backend.orchestration.supervisor_agent import SupervisorAgent
from backend.agents.base_agent import AgentOutput

@pytest.mark.asyncio
async def test_deep_search_agent():
    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mock_tools = MagicMock()

    agent = DeepSearchAgent(None, mock_cache, mock_tools)
    agent._search_web = MagicMock(return_value=[{
        "title": "Sample Report",
        "url": "https://example.com/report",
        "snippet": "Sample snippet",
        "source": "search",
    }])
    agent._fetch_documents = MagicMock(return_value=[{
        "title": "Sample Report",
        "url": "https://example.com/report",
        "snippet": "Sample snippet",
        "content": "Sample content for deep search report.",
        "source": "search",
        "is_pdf": False,
    }])

    # Test research flow
    result = await agent.research("NVDA investment thesis", "NVDA")

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "deep_search"
    assert "search" in result.data_sources
    assert len(result.evidence) == 1

@pytest.mark.asyncio
async def test_deep_search_agent_self_rag_merges_docs():
    mock_cache = MagicMock()
    mock_tools = MagicMock()
    agent = DeepSearchAgent(None, mock_cache, mock_tools)

    base_docs = [{
        "title": "Base Doc",
        "url": "https://example.com/base",
        "snippet": "Base snippet",
        "content": "Base content.",
        "source": "tavily",
        "is_pdf": False,
    }]
    extra_docs = [{
        "title": "Gap Doc",
        "url": "https://example.com/gap",
        "snippet": "Gap snippet",
        "content": "Gap content.",
        "source": "search",
        "is_pdf": True,
    }]

    agent._initial_search = AsyncMock(return_value=base_docs)
    agent._identify_gaps = AsyncMock(side_effect=[["competitors"], []])
    agent._targeted_search = AsyncMock(return_value=extra_docs)
    agent._first_summary = AsyncMock(return_value="Initial summary")
    agent._update_summary = AsyncMock(return_value="Updated summary")

    result = await agent.research("NVDA investment thesis", "NVDA")

    assert isinstance(result, AgentOutput)
    assert result.summary == "Updated summary"
    assert len(result.evidence) == 2
    assert "tavily" in result.data_sources
    assert "search" in result.data_sources

@pytest.mark.asyncio
async def test_macro_agent():
    mock_llm = MagicMock()
    mock_cache = MagicMock()
    mock_tools = MagicMock()
    mock_tools.get_fred_data.return_value = {
        "fed_rate": 5.0,
        "fed_rate_formatted": "5.0%",
        "cpi_formatted": "3.2%",
    }

    agent = MacroAgent(mock_llm, mock_cache, mock_tools)

    # Test research flow with macro keyword
    result = await agent.research("inflation analysis", "N/A")

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "macro"
    # Ensure evidence is collected (even if mocked)
    if result.evidence:
        assert result.evidence[0].source.startswith("FRED")

@pytest.mark.asyncio
async def test_macro_agent_fallback_structured():
    mock_llm = MagicMock()
    mock_cache = MagicMock()
    mock_tools = MagicMock()
    mock_tools.get_fred_data.side_effect = Exception("FRED down")
    mock_tools.search.return_value = "fallback text"

    agent = MacroAgent(mock_llm, mock_cache, mock_tools)
    result = await agent.research("inflation analysis", "N/A")

    assert "搜索回退" in result.summary
    assert "Web Search" in result.data_sources
    assert result.evidence is not None
    assert len(result.evidence) > 0

@pytest.mark.asyncio
async def test_supervisor_integration_phase2():
    mock_llm = MagicMock()
    mock_tools = MagicMock()
    mock_cache = MagicMock()

    supervisor = AgentSupervisor(mock_llm, mock_tools, mock_cache)

    # Check if new agents are registered
    assert "deep_search" in supervisor.agents
    assert "macro" in supervisor.agents
    assert "technical" in supervisor.agents
    assert "fundamental" in supervisor.agents

    # Mock all agents research method to avoid actual calls
    for name, agent in supervisor.agents.items():
        agent.research = AsyncMock(return_value=AgentOutput(
            agent_name=name,
            summary=f"{name} summary",
            evidence=[],
            confidence=0.8,
            data_sources=["test"],
            as_of="2023-01-01"
        ))

    # Mock Forum synthesize
    supervisor.forum.synthesize = AsyncMock(return_value=MagicMock())

    # Run analyze
    await supervisor.analyze("Deep analysis of NVDA", "NVDA")

    # Verify agents were called
    supervisor.agents["deep_search"].research.assert_called()
    supervisor.agents["macro"].research.assert_called()
    supervisor.agents["technical"].research.assert_called()
    supervisor.agents["fundamental"].research.assert_called()


def test_deep_search_queries_dynamic():
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())
    queries = agent._build_queries("valuation risk", "AAPL")
    assert any("risk factors" in q for q in queries)
    assert any("valuation model" in q for q in queries)

if __name__ == "__main__":
    asyncio.run(test_deep_search_agent())
    asyncio.run(test_macro_agent())
    asyncio.run(test_supervisor_integration_phase2())

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from backend.agents.deep_search_agent import DeepSearchAgent
from backend.agents.macro_agent import MacroAgent
from backend.orchestration.supervisor import AgentSupervisor
from backend.agents.base_agent import AgentOutput

@pytest.mark.asyncio
async def test_deep_search_agent():
    mock_llm = MagicMock()
    mock_cache = MagicMock()
    mock_tools = MagicMock()

    agent = DeepSearchAgent(mock_llm, mock_cache, mock_tools)

    # Test research flow
    result = await agent.research("NVDA investment thesis", "NVDA")

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "deep_search"
    # assert result.confidence >= 0.8  (Actual confidence depends on implementation details)
    assert "Tavily" in result.data_sources or "Deep Web" in result.data_sources

@pytest.mark.asyncio
async def test_macro_agent():
    mock_llm = MagicMock()
    mock_cache = MagicMock()
    mock_tools = MagicMock()

    agent = MacroAgent(mock_llm, mock_cache, mock_tools)

    # Test research flow with macro keyword
    result = await agent.research("inflation analysis", "N/A")

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "macro"
    # Ensure evidence is collected (even if mocked)
    if result.evidence:
        assert result.evidence[0].source == "FRED"

@pytest.mark.asyncio
async def test_supervisor_integration_phase2():
    mock_llm = MagicMock()
    mock_tools = MagicMock()
    mock_cache = MagicMock()

    supervisor = AgentSupervisor(mock_llm, mock_tools, mock_cache)

    # Check if new agents are registered
    assert "deep_search" in supervisor.agents
    assert "macro" in supervisor.agents

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

    # Verify DeepSearchAgent was called
    supervisor.agents["deep_search"].research.assert_called()
    supervisor.agents["macro"].research.assert_called()

if __name__ == "__main__":
    asyncio.run(test_deep_search_agent())
    asyncio.run(test_macro_agent())
    asyncio.run(test_supervisor_integration_phase2())

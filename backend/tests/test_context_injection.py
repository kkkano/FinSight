import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from backend.services.memory import UserProfile
from backend.orchestration.forum import ForumHost, ForumOutput, AgentOutput
from backend.orchestration.supervisor_agent import SupervisorAgent
from backend.orchestration.intent_classifier import ClassificationResult, AgentIntent
import backend.services.llm_retry as llm_retry

@pytest.mark.asyncio
async def test_forum_host_context_injection():
    # Mock LLM
    mock_llm = MagicMock()
    # Mock synthesize (since it's not fully implemented with LLM yet)
    host = ForumHost(mock_llm)

    # 1. Test Conservative Profile
    conservative_profile = UserProfile(
        user_id="u1",
        risk_tolerance="low",
        investment_style="conservative"
    )

    outputs = {
        "price": AgentOutput(
            agent_name="PriceAgent",
            summary="价格下跌 5%",
            evidence=[],
            confidence=0.9,
            data_sources=["test"],
            as_of="2023-01-01"
        ),
        "news": AgentOutput(
            agent_name="NewsAgent",
            summary="财报不及预期",
            evidence=[],
            confidence=0.8,
            data_sources=["test"],
            as_of="2023-01-01"
        )
    }

    # 调用 synthesize (注意: 这里的 synthesize 方法目前是 mock 的逻辑，我们主要测试是否接收 profile 参数不报错)
    # 在真实实现中，我们会检查 prompt 是否包含 "用户风险厌恶"
    result = await host.synthesize(outputs, user_profile=conservative_profile)
    assert isinstance(result, ForumOutput)
    # 暂时只能断言结果类型，因为 Prompt 逻辑被注释掉了

@pytest.mark.asyncio
async def test_supervisor_pass_profile():
    # Mock dependencies
    mock_llm = MagicMock()
    mock_tools = MagicMock()
    mock_cache = MagicMock()

    supervisor = SupervisorAgent(mock_llm, mock_tools, mock_cache)

    # Mock Agents
    for name in supervisor.agents:
        supervisor.agents[name].research = AsyncMock(return_value=AgentOutput(
            agent_name=name,
            summary=f"{name} summary",
            evidence=[],
            confidence=0.8,
            data_sources=["test"],
            as_of="2023-01-01"
        ))

    # Mock Forum
    supervisor.forum.synthesize = AsyncMock(return_value=ForumOutput(
        consensus="Consensus",
        disagreement="None",
        confidence=0.8,
        recommendation="HOLD",
        risks=[]
    ))

    profile = UserProfile(user_id="u2", risk_tolerance="high")

    supervisor.classifier.classify = MagicMock(return_value=ClassificationResult(
        intent=AgentIntent.REPORT,
        confidence=1.0,
        tickers=["AAPL"],
        method="test",
        reasoning="forced",
        scores={},
    ))

    # Run process
    result = await supervisor.process("分析 AAPL", tickers=["AAPL"], user_profile=profile)

    # Verify analyze call passed profile to forum
    supervisor.forum.synthesize.assert_called_once()
    call_args = supervisor.forum.synthesize.call_args
    assert call_args.kwargs['user_profile'] == profile

if __name__ == "__main__":
    asyncio.run(test_forum_host_context_injection())
    asyncio.run(test_supervisor_pass_profile())


@pytest.mark.asyncio
async def test_forum_host_uses_retry_and_fallback_on_empty_response(monkeypatch):
    host = ForumHost(MagicMock())

    async def _ok_token(timeout: float = 0.0):
        return True

    class _Resp:
        content = "   "

    async def _fake_retry(*args, **kwargs):
        return _Resp()

    monkeypatch.setattr("backend.services.rate_limiter.acquire_llm_token", _ok_token)
    monkeypatch.setattr(llm_retry, "ainvoke_with_rate_limit_retry", _fake_retry)

    outputs = {
        "price": AgentOutput(
            agent_name="PriceAgent",
            summary="AAPL price stable",
            evidence=[],
            confidence=0.8,
            data_sources=["test"],
            as_of="2026-01-01",
        )
    }

    result = await host.synthesize(outputs)
    assert isinstance(result, ForumOutput)
    assert isinstance(result.consensus, str)
    assert len(result.consensus.strip()) > 0


def test_supervisor_url_summary_no_sync_llm_needed():
    mock_llm = MagicMock()
    mock_tools = MagicMock()
    mock_cache = MagicMock()
    supervisor = SupervisorAgent(mock_llm, mock_tools, mock_cache)

    mock_tools.fetch_url_content = MagicMock(return_value="x " * 400)
    summary = supervisor._fetch_and_summarize_url("https://example.com/a")

    assert isinstance(summary, str)
    assert len(summary) > 0
    assert len(summary) <= 300
    assert not mock_llm.invoke.called

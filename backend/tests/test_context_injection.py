import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from backend.services.memory import UserProfile
from backend.orchestration.forum import ForumHost, ForumOutput, AgentOutput
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

if __name__ == "__main__":
    asyncio.run(test_forum_host_context_injection())


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

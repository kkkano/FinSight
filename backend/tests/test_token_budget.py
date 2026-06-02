# -*- coding: utf-8 -*-
"""P1-5: 单请求 token 预算上限

每个请求（run）的 LLM token 消耗累计超过预算后，后续 LLM 调用立即失败，
防止单请求无上限烧钱（如深搜递归/反思循环）。
"""
import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.services.llm_usage import (
    TokenBudgetExceededError,
    TokenUsageAccumulator,
    check_token_budget,
    reset_token_accumulator,
    set_token_accumulator,
)


@pytest.fixture
def accumulator():
    """注入一个干净的 accumulator，测试后还原"""
    acc = TokenUsageAccumulator()
    token = set_token_accumulator(acc)
    yield acc
    reset_token_accumulator(token)


class TestCheckTokenBudget:
    def test_no_accumulator_does_not_raise(self):
        """非请求上下文（无 accumulator）不检查预算"""
        check_token_budget()  # 不抛即通过

    def test_under_budget_does_not_raise(self, accumulator, monkeypatch):
        monkeypatch.setenv("LLM_REQUEST_TOKEN_BUDGET", "1000")
        accumulator.add("test-model", prompt=300, completion=200)  # 500 < 1000

        check_token_budget()  # 不抛即通过

    def test_over_budget_raises(self, accumulator, monkeypatch):
        monkeypatch.setenv("LLM_REQUEST_TOKEN_BUDGET", "1000")
        accumulator.add("test-model", prompt=700, completion=400)  # 1100 >= 1000

        with pytest.raises(TokenBudgetExceededError) as exc_info:
            check_token_budget()

        assert exc_info.value.used == 1100
        assert exc_info.value.budget == 1000

    def test_budget_zero_disables_check(self, accumulator, monkeypatch):
        monkeypatch.setenv("LLM_REQUEST_TOKEN_BUDGET", "0")
        accumulator.add("test-model", prompt=999999, completion=999999)

        check_token_budget()  # 预算为 0 = 不限制，不抛

    def test_invalid_budget_env_uses_default(self, accumulator, monkeypatch):
        monkeypatch.setenv("LLM_REQUEST_TOKEN_BUDGET", "not-a-number")
        accumulator.add("test-model", prompt=100, completion=100)

        check_token_budget()  # 默认预算很大，不应抛


class TestLLMRetryBudgetEnforcement:
    """P1-5: ainvoke_with_rate_limit_retry 在超预算时拒绝调用 LLM"""

    def test_call_rejected_when_over_budget(self, accumulator, monkeypatch):
        from backend.services.llm_retry import ainvoke_with_rate_limit_retry

        monkeypatch.setenv("LLM_REQUEST_TOKEN_BUDGET", "1000")
        # 先把预算耗尽
        accumulator.add("test-model", prompt=800, completion=300)

        llm = MagicMock()
        llm.ainvoke = AsyncMock(return_value=MagicMock(content="should not be called"))

        with pytest.raises(TokenBudgetExceededError):
            asyncio.run(
                ainvoke_with_rate_limit_retry(llm, [], acquire_token=False)
            )

        # LLM 不应被调用（预算检查在调用前）
        llm.ainvoke.assert_not_called()

    def test_call_proceeds_when_under_budget(self, accumulator, monkeypatch):
        from backend.services.llm_retry import ainvoke_with_rate_limit_retry

        monkeypatch.setenv("LLM_REQUEST_TOKEN_BUDGET", "100000")
        monkeypatch.setenv("LLM_RATE_LIMIT_RETRY_ENABLED", "false")
        accumulator.add("test-model", prompt=100, completion=100)

        response = MagicMock(content="ok")
        llm = MagicMock()
        llm.model_name = "test-model"
        llm.ainvoke = AsyncMock(return_value=response)

        result = asyncio.run(
            ainvoke_with_rate_limit_retry(llm, [], acquire_token=False)
        )

        assert result is response
        llm.ainvoke.assert_called_once()

import pytest

from backend.orchestration.budget import BudgetManager, BudgetExceededError


def test_budget_tool_calls():
    budget = BudgetManager(max_tool_calls=1, max_rounds=10, max_seconds=60)
    budget.consume_tool_call("tool_a")
    with pytest.raises(BudgetExceededError):
        budget.consume_tool_call("tool_b")


def test_budget_rounds():
    budget = BudgetManager(max_tool_calls=10, max_rounds=1, max_seconds=60)
    budget.consume_round("r1")
    with pytest.raises(BudgetExceededError):
        budget.consume_round("r2")

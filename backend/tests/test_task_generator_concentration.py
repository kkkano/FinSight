import pytest

from backend.services.task_generator import TaskContext, TaskGenerator


@pytest.mark.asyncio
async def test_concentration_uses_market_value_not_shares():
    generator = TaskGenerator()
    context = TaskContext(
        portfolio=[
            {"ticker": "AAPL", "shares": 100, "avg_cost": 150},
            {"ticker": "NVDA", "shares": 100, "avg_cost": 700},
        ],
        snapshots={
            "AAPL": {"price": 150},
            "NVDA": {"price": 800},
        },
    )

    tasks = await generator.generate(context)
    concentration = next((task for task in tasks if task.category == "risk"), None)

    assert concentration is not None
    assert "NVDA" in concentration.reason
    assert "84%" in concentration.reason or "85%" in concentration.reason


@pytest.mark.asyncio
async def test_concentration_falls_back_to_cost_with_reason():
    generator = TaskGenerator()
    context = TaskContext(
        portfolio=[
            {"ticker": "AAPL", "shares": 100, "avg_cost": 200},
            {"ticker": "MSFT", "shares": 100, "avg_cost": 100},
        ],
        snapshots={},
    )

    tasks = await generator.generate(context)
    concentration = next((task for task in tasks if task.category == "risk"), None)

    assert concentration is not None
    assert "AAPL" in concentration.reason
    assert "成本价估算" in concentration.reason

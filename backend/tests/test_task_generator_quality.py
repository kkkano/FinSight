import pytest

from backend.services.task_generator import TaskContext, TaskGenerator


@pytest.mark.asyncio
async def test_empty_context_does_not_generate_generic_filler_task():
    tasks = await TaskGenerator().generate(TaskContext())

    assert tasks == []


@pytest.mark.asyncio
async def test_signal_tasks_have_object_action_and_entry():
    tasks = await TaskGenerator().generate(
        TaskContext(
            portfolio=[{"ticker": "AAPL", "shares": 10, "avg_cost": 180}],
            snapshots={"AAPL": {"price": 170, "change_percent": -4.2}},
        )
    )

    assert tasks
    assert all(task.reason.strip() for task in tasks)
    assert all(task.execution_params or task.report_id or task.action_url != "/workbench" for task in tasks)
    assert all(task.title != "市场新闻速览" for task in tasks)

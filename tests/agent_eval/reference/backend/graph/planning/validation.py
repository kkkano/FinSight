"""在任何外部 I/O 前校验实际执行计划。"""
from __future__ import annotations

from typing import Any, Callable

from backend.graph.plan_ir import PlanIR


def validate_executable_plan(payload: dict[str, Any], *, tool_lookup: Callable | None = None) -> PlanIR:
    plan = PlanIR.model_validate(payload)
    plan.budget.planned_tool_calls = sum(step.kind == "tool" for step in plan.steps)
    plan.budget.planned_agent_calls = sum(step.kind == "agent" for step in plan.steps)
    # 必需义务不会被历史默认估计静默截断；真实调用次数独立计量。
    plan.budget.max_tools = max(plan.budget.max_tools, plan.budget.planned_tool_calls)
    if tool_lookup is None:
        from backend.langchain_tools import get_tool_by_name
        tool_lookup = get_tool_by_name
    tasks = {task.id for task in plan.tasks}
    if len(tasks) != len(plan.tasks):
        raise ValueError("duplicate_plan_task_id")
    steps = {step.id: step for step in plan.steps}
    if len(steps) != len(plan.steps):
        raise ValueError("duplicate_plan_step_id")
    dependencies: dict[str, set[str]] = {}
    for step in plan.steps:
        references = set(step.task_ids + ([step.task_id] if step.task_id else []))
        if tasks and not references <= tasks:
            raise ValueError(f"unknown_plan_task:{step.id}")
        dependencies[step.id] = set(step.depends_on + step.data_dependencies)
        if step.id in dependencies[step.id] or not dependencies[step.id] <= steps.keys():
            raise ValueError(f"invalid_plan_dependency:{step.id}")
        if step.kind == "tool":
            tool = tool_lookup(step.name)
            if tool is None or getattr(tool, "args_schema", None) is None:
                raise ValueError(f"unregistered_plan_tool:{step.name}")
            try:
                tool.args_schema.model_validate(step.inputs)
            except Exception as exc:
                raise ValueError(f"invalid_plan_tool_inputs:{step.id}:{step.name}") from exc
    visited: set[str] = set()
    while len(visited) < len(steps):
        ready = {step_id for step_id, deps in dependencies.items() if step_id not in visited and deps <= visited}
        if not ready:
            raise ValueError("plan_dependency_cycle")
        visited.update(ready)
    return plan

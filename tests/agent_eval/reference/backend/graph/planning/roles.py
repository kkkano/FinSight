# -*- coding: utf-8 -*-
"""为计划中的 Agent 步骤分配确定性的 lead/support 角色。"""
from __future__ import annotations

from typing import Any, Iterable

from backend.agents.profiles import lead_agent_for_operation


def _task_operation(task: dict[str, Any]) -> str:
    operation = task.get("operation")
    if isinstance(operation, dict):
        return str(operation.get("name") or "").strip()
    return str(operation or "").strip()


def assign_agent_roles(
    steps: list[dict[str, Any]],
    *,
    operation: str,
    tasks: Iterable[dict[str, Any]] | None = None,
) -> None:
    """原地写入 role；逐 task 选固定 lead，未入选时由该 task 首个 Agent 兜底。"""
    agent_steps = [
        step
        for step in steps
        if isinstance(step, dict)
        and step.get("kind") == "agent"
        and isinstance(step.get("name"), str)
        and str(step.get("name") or "").strip()
    ]
    if not agent_steps:
        return

    lead_names: set[str] = set()
    normalized_tasks = [task for task in (tasks or []) if isinstance(task, dict)]
    for task in normalized_tasks:
        task_id = str(task.get("task_id") or task.get("id") or "").strip()
        if not task_id:
            continue
        task_steps = []
        for step in agent_steps:
            task_ids = step.get("task_ids") if isinstance(step.get("task_ids"), list) else []
            single_task_id = str(step.get("task_id") or "").strip()
            normalized_ids = {str(item).strip() for item in task_ids if str(item).strip()}
            if single_task_id:
                normalized_ids.add(single_task_id)
            if task_id in normalized_ids:
                task_steps.append(step)
        if not task_steps:
            continue
        preferred = lead_agent_for_operation(_task_operation(task) or operation)
        selected = {str(step.get("name") or "").strip() for step in task_steps}
        lead_names.add(
            preferred
            if preferred in selected
            else str(task_steps[0].get("name") or "").strip()
        )

    if not lead_names:
        preferred = lead_agent_for_operation(operation)
        selected = {str(step.get("name") or "").strip() for step in agent_steps}
        lead_names.add(
            preferred
            if preferred in selected
            else str(agent_steps[0].get("name") or "").strip()
        )

    for step in agent_steps:
        inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
        normalized_inputs = dict(inputs)
        normalized_inputs["role"] = (
            "lead"
            if str(step.get("name") or "").strip() in lead_names
            else "support"
        )
        step["inputs"] = normalized_inputs


__all__ = ["assign_agent_roles"]

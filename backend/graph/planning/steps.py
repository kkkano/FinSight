# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/planner_stub.py（WP3 Task2，零行为变更）。
from __future__ import annotations

import os
import re
import json
from collections.abc import Iterable

from backend.graph.earnings_intent import query_requests_earnings_price_impact
from backend.graph.capability_registry import select_agents_for_request
from backend.graph.coverage_validator import validate_plan_coverage_for_frames
from backend.graph.intent_contract import EXTERNAL_IMPACT_LIGHT_PROFILE, canonical_evidence_kinds
from backend.graph.request_task_contract import reply_contract_disallows_news
from backend.graph.state import GraphState
from backend.graph.plan_ir import PlanIR, PlanBudget, PlanSubject
from backend.graph.understanding_v2 import VALUATION_COMPARE_LIGHT_PROFILE, project_v2_tasks_to_legacy


def _step_task_ids(step: dict) -> list[str]:
    values = step.get("task_ids") if isinstance(step.get("task_ids"), list) else []
    task_ids = [str(value or "").strip() for value in values if str(value or "").strip()]
    single = str(step.get("task_id") or "").strip()
    if single and single not in task_ids:
        task_ids.insert(0, single)
    return task_ids


def _contiguous_groups(steps: list[dict]) -> list[list[dict]]:
    groups: list[list[dict]] = []
    current: list[dict] = []
    current_group: str | None = None
    for step in steps:
        raw_group = step.get("parallel_group")
        group = str(raw_group).strip() if isinstance(raw_group, str) and raw_group.strip() else None
        if group is None:
            if current:
                groups.append(current)
                current = []
                current_group = None
            groups.append([step])
        elif current and current_group == group:
            current.append(step)
        else:
            if current:
                groups.append(current)
            current = [step]
            current_group = group
    if current:
        groups.append(current)
    return groups


def finalize_step_dependencies(steps: list[dict]) -> list[dict]:
    """补齐显式 DAG：同 task 串联，不同 task 的根阶段保持并发。"""
    valid_ids = {str(step.get("id") or "").strip() for step in steps}
    valid_ids.discard("")
    last_ids_by_task: dict[str, list[str]] = {}
    latest_unscoped_group: list[str] = []
    previous_group_ids: list[str] = []

    for group in _contiguous_groups(steps):
        group_ids = [str(step.get("id") or "").strip() for step in group]
        group_ids = [step_id for step_id in group_ids if step_id]
        group_tasks = {task_id for step in group for task_id in _step_task_ids(step)}
        has_unscoped_step = any(not _step_task_ids(step) for step in group)

        for step in group:
            step_id = str(step.get("id") or "").strip()
            raw_dependencies = step.get("depends_on")
            explicit_values: Iterable = raw_dependencies if isinstance(raw_dependencies, list) else []
            explicit: list[str] = []
            for value in explicit_values:
                dependency = str(value or "").strip()
                if dependency and dependency != step_id and dependency in valid_ids and dependency not in explicit:
                    explicit.append(dependency)
            if isinstance(raw_dependencies, list):
                step["depends_on"] = explicit
                continue

            task_ids = _step_task_ids(step)
            inferred: list[str] = []
            for task_id in task_ids:
                for dependency in last_ids_by_task.get(task_id, latest_unscoped_group):
                    if dependency != step_id and dependency not in inferred:
                        inferred.append(dependency)
            if not task_ids:
                inferred = list(previous_group_ids)
            step["depends_on"] = inferred

        for task_id in group_tasks:
            last_ids_by_task[task_id] = [
                str(step.get("id") or "").strip()
                for step in group
                if task_id in _step_task_ids(step) and str(step.get("id") or "").strip()
            ]
        if has_unscoped_step:
            latest_unscoped_group = list(group_ids)
            for task_id in last_ids_by_task:
                last_ids_by_task[task_id] = list(group_ids)
        previous_group_ids = list(group_ids)
    return steps


def _append_tool_step(ctx, 
    name: str,
    inputs: dict,
    *,
    why: str,
    optional: bool = True,
    parallel_group: str | None = None,
    task_ids: list[str] | None = None,
) -> None:
    if name not in ctx.allowed_tools:
        return
    try:
        inputs_key = json.dumps(inputs, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        inputs_key = str(sorted(inputs.items())) if isinstance(inputs, dict) else str(inputs)
    group_key = str(parallel_group or "")
    key = (name, inputs_key, group_key)
    normalized_task_ids = [str(task_id).strip() for task_id in (task_ids or []) if str(task_id).strip()]
    if not normalized_task_ids and isinstance(parallel_group, str) and parallel_group in ctx.ready_task_id_set:
        normalized_task_ids = [parallel_group]
    existing = ctx.step_index.get(key)
    if existing is not None:
        if optional is False:
            existing["optional"] = False
        if normalized_task_ids:
            merged = [
                str(task_id).strip()
                for task_id in (existing.get("task_ids") or [])
                if str(task_id).strip()
            ]
            seen = set(merged)
            for task_id in normalized_task_ids:
                if task_id in seen:
                    continue
                seen.add(task_id)
                merged.append(task_id)
            existing["task_ids"] = merged
            existing["task_id"] = merged[0]
        return
    step = {
        "id": f"s{ctx.step_id}",
        "kind": "tool",
        "name": name,
        "inputs": inputs,
        "why": why,
        "optional": optional,
    }
    if normalized_task_ids:
        step["task_ids"] = normalized_task_ids
        step["task_id"] = normalized_task_ids[0]
    if parallel_group:
        step["parallel_group"] = parallel_group
    ctx.steps.append(step)
    ctx.step_index[key] = step
    ctx.step_id += 1


def _append_agent_step(ctx, 
    name: str,
    inputs: dict,
    *,
    why: str,
    optional: bool = True,
    parallel_group: str | None = None,
    task_ids: list[str] | None = None,
) -> None:
    if name not in ctx.allowed_agents:
        return
    try:
        inputs_key = json.dumps(inputs, ensure_ascii=False, sort_keys=True, default=str)
    except Exception:
        inputs_key = str(sorted(inputs.items())) if isinstance(inputs, dict) else str(inputs)
    group_key = str(parallel_group or "")
    key = (f"agent:{name}", inputs_key, group_key)
    normalized_task_ids = [str(task_id).strip() for task_id in (task_ids or []) if str(task_id).strip()]
    if not normalized_task_ids and isinstance(parallel_group, str) and parallel_group in ctx.ready_task_id_set:
        normalized_task_ids = [parallel_group]
    existing = ctx.step_index.get(key)
    if existing is not None:
        if optional is False:
            existing["optional"] = False
        if normalized_task_ids:
            merged = [
                str(task_id).strip()
                for task_id in (existing.get("task_ids") or [])
                if str(task_id).strip()
            ]
            seen = set(merged)
            for task_id in normalized_task_ids:
                if task_id in seen:
                    continue
                seen.add(task_id)
                merged.append(task_id)
            existing["task_ids"] = merged
            existing["task_id"] = merged[0]
        return
    # 计划步骤保留覆盖校验和渲染所需的 evidence/time scope 元数据。
    # 注意 dedup key 用原始 inputs 计算，保持既有合并行为不变。
    brief_task = next(
        (ctx.ready_tasks_by_id[tid] for tid in normalized_task_ids if tid in ctx.ready_tasks_by_id),
        None,
    )
    enriched_inputs = dict(inputs)
    if brief_task is not None:
        operation_obj = brief_task.get("operation")
        operation_name = (
            str(operation_obj.get("name") or "")
            if isinstance(operation_obj, dict)
            else str(operation_obj or "")
        )
        operation_params = (
            operation_obj.get("params")
            if isinstance(operation_obj, dict) and isinstance(operation_obj.get("params"), dict)
            else {}
        )
        task_params = brief_task.get("params") if isinstance(brief_task.get("params"), dict) else {}
        enriched_inputs.setdefault("objective", operation_name)
        enriched_inputs.setdefault(
            "required_evidence", list(brief_task.get("required_evidence") or [])
        )
        enriched_inputs.setdefault(
            "time_scope",
            dict(operation_params.get("time_scope") or task_params.get("time_scope") or {}),
        )
    step = {
        "id": f"s{ctx.step_id}",
        "kind": "agent",
        "name": name,
        "inputs": enriched_inputs,
        "why": why,
        "optional": optional,
    }
    if normalized_task_ids:
        step["task_ids"] = normalized_task_ids
        step["task_id"] = normalized_task_ids[0]
    if parallel_group:
        step["parallel_group"] = parallel_group
    ctx.steps.append(step)
    ctx.step_index[key] = step
    ctx.step_id += 1


def _has_step(ctx, kind: str, name: str) -> bool:
    return any(step.get("kind") == kind and step.get("name") == name for step in ctx.steps)

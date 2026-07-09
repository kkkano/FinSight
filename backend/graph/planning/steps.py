# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/planner_stub.py（WP3 Task2，零行为变更）。
from __future__ import annotations

import os
import re
import json

from backend.graph.earnings_intent import query_requests_earnings_price_impact
from backend.graph.capability_registry import select_agents_for_request
from backend.graph.coverage_validator import validate_plan_coverage_for_frames
from backend.graph.intent_contract import EXTERNAL_IMPACT_LIGHT_PROFILE, canonical_evidence_kinds
from backend.graph.request_task_contract import reply_contract_disallows_news
from backend.graph.state import GraphState
from backend.graph.plan_ir import PlanIR, PlanBudget, PlanSubject
from backend.graph.understanding_v2 import VALUATION_COMPARE_LIGHT_PROFILE, project_v2_tasks_to_legacy


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
    # WP2-T6: agent step 携带 AgentBrief 素材（objective/required_evidence/time_scope）。
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

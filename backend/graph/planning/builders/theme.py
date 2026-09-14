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
from backend.graph.planning.steps import _append_tool_step
from backend.graph.planning.util import _task_id


def _append_theme_task_steps(ctx, task: dict, *, group: str) -> None:
    task_ids = [_task_id(ctx, task)]
    task_query = str(task.get("subject_label") or ctx.query).strip() or ctx.query
    _append_tool_step(ctx, 
        "get_current_datetime",
        {},
        why="主题任务：获取当前日期，限定近期事件语境。",
        optional=True,
        parallel_group=group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "get_authoritative_media_news",
        {"query": ctx.query, "max_results": 6, "authoritative_only": True},
        why="主题任务：优先用权威媒体验证行业事件。",
        optional=True,
        parallel_group=group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "search",
        {"query": task_query},
        why="主题任务：检索行业/主题的近期事件与影响。",
        optional=False,
        parallel_group=group,
        task_ids=task_ids,
    )

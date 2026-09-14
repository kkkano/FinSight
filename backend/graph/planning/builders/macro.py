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
from backend.graph.planning.util import _macro_query_for_task, _task_id, _task_operation_name


def _append_macro_task_steps(ctx, task: dict, *, group: str) -> None:
    op_name = _task_operation_name(ctx, task)
    if op_name == "qa" and ctx.output_mode != "investment_report":
        return
    task_ids = [_task_id(ctx, task)]
    task_query = _macro_query_for_task(ctx, task)
    _append_tool_step(ctx, 
        "get_current_datetime",
        {},
        why="宏观任务：获取当前日期，防止把旧政策当成当前事实。",
        optional=True,
        parallel_group=group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "get_official_macro_releases",
        {"query": ctx.query, "max_results": 8},
        why="宏观任务：优先检查官方宏观/央行发布。",
        optional=False,
        parallel_group=group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "get_authoritative_media_news",
        {"query": task_query, "max_results": 6, "authoritative_only": True},
        why="宏观任务：用权威媒体交叉验证市场影响。",
        optional=True,
        parallel_group=group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "search",
        {"query": task_query},
        why="宏观任务：补充开放搜索证据。",
        optional=True,
        parallel_group=group,
        task_ids=task_ids,
    )

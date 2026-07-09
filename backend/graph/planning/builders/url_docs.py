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
from backend.graph.planning.util import _task_id, _task_urls


def _append_document_task_steps(ctx, task: dict, *, group: str) -> None:
    urls = _task_urls(ctx, task)
    for url in urls:
        _append_tool_step(ctx, 
            "fetch_url_content",
            {"url": url, "max_length": 6000},
            why="文档任务已给出 URL：读取页面正文后再作为证据使用。",
            optional=False,
            parallel_group=group,
            task_ids=[_task_id(ctx, task)],
        )
    if urls:
        return
    task_query = str(task.get("subject_label") or ctx.query).strip() or ctx.query
    _append_tool_step(ctx, 
        "search",
        {"query": task_query},
        why="文档/新闻任务缺少可抓取 URL：用搜索补足来源线索。",
        optional=True,
        parallel_group=group,
        task_ids=[_task_id(ctx, task)],
    )

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
from backend.graph.planning.util import _task_id, _task_tickers


def _append_portfolio_task_steps(ctx, task: dict, *, group: str) -> None:
    task_ids = [_task_id(ctx, task)]
    tickers_for_task = _task_tickers(ctx, task)
    params = task.get("params") if isinstance(task.get("params"), dict) else {}
    raw_positions = params.get("positions") if isinstance(params.get("positions"), list) else []
    positions = [
        item
        for item in raw_positions
        if isinstance(item, dict) and str(item.get("ticker") or "").strip()
    ]
    if not positions and tickers_for_task:
        weight = round(1.0 / len(tickers_for_task), 4)
        positions = [{"ticker": ticker, "weight": weight} for ticker in tickers_for_task[:8]]
    if positions:
        _append_tool_step(ctx, 
            "get_factor_exposure",
            {"positions": positions, "lookback_days": 252},
            why="组合任务：估算持仓因子暴露。",
            optional=True,
            parallel_group=group,
            task_ids=task_ids,
        )
        _append_tool_step(ctx, 
            "run_portfolio_stress_test",
            {"positions": positions, "lookback_days": 252},
            why="组合任务：估算压力情景下的组合敏感性。",
            optional=True,
            parallel_group=group,
            task_ids=task_ids,
        )
    _append_tool_step(ctx, 
        "search",
        {"query": ctx.query},
        why="组合任务：检索影响持仓的近期市场事件。",
        optional=True,
        parallel_group=group,
        task_ids=task_ids,
    )

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
from backend.graph.planning.util import (
    _holder_cik_or_name_from_query,
    _sec_holdings_enabled,
    _task_id,
    _task_operation_name,
    _task_operation_params,
    _task_tickers,
)


def _append_holdings_task_steps(ctx, task: dict, *, group: str) -> None:
    if not _sec_holdings_enabled():
        return
    if _task_operation_name(ctx, task) != "holdings":
        return

    task_ids = [_task_id(ctx, task)]
    tickers_for_task = _task_tickers(ctx, task)
    subject_for_task = str(task.get("subject_type") or "unknown").strip().lower()
    params = {**_task_operation_params(ctx, task)}
    task_params = task.get("params")
    if isinstance(task_params, dict):
        params.update(task_params)
    holder = str(params.get("holder_cik_or_name") or _holder_cik_or_name_from_query(ctx.query) or "").strip()
    quarter = str(params.get("quarter") or "").strip()

    if subject_for_task == "portfolio":
        raw_positions = params.get("positions") if isinstance(params.get("positions"), list) else []
        positions = [
            item
            for item in raw_positions
            if isinstance(item, dict) and str(item.get("ticker") or "").strip()
        ]
        if not positions and tickers_for_task:
            weight = round(1.0 / len(tickers_for_task), 4)
            positions = [{"ticker": ticker, "weight": weight} for ticker in tickers_for_task[:8]]
        if positions and holder:
            inputs: dict = {"positions": positions, "holder_cik_or_name": holder}
            if quarter:
                inputs["quarter"] = quarter
            _append_tool_step(ctx, 
                "get_holdings_overlap",
                inputs,
                why="持仓重叠任务：用公开 13F 披露对比用户组合与机构持仓。",
                optional=False,
                parallel_group=group,
                task_ids=task_ids,
            )
        elif holder:
            inputs = {"cik_or_name": holder, "limit": 100}
            if quarter:
                inputs["quarter"] = quarter
            _append_tool_step(ctx, 
                "get_institutional_holdings",
                inputs,
                why="持仓任务缺少可对比组合：先读取机构公开 13F 持仓。",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
        return

    if subject_for_task in {"company", "index", "commodity"}:
        if holder:
            inputs = {"cik_or_name": holder, "limit": 100}
            if quarter:
                inputs["quarter"] = quarter
            _append_tool_step(ctx, 
                "get_institutional_holdings",
                inputs,
                why="持仓任务：读取指定机构的公开 13F 持仓。",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
        for ticker in tickers_for_task[:6]:
            _append_tool_step(ctx, 
                "get_insider_transactions",
                {"ticker": ticker, "days": 180, "limit": 50},
                why=f"{ticker} 持仓任务：读取公开 Form 4 内部人交易披露。",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
            _append_tool_step(ctx, 
                "get_institution_holdings_by_ticker",
                {"ticker": ticker, "limit": 50},
                why=f"{ticker} 持仓任务：读取公开 13F 机构持有人线索。",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )

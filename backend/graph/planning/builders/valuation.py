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
from backend.graph.planning.steps import _append_agent_step, _append_tool_step


def _append_valuation_sanity_steps(ctx, 
    ticker: str,
    *,
    group: str | None = None,
    task_ids: list[str] | None = None,
) -> None:
    evidence_group = group or "valuation_evidence"
    _append_tool_step(ctx, 
        "get_stock_price",
        {"ticker": ticker},
        why=f"{ticker} 估值合理性任务：获取当前价格/市值作为估值锚点。",
        optional=False,
        parallel_group=evidence_group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "get_company_info",
        {"ticker": ticker},
        why=f"{ticker} 估值合理性任务：补充公司基础信息、市值和估值上下文。",
        optional=True,
        parallel_group=evidence_group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "get_sec_company_facts_quarterly",
        {"ticker": ticker, "limit": 8},
        why=f"{ticker} 估值合理性任务：读取季度收入/净利用于增长和倍数计算。",
        optional=True,
        parallel_group=evidence_group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "get_earnings_estimates",
        {"ticker": ticker},
        why=f"{ticker} 估值合理性任务：补充 forward earnings 预期。",
        optional=True,
        parallel_group=evidence_group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "get_eps_revisions",
        {"ticker": ticker},
        why=f"{ticker} 估值合理性任务：补充 EPS 上修/下修，判断增长预期是否支撑估值。",
        optional=True,
        parallel_group=evidence_group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "get_technical_snapshot",
        {"ticker": ticker},
        why=f"{ticker} 估值合理性任务：补充趋势/动量，避免只用静态估值判断。",
        optional=True,
        parallel_group=evidence_group,
        task_ids=task_ids,
    )
    agent_group = f"{evidence_group}_agents"
    _append_tool_step(ctx, 
        "run_python_compute",
        {
            "dataset_refs": [
                "step:get_stock_price",
                "step:get_company_info",
                "step:get_sec_company_facts_quarterly",
                "step:get_earnings_estimates",
            ],
            "operation": "valuation_sanity",
            "params": {"ticker": ticker},
        },
        why=f"{ticker} 估值合理性任务：用已采集数据计算 P/S、P/E、增长率等表格指标。",
        optional=True,
        parallel_group=agent_group,
        task_ids=task_ids,
    )
    _append_agent_step(ctx, 
        "fundamental_agent",
        {"query": ctx.query, "ticker": ticker},
        why=f"{ticker} 估值合理性任务：运行 fundamental_agent 解释增长、盈利质量和估值支撑。",
        optional=False,
        parallel_group=agent_group,
        task_ids=task_ids,
    )
    _append_agent_step(ctx, 
        "technical_agent",
        {"query": ctx.query, "ticker": ticker},
        why=f"{ticker} 估值合理性任务：运行 technical_agent 检查市场是否已透支预期。",
        optional=True,
        parallel_group=agent_group,
        task_ids=task_ids,
    )
    _append_agent_step(ctx, 
        "risk_agent",
        {"query": ctx.query, "ticker": ticker},
        why=f"{ticker} 估值合理性任务：运行 risk_agent 给出估值回撤和预期证伪风险。",
        optional=True,
        parallel_group=agent_group,
        task_ids=task_ids,
    )

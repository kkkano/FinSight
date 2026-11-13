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


def _append_earnings_performance_steps(ctx, 
    ticker: str,
    *,
    group: str | None = None,
    task_ids: list[str] | None = None,
) -> None:
    evidence_group = group or "earnings_evidence"
    _append_tool_step(ctx, 
        "get_company_info",
        {"ticker": ticker},
        why=f"{ticker} 财报表现任务：补充公司基础信息，避免只列新闻标题。",
        optional=True,
        parallel_group=evidence_group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "get_sec_company_facts_quarterly",
        {"ticker": ticker, "limit": 8},
        why=f"{ticker} 财报表现任务：读取季度营收、净利和 EPS 等事实指标。",
        optional=True,
        parallel_group=evidence_group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "get_earnings_estimates",
        {"ticker": ticker},
        why=f"{ticker} 财报表现任务：补充盈利预期和下一季共识。",
        optional=True,
        parallel_group=evidence_group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "get_eps_revisions",
        {"ticker": ticker},
        why=f"{ticker} 财报表现任务：补充 EPS 上修/下修趋势。",
        optional=True,
        parallel_group=evidence_group,
        task_ids=task_ids,
    )
    if not ctx.news_disallowed:
        _append_tool_step(ctx, 
            "get_company_news",
            {"ticker": ticker},
            why=f"{ticker} 财报表现任务：补充近期财报新闻、指引和市场反应。",
            optional=True,
            parallel_group=evidence_group,
            task_ids=task_ids,
        )
        _append_tool_step(ctx, 
            "get_authoritative_media_news",
            {"query": f"{ticker} latest earnings results", "max_results": 6, "authoritative_only": True},
            why=f"{ticker} 财报表现任务：用权威媒体交叉验证财报要点。",
            optional=True,
            parallel_group=evidence_group,
            task_ids=task_ids,
        )
        _append_tool_step(ctx, 
            "get_earnings_call_transcripts",
            {"ticker": ticker, "limit": 3},
            why=f"{ticker} 财报表现任务：补充电话会 transcript 以验证管理层指引。",
            optional=True,
            parallel_group=evidence_group,
            task_ids=task_ids,
        )
    agent_group = f"{evidence_group}_agents"
    _append_agent_step(ctx, 
        "fundamental_agent",
        {"query": ctx.query, "ticker": ticker},
        why=f"{ticker} 财报表现任务：运行 fundamental_agent 汇总财务表现、预期和质量风险。",
        optional=False,
        parallel_group=agent_group,
        task_ids=task_ids,
    )
    _append_agent_step(ctx, 
        "news_agent",
        {"query": ctx.query, "ticker": ticker},
        why=f"{ticker} 财报表现任务：运行 news_agent 区分财报催化和噪音。",
        optional=True,
        parallel_group=agent_group,
        task_ids=task_ids,
    )


def _append_earnings_impact_steps(ctx, 
    ticker: str,
    *,
    group: str | None = None,
    task_ids: list[str] | None = None,
) -> None:
    evidence_group = group or "earnings_impact_evidence"
    _append_tool_step(ctx, 
        "get_stock_price",
        {"ticker": ticker},
        why=f"{ticker} 财报影响股价任务：获取当前价格/涨跌幅作为市场反应锚点。",
        optional=False,
        parallel_group=evidence_group,
        task_ids=task_ids,
    )
    _append_tool_step(ctx, 
        "analyze_historical_drawdowns",
        {"ticker": ticker},
        why=f"{ticker} 财报影响股价任务：补充历史波动和回撤风险。",
        optional=True,
        parallel_group=evidence_group,
        task_ids=task_ids,
    )
    _append_earnings_performance_steps(ctx, ticker, group=evidence_group, task_ids=task_ids)
    _append_tool_step(ctx, 
        "run_python_compute",
        {
            "dataset_refs": [
                "step:get_stock_price",
                "step:get_sec_company_facts_quarterly",
                "step:get_earnings_estimates",
                "step:get_eps_revisions",
            ],
            "operation": "growth_rates",
            "params": {"metric": "revenue", "ticker": ticker},
        },
        why=f"{ticker} 财报影响股价任务：用已采集财报事实计算增长/预期变化指标，给综合回答提供数值锚点。",
        optional=True,
        parallel_group=f"{evidence_group}_agents",
        task_ids=task_ids,
    )
    _append_agent_step(ctx, 
        "risk_agent",
        {"query": ctx.query, "ticker": ticker},
        why=f"{ticker} 财报影响股价任务：运行 risk_agent 给出价格反应的证伪和回撤风险。",
        optional=True,
        parallel_group=f"{evidence_group}_agents",
        task_ids=task_ids,
    )

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
from backend.graph.planning.steps import _append_agent_step, _append_tool_step, _has_step


def _append_report_mode_enrichment_steps(ctx) -> None:
    if ctx.output_mode != "investment_report" or not ctx.primary_ticker:
        return

    deep_required = bool(ctx.is_deep_financial_report)
    task_ids = [
        str(task_id).strip()
        for task_id in sorted(ctx.ready_task_id_set)
        if str(task_id).strip()
    ] or None

    if not _has_step(ctx, "tool", "get_stock_price"):
        _append_tool_step(ctx, 
            "get_stock_price",
            {"ticker": ctx.primary_ticker},
            why="研报模式：补充当前价格作为估值、风险和结论锚点。",
            optional=True,
            parallel_group="report_evidence",
            task_ids=task_ids,
        )
    _append_tool_step(ctx, 
        "analyze_historical_drawdowns",
        {"ticker": ctx.primary_ticker},
        why="研报模式：补充历史回撤信息用于风险章节。",
        optional=True,
        parallel_group="report_evidence",
        task_ids=task_ids,
    )

    if "get_local_market_filings" in ctx.allowed_tools:
        _append_tool_step(ctx, 
            "get_local_market_filings",
            {"ticker": ctx.primary_ticker, "limit": 8},
            why="研报模式：补充本地交易所公告/定期报告证据。",
            optional=not deep_required,
            parallel_group="report_evidence",
            task_ids=task_ids,
        )
    else:
        _append_tool_step(ctx, 
            "get_sec_filings",
            {"ticker": ctx.primary_ticker, "forms": "10-K,10-Q", "limit": 6},
            why="研报模式：补充 SEC EDGAR 10-K/10-Q filing evidence。",
            optional=not deep_required,
            parallel_group="report_evidence",
            task_ids=task_ids,
        )
        _append_tool_step(ctx, 
            "get_sec_company_facts_quarterly",
            {"ticker": ctx.primary_ticker, "limit": 8},
            why="研报模式：补充 SEC CompanyFacts 季度财务指标。",
            optional=not deep_required,
            parallel_group="report_evidence",
            task_ids=task_ids,
        )
        _append_tool_step(ctx, 
            "get_sec_material_events",
            {"ticker": ctx.primary_ticker, "limit": 5},
            why="研报模式：补充 SEC 8-K 重大事件证据。",
            optional=True,
            parallel_group="report_evidence",
            task_ids=task_ids,
        )

    if deep_required:
        _append_tool_step(ctx, 
            "get_authoritative_media_news",
            {"query": f"{ctx.primary_ticker} earnings outlook", "max_results": 6, "authoritative_only": True},
            why="深度研报：强制补充权威媒体交叉验证。",
            optional=False,
            parallel_group="report_evidence",
            task_ids=task_ids,
        )
        _append_tool_step(ctx, 
            "get_earnings_call_transcripts",
            {"ticker": ctx.primary_ticker, "limit": 5},
            why="深度研报：补充业绩电话会 transcript evidence。",
            optional=False,
            parallel_group="report_evidence",
            task_ids=task_ids,
        )

    policy_agent_selection = ctx.policy.get("agent_selection") if isinstance(ctx.policy, dict) else {}
    selected_agents: list[str] = []
    if isinstance(policy_agent_selection, dict):
        selected_agents = [
            str(name)
            for name in (policy_agent_selection.get("selected") or [])
            if isinstance(name, str) and name in ctx.allowed_agents
        ]
    if not selected_agents:
        ordered_agents = [
            "price_agent",
            "news_agent",
            "fundamental_agent",
            "technical_agent",
            "macro_agent",
            "risk_agent",
            "deep_search_agent",
        ]
        selected_agents = [name for name in ordered_agents if name in ctx.allowed_agents]
    agent_parallel_group = "report_agents" if len(selected_agents) > 1 else None
    for agent_name in selected_agents:
        _append_agent_step(ctx, 
            agent_name,
            {"query": ctx.query, "ticker": ctx.primary_ticker},
            why=f"研报模式：运行 {agent_name} 产出结构化摘要和证据。",
            optional=True,
            parallel_group=agent_parallel_group,
            task_ids=task_ids,
        )

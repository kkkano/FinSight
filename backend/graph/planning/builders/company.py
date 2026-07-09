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
from backend.graph.planning.builders.earnings import (
    _append_earnings_impact_steps,
    _append_earnings_performance_steps,
)
from backend.graph.planning.builders.evidence import _append_evidence_steps_for_ticker
from backend.graph.planning.builders.valuation import _append_valuation_sanity_steps
from backend.graph.planning.steps import _append_agent_step, _append_tool_step
from backend.graph.planning.util import (
    _qa_needs_live_context,
    _should_use_performance_compare,
    _task_id,
    _task_operation_name,
    _task_operation_params,
    _task_required_evidence,
    _task_tickers,
)


def _append_company_task_steps(ctx, task: dict, *, group: str) -> None:
    op_name = _task_operation_name(ctx, task)
    params = _task_operation_params(ctx, task)
    tickers_for_task = _task_tickers(ctx, task)
    task_ids = [_task_id(ctx, task)]
    if op_name == "backtest":
        ticker = tickers_for_task[0] if tickers_for_task else ctx.primary_ticker
        strategy = str(params.get("strategy") or "ma_cross").strip() or "ma_cross"
        _append_tool_step(ctx, 
            "run_strategy_backtest",
            {
                "ticker": ticker or "",
                "strategy": strategy,
                "params": dict(params.get("strategy_params") or params.get("params") or {}),
                "initial_cash": float(params.get("initial_cash") or 100000.0),
                "t_plus_one": bool(params.get("t_plus_one", True)),
            },
            why="Backtest workflow action: execute the requested strategy and return performance metrics.",
            optional=False,
            parallel_group=group,
            task_ids=task_ids,
        )
        return
    if op_name == "compare" and len(tickers_for_task) >= 2:
        if _should_use_performance_compare(ctx, task):
            mapping = {ticker: ticker for ticker in tickers_for_task[:6]}
            _append_tool_step(ctx, 
                "get_performance_comparison",
                {"tickers": mapping},
                why="多标的对比任务：取标准化历史表现数据。",
                optional=False,
                parallel_group=group,
                task_ids=task_ids,
            )
        if ctx.output_mode == "investment_report":
            for ticker in tickers_for_task[:6]:
                _append_tool_step(ctx, 
                    "get_stock_price",
                    {"ticker": ticker},
                    why=f"{ticker} 对比研报：补充当前价格作为报告锚点。",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(ctx, 
                    "get_company_news",
                    {"ticker": ticker},
                    why=f"{ticker} 对比研报：补充近期新闻用于事件解释。",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(ctx, 
                    "get_company_info",
                    {"ticker": ticker},
                    why=f"{ticker} 对比研报：补充公司基础信息。",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
        return

    for ticker in tickers_for_task[:6]:
        live_qa = op_name == "qa" and _qa_needs_live_context(ctx)
        required_evidence = _task_required_evidence(ctx, task)
        if required_evidence:
            _append_evidence_steps_for_ticker(ctx, 
                ticker,
                required_evidence,
                group=group,
                task_ids=task_ids,
                evidence_profile=str(
                    params.get("evidence_profile") or params.get("budget_profile") or ""
                ).strip().lower(),
            )
            continue
        if op_name == "earnings_impact" or query_requests_earnings_price_impact(ctx.query):
            _append_earnings_impact_steps(ctx, ticker, group=group, task_ids=task_ids)
            continue
        if op_name == "earnings_performance":
            _append_earnings_performance_steps(ctx, ticker, group=group, task_ids=task_ids)
            continue
        if op_name == "valuation_sanity":
            _append_valuation_sanity_steps(ctx, ticker, group=group, task_ids=task_ids)
            continue
        if op_name == "investment_opinion":
            valuation_focus = (
                str(params.get("evidence_focus") or "").strip().lower() == "valuation"
                or str(params.get("evidence_profile") or "").strip().lower() == VALUATION_COMPARE_LIGHT_PROFILE
                or str(params.get("budget_profile") or "").strip().lower() == VALUATION_COMPARE_LIGHT_PROFILE
            )
            valuation_lightweight = (
                str(params.get("evidence_profile") or "").strip().lower() == VALUATION_COMPARE_LIGHT_PROFILE
                or str(params.get("budget_profile") or "").strip().lower() == VALUATION_COMPARE_LIGHT_PROFILE
            )
            _append_tool_step(ctx, 
                "get_stock_price",
                {"ticker": ticker},
                why=f"{ticker} 投资观点任务：获取当前价格/涨跌幅作为方向判断锚点。",
                optional=False,
                parallel_group=group,
                task_ids=task_ids,
            )
            if valuation_focus:
                _append_tool_step(ctx, 
                    "get_company_info",
                    {"ticker": ticker},
                    why=f"{ticker} valuation evidence: add company and valuation context.",
                    optional=False,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                _append_tool_step(ctx, 
                    "get_earnings_estimates",
                    {"ticker": ticker},
                    why=f"{ticker} valuation evidence: add earnings expectations for multiple sanity.",
                    optional=False,
                    parallel_group=group,
                    task_ids=task_ids,
                )
                if not valuation_lightweight:
                    _append_agent_step(ctx, 
                        "fundamental_agent",
                        {"query": ctx.query, "ticker": ticker},
                        why=f"{ticker} valuation evidence: run fundamental_agent for valuation support.",
                        optional=False,
                        parallel_group=f"{group}_valuation_agents" if group else "valuation_agents",
                        task_ids=task_ids,
                    )
                continue
            _append_tool_step(ctx, 
                "get_technical_snapshot",
                {"ticker": ticker},
                why=f"{ticker} 投资观点任务：获取趋势、动量、支撑阻力等技术证据。",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
            _append_tool_step(ctx, 
                "get_company_news",
                {"ticker": ticker},
                why=f"{ticker} 投资观点任务：获取近期新闻和催化事件，避免只看价格。",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
            _append_tool_step(ctx, 
                "get_company_info",
                {"ticker": ticker},
                why=f"{ticker} 投资观点任务：补充公司基础信息和估值上下文。",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
            _append_tool_step(ctx, 
                "get_earnings_estimates",
                {"ticker": ticker},
                why=f"{ticker} 投资观点任务：补充盈利预期，避免只给消息面判断。",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
            _append_tool_step(ctx, 
                "get_eps_revisions",
                {"ticker": ticker},
                why=f"{ticker} 投资观点任务：补充 EPS 修正方向，判断基本面预期是否改善。",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
            _append_tool_step(ctx, 
                "analyze_historical_drawdowns",
                {"ticker": ticker},
                why=f"{ticker} 投资观点任务：补充历史回撤和波动风险。",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )
            agent_group = f"{group}_opinion_agents" if group else "opinion_agents"
            _append_agent_step(ctx, 
                "technical_agent",
                {"query": ctx.query, "ticker": ticker},
                why=f"{ticker} 投资观点任务：运行 technical_agent 给出趋势、动量和关键价位。",
                optional=False,
                parallel_group=agent_group,
                task_ids=task_ids,
            )
            _append_agent_step(ctx, 
                "fundamental_agent",
                {"query": ctx.query, "ticker": ticker},
                why=f"{ticker} 投资观点任务：运行 fundamental_agent 给出基本面和估值证据。",
                optional=True,
                parallel_group=agent_group,
                task_ids=task_ids,
            )
            _append_agent_step(ctx, 
                "risk_agent",
                {"query": ctx.query, "ticker": ticker},
                why=f"{ticker} 投资观点任务：运行 risk_agent 给出回撤、波动和证伪风险。",
                optional=True,
                parallel_group=agent_group,
                task_ids=task_ids,
            )
            _append_agent_step(ctx, 
                "news_agent",
                {"query": ctx.query, "ticker": ticker},
                why=f"{ticker} 投资观点任务：运行 news_agent 区分催化事件和噪音。",
                optional=True,
                parallel_group=agent_group,
                task_ids=task_ids,
            )
            continue
        if op_name in {"price", "technical", "analyze_impact", "daily_brief"} or live_qa:
            _append_tool_step(ctx, 
                "get_stock_price",
                {"ticker": ticker},
                why=f"{ticker} 任务：获取价格/涨跌幅作为回答锚点。",
                optional=op_name not in {"price", "technical"},
                parallel_group=group,
                task_ids=task_ids,
            )
        if op_name == "technical":
            _append_tool_step(ctx, 
                "get_technical_snapshot",
                {"ticker": ticker},
                why=f"{ticker} 技术面任务：获取技术指标快照。",
                optional=False,
                parallel_group=group,
                task_ids=task_ids,
            )
            _append_agent_step(ctx, 
                "technical_agent",
                {"query": ctx.query, "ticker": ticker},
                why=f"{ticker} 技术面任务：运行 technical_agent 综合 K 线、报价、期权和情绪证据。",
                optional=False,
                parallel_group=group,
                task_ids=task_ids,
            )
        if (op_name in {"fetch", "analyze_impact", "daily_brief"} or live_qa) and not ctx.news_disallowed:
            news_inputs = {"ticker": ticker}
            if ctx.output_mode == "brief":
                news_inputs.update({"fast": True, "limit": 3})
            _append_tool_step(ctx, 
                "get_company_news",
                news_inputs,
                why=f"{ticker} 任务：获取相关新闻用于事件解释。",
                optional=op_name not in {"fetch", "analyze_impact"},
                parallel_group=group,
                task_ids=task_ids,
            )
            if ctx.requires_links or bool(params.get("include_links")):
                _append_tool_step(ctx, 
                    "get_authoritative_media_news",
                    {
                        "query": f"{ticker} {ctx.query}".strip(),
                        "max_results": 6,
                        "authoritative_only": False,
                    },
                    why=f"{ticker} link-required news task: supplement article URLs from media/RSS feeds.",
                    optional=True,
                    parallel_group=group,
                    task_ids=task_ids,
                )
        fast_brief_router_task = (
            ctx.output_mode == "brief"
            and str(task.get("reason") or "").strip()
            in {"conversation_router_task_hint", "conversation_router_task_hint_support"}
        )
        if (op_name == "analyze_impact" and not fast_brief_router_task) or (
            op_name == "qa" and ctx.output_mode == "investment_report"
        ):
            _append_tool_step(ctx, 
                "get_company_info",
                {"ticker": ticker},
                why=f"{ticker} 任务：补充公司基础信息，避免只看新闻标题。",
                optional=True,
                parallel_group=group,
                task_ids=task_ids,
            )

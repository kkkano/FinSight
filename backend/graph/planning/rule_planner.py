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
from backend.graph.planning.builders.company import _append_company_task_steps
from backend.graph.planning.builders.earnings import (
    _append_earnings_impact_steps,
    _append_earnings_performance_steps,
)
from backend.graph.planning.builders.holdings import _append_holdings_task_steps
from backend.graph.planning.builders.macro import _append_macro_task_steps
from backend.graph.planning.builders.portfolio import _append_portfolio_task_steps
from backend.graph.planning.builders.theme import _append_theme_task_steps
from backend.graph.planning.builders.url_docs import _append_document_task_steps
from backend.graph.planning.builders.valuation import _append_valuation_sanity_steps
from backend.graph.planning.context import PlanContext
from backend.graph.planning.frames import (
    _append_request_frame_steps,
    _frame_required_evidence,
    _frame_required_results,
    _frame_subject,
    _frame_tickers,
    _request_frames_authoritatively_need_no_plan_steps,
)
from backend.graph.planning.report_mode import _append_report_mode_enrichment_steps
from backend.graph.planning.steps import _append_tool_step
from backend.graph.planning.util import (
    _contains_any,
    _plan_subject_payload,
    _plan_task_summary,
    _should_use_performance_compare,
    _task_id,
    _task_operation_name,
    _task_tickers,
    _task_urls,
)


# 任务级 builder 注册表：subject_type -> builder（签名 (ctx, task, *, group)）。
# 行为保真备注：holdings 按 operation 名、URL 存在性两个前置守卫不进表（原分支顺序保留）；
# 未登记类型（unknown 等）= 原 elif 链落空 no-op（spec 草表的 unknown->company 与现实不符，见 Deviations）。
TASK_BUILDERS = {
    "company": _append_company_task_steps,
    "index": _append_company_task_steps,
    "commodity": _append_company_task_steps,
    "macro": _append_macro_task_steps,
    "portfolio": _append_portfolio_task_steps,
    "theme": _append_theme_task_steps,
    "research_doc": _append_document_task_steps,
    "filing": _append_document_task_steps,
    "news_item": _append_document_task_steps,
    "news_set": _append_document_task_steps,
}


def _append_understanding_task_steps(ctx) -> bool:
    if not ctx.ready_tasks:
        return False
    if len(ctx.ready_tasks) == 1:
        task = ctx.ready_tasks[0]
        subject_for_task = str(task.get("subject_type") or "unknown").strip().lower()
        if _task_operation_name(ctx, task) == "holdings":
            _append_holdings_task_steps(ctx, task, group=_task_id(ctx, task) or "task_1")
            return True
        if _task_urls(ctx, task) or subject_for_task in {"research_doc", "filing", "news_item", "news_set"}:
            _append_document_task_steps(ctx, task, group=_task_id(ctx, task) or "task_1")
            return True
        builder = TASK_BUILDERS.get(subject_for_task)
        if builder is not None:
            builder(ctx, task, group=_task_id(ctx, task) or "task_1")
            return True
        return False
    if all(
        _task_subject_type in {"company", "index", "commodity"}
        and _task_operation_name(ctx, task) == "price"
        for task in ctx.ready_tasks
        for _task_subject_type in [str(task.get("subject_type") or "unknown").strip().lower()]
    ):
        for task in ctx.ready_tasks[:12]:
            _append_company_task_steps(ctx, task, group="price_quotes")
        return True
    for idx, task in enumerate(ctx.ready_tasks[:12], 1):
        subject_for_task = str(task.get("subject_type") or "unknown").strip().lower()
        group = (
            "brief_data"
            if ctx.output_mode == "brief" and subject_for_task in {"company", "index", "commodity"}
            else (_task_id(ctx, task) or f"task_{idx}")
        )
        if _task_operation_name(ctx, task) == "holdings":
            _append_holdings_task_steps(ctx, task, group=group)
        elif _task_urls(ctx, task):
            _append_document_task_steps(ctx, task, group=group)
        elif (builder := TASK_BUILDERS.get(subject_for_task)) is not None:
            builder(ctx, task, group=group)
    return True

def rule_based_planner(state: GraphState) -> dict:
    """规则式生产 planner（原名 planner_stub——它从来不是 stub）。

    ctx 承载原巨型闭包的全部捕获变量；builder 注册表见 TASK_BUILDERS。
    """
    ctx = PlanContext()
    raw_subject = state.get("subject")
    ctx.subject = raw_subject if isinstance(raw_subject, dict) else {}
    ctx.output_mode = state.get("output_mode") or "brief"
    ctx.query = (state.get("query") or "").strip()
    operation_obj = state.get("operation") if isinstance(state.get("operation"), dict) else {}
    operation = operation_obj.get("name") or "qa"
    operation_params = operation_obj.get("params") if isinstance(operation_obj.get("params"), dict) else {}
    ctx.news_disallowed = reply_contract_disallows_news(state)
    reply_contract = state.get("reply_contract") if isinstance(state.get("reply_contract"), dict) else {}
    source_constraints = (
        reply_contract.get("source_constraints")
        if isinstance(reply_contract.get("source_constraints"), dict)
        else {}
    )
    ctx.requires_links = bool(source_constraints.get("requires_links"))

    trace = state.get("trace") or {}

    ctx.policy = state.get("policy") or {}
    raw_budget = ctx.policy.get("budget") if isinstance(ctx.policy, dict) else None
    budget = PlanBudget.model_validate(raw_budget or {"max_rounds": 1, "max_tools": 0})
    ctx.allowed_tools = set((ctx.policy.get("allowed_tools") or []) if isinstance(ctx.policy, dict) else [])
    ctx.allowed_agents = set((ctx.policy.get("allowed_agents") or []) if isinstance(ctx.policy, dict) else [])
    skill_selection = ctx.policy.get("skill_selection") if isinstance(ctx.policy, dict) else {}
    skill_selection = skill_selection if isinstance(skill_selection, dict) else {}
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    ctx.market = str(
        (ctx.policy.get("market") if isinstance(ctx.policy, dict) else None)
        or ui_context.get("market")
        or "US"
    ).strip().upper() or "US"
    raw_tasks = state.get("tasks")
    if not isinstance(raw_tasks, list):
        raw_tasks = project_v2_tasks_to_legacy(state.get("understanding_v2"))
    ctx.ready_tasks = [
        task for task in (raw_tasks if isinstance(raw_tasks, list) else [])
        if isinstance(task, dict) and str(task.get("status") or "ready").strip().lower() != "blocked"
    ]
    ctx.ready_task_id_set = {str(task.get("id") or "").strip() for task in ctx.ready_tasks if str(task.get("id") or "").strip()}
    ctx.ready_tasks_by_id = {str(task.get("id") or "").strip(): task for task in ctx.ready_tasks if str(task.get("id") or "").strip()}
    raw_request_frames = state.get("request_frames")
    ctx.request_frames = [
        frame for frame in (raw_request_frames if isinstance(raw_request_frames, list) else [])
        if isinstance(frame, dict)
    ]
    if not ctx.request_frames and isinstance(state.get("request_frame"), dict):
        ctx.request_frames = [state["request_frame"]]

    ctx.steps = []
    ctx.step_index = {}
    ctx.step_id = 1

    selection_payload = ctx.subject.get("selection_payload") if isinstance(ctx.subject, dict) else None
    if isinstance(selection_payload, list) and selection_payload:
        ctx.steps.append(
            {
                "id": f"s{ctx.step_id}",
                "kind": "llm",
                "name": "summarize_selection",
                "inputs": {"selection": selection_payload, "query": ctx.query},
                "why": "Selection 是高权重证据，先读/先总结以避免跑偏",
                "optional": False,
            }
        )
        ctx.step_id += 1
    else:
        selection_payload = []

    ctx.tickers = ctx.subject.get("tickers") if isinstance(ctx.subject, dict) else None
    ctx.primary_ticker = (ctx.tickers or [None])[0] if isinstance(ctx.tickers, list) else None
    subject_type = ctx.subject.get("subject_type") if isinstance(ctx.subject, dict) else None
    ctx.query_lower = ctx.query.lower()




    deep_financial_tokens = (
        "deep report",
        "deep research",
        "longform",
        "filing",
        "10-k",
        "10-q",
        "earnings call",
        "transcript",
        "研报",
        "深度",
        "财报",
        "电话会",
    )
    ctx.is_deep_financial_report = ctx.output_mode == "investment_report" and (
        _contains_any(ctx, deep_financial_tokens) or "deep_search_agent" in ctx.allowed_agents
    )








































    used_request_frame_plan = _append_request_frame_steps(ctx)
    if not used_request_frame_plan and _request_frames_authoritatively_need_no_plan_steps(ctx):
        used_request_frame_plan = True
    used_understanding_task_plan = False if used_request_frame_plan else _append_understanding_task_steps(ctx)

    if used_request_frame_plan or used_understanding_task_plan:
        _append_report_mode_enrichment_steps(ctx)
        task_sections = []
        if used_request_frame_plan:
            for index, frame in enumerate(ctx.request_frames[:8], 1):
                frame_subject = _frame_subject(ctx, frame)
                label = str(
                    frame_subject.get("label")
                    or ", ".join(_frame_tickers(ctx, frame))
                    or frame_subject.get("type")
                    or f"frame_{index}"
                )
                obligations = "+".join(_frame_required_evidence(ctx, frame) + _frame_required_results(ctx, frame)) or "contract"
                task_sections.append(f"{label}:{obligations}")
        for task in ctx.ready_tasks[:8]:
            label = str(task.get("subject_label") or ", ".join(_task_tickers(ctx, task)) or task.get("subject_type") or "任务")
            task_sections.append(f"{label}:{_task_operation_name(ctx, task)}")
        raw_plan = {
            "goal": ctx.query or "N/A",
            "subject": _plan_subject_payload(ctx),
            "output_mode": ctx.output_mode,
            "tasks": _plan_task_summary(ctx),
            "steps": ctx.steps,
            "synthesis": {"style": "structured", "sections": task_sections},
            "budget": budget.model_dump(),
        }
        try:
            plan = PlanIR.model_validate(raw_plan)
            coverage_validation = validate_plan_coverage_for_frames(
                request_frames=ctx.request_frames,
                plan_ir=plan.model_dump(),
                market=ctx.market,
            ) if ctx.request_frames else None
            trace.update(
                {
                    "planner": {
                        "type": "stub",
                        "validated": True,
                        "steps": len(plan.steps),
                        "operation": operation,
                        "understanding_task_count": len(ctx.ready_tasks),
                        "request_frame_count": len(ctx.request_frames),
                        "request_frame_driven": used_request_frame_plan,
                    }
                }
            )
            if coverage_validation is not None:
                trace["coverage_validator"] = coverage_validation
            return {"plan_ir": plan.model_dump(), "trace": trace}
        except Exception as exc:
            fallback = PlanIR(
                goal=ctx.query or "N/A",
                subject=PlanSubject(subject_type="unknown"),
                output_mode="brief",
                steps=[],
                budget=PlanBudget(max_rounds=1, max_tools=0),
            )
            trace.update(
                {
                    "planner": {
                        "type": "stub",
                        "validated": False,
                        "fallback": True,
                        "error": str(exc),
                    }
                }
            )
            return {"plan_ir": fallback.model_dump(), "trace": trace}

    if subject_type == "macro":
        _append_tool_step(ctx, 
            "get_current_datetime",
            {},
            why="宏观/主题问题先获取当前日期，避免把旧政策路径当成当前事实。",
            optional=True,
        )
        _append_tool_step(ctx, 
            "get_official_macro_releases",
            {"query": ctx.query, "max_results": 8},
            why="宏观/主题问题优先检索官方宏观发布与央行材料。",
            optional=True,
        )
        _append_tool_step(ctx, 
            "get_authoritative_media_news",
            {"query": ctx.query, "max_results": 6, "authoritative_only": True},
            why="补充权威媒体对宏观路径和市场估值影响的交叉验证。",
            optional=True,
        )
        _append_tool_step(ctx, 
            "search",
            {"query": ctx.query},
            why="补充开放搜索证据，用于覆盖主题研究中未被官方发布直接解释的市场影响。",
            optional=True,
        )

    # Morning brief: per-ticker price + news in parallel.
    if operation == "morning_brief":
        brief_tickers = [t for t in (ctx.tickers if isinstance(ctx.tickers, list) else []) if isinstance(t, str) and t.strip()]
        if not brief_tickers and isinstance(ctx.primary_ticker, str) and ctx.primary_ticker.strip():
            brief_tickers = [ctx.primary_ticker]
        for ticker in brief_tickers[:6]:
            if "get_stock_price" in ctx.allowed_tools:
                ctx.steps.append(
                    {
                        "id": f"s{ctx.step_id}",
                        "kind": "tool",
                        "name": "get_stock_price",
                        "inputs": {"ticker": ticker},
                        "parallel_group": "brief_data",
                        "why": f"晨报：获取 {ticker} 最新价格",
                        "optional": False,
                    }
                )
                ctx.step_id += 1
            if "get_company_news" in ctx.allowed_tools:
                ctx.steps.append(
                    {
                        "id": f"s{ctx.step_id}",
                        "kind": "tool",
                        "name": "get_company_news",
                        "inputs": {"ticker": ticker, "fast": True, "limit": 3},
                        "parallel_group": "brief_data",
                        "why": f"晨报：获取 {ticker} 最新新闻",
                        "optional": False,
                    }
                )
                ctx.step_id += 1
        if "get_current_datetime" in ctx.allowed_tools:
            ctx.steps.append(
                {
                    "id": f"s{ctx.step_id}",
                    "kind": "tool",
                    "name": "get_current_datetime",
                    "inputs": {},
                    "why": "晨报：获取当前日期时间用于报告标题",
                    "optional": True,
                }
            )
            ctx.step_id += 1

    if operation == "screen":
        screen_inputs = {
            "market": str((state.get("ui_context") or {}).get("market") or "US").upper(),
            "filters": {},
            "limit": 20,
            "page": 1,
            "sort_by": "marketCap",
            "sort_order": "desc",
        }
        if "screen_stocks" in ctx.allowed_tools:
            ctx.steps.append(
                {
                    "id": f"s{ctx.step_id}",
                    "kind": "tool",
                    "name": "screen_stocks",
                    "inputs": screen_inputs,
                    "why": "筛选类请求直接调用 screener 工具生成候选池。",
                    "optional": False,
                }
            )
            ctx.step_id += 1

    if operation == "cn_market":
        _append_tool_step(ctx, 
            "get_cn_market_fund_flow",
            {"limit": 20},
            why="A股市场请求先给出资金流向快照。",
            optional=False,
        )
        _append_tool_step(ctx, 
            "get_cn_market_northbound",
            {"limit": 20},
            why="补充北向资金维度。",
            optional=True,
        )
        _append_tool_step(ctx, 
            "get_cn_limit_board",
            {"limit": 20},
            why="补充涨跌停板块异动。",
            optional=True,
        )
        _append_tool_step(ctx, 
            "get_cn_lhb",
            {"limit": 20},
            why="补充龙虎榜交易信息。",
            optional=True,
        )
        _append_tool_step(ctx, 
            "get_cn_concept_map",
            {"keyword": "", "limit": 20},
            why="补充概念板块信息。",
            optional=True,
        )

    if operation == "backtest":
        ticker_for_backtest = ctx.primary_ticker or ((ctx.tickers or [None])[0] if isinstance(ctx.tickers, list) else None) or ""
        _append_tool_step(ctx, 
            "run_strategy_backtest",
            {
                "ticker": ticker_for_backtest,
                "strategy": str(operation_params.get("strategy") or "ma_cross").strip() or "ma_cross",
                "params": dict(operation_params.get("strategy_params") or operation_params.get("params") or {}),
                "initial_cash": float(operation_params.get("initial_cash") or 100000.0),
                "t_plus_one": bool(operation_params.get("t_plus_one", True)),
            },
            why="回测类请求调用策略回测工具并返回指标与交易明细。",
            optional=False,
        )

    # Rule-based minimal plan (Phase 3 scaffolding).
    if operation == "fetch" and ctx.primary_ticker and "get_company_news" in ctx.allowed_tools:
        ctx.steps.append(
            {
                "id": f"s{ctx.step_id}",
                "kind": "tool",
                "name": "get_company_news",
                "inputs": {"ticker": ctx.primary_ticker},
                "why": "获取标的最新新闻用于后续解读/对话",
                "optional": True,
            }
        )
        ctx.step_id += 1

    if operation == "compare":
        tickers_list = ctx.tickers if isinstance(ctx.tickers, list) else []
        tickers_list = [t for t in tickers_list if isinstance(t, str) and t.strip()]
        if len(tickers_list) >= 2 and "get_performance_comparison" in ctx.allowed_tools and _should_use_performance_compare(ctx, None):
            mapping = {t: t for t in tickers_list[:6]}
            ctx.steps.append(
                {
                    "id": f"s{ctx.step_id}",
                    "kind": "tool",
                    "name": "get_performance_comparison",
                    "inputs": {"tickers": mapping},
                    "why": "对比多标的 YTD/1Y 表现，作为对比分析的第一性数据",
                    "optional": False,
                }
            )
            ctx.step_id += 1
        if ctx.output_mode == "investment_report":
            for ticker in tickers_list[:6]:
                _append_tool_step(ctx, 
                    "get_stock_price",
                    {"ticker": ticker},
                    why=f"{ticker} 对比研报：补充当前价格作为报告锚点。",
                    optional=True,
                )
                _append_tool_step(ctx, 
                    "get_company_news",
                    {"ticker": ticker},
                    why=f"{ticker} 对比研报：补充近期新闻用于事件解释。",
                    optional=True,
                )
                _append_tool_step(ctx, 
                    "get_company_info",
                    {"ticker": ticker},
                    why=f"{ticker} 对比研报：补充公司基础信息。",
                    optional=True,
                )

    if operation == "earnings_impact" and ctx.primary_ticker:
        _append_earnings_impact_steps(ctx, ctx.primary_ticker)

    if operation == "earnings_performance" and ctx.primary_ticker:
        _append_earnings_performance_steps(ctx, ctx.primary_ticker)

    if operation == "valuation_sanity" and ctx.primary_ticker:
        _append_valuation_sanity_steps(ctx, ctx.primary_ticker)

    if operation in ("price", "technical") and ctx.primary_ticker and "get_stock_price" in ctx.allowed_tools:
        ctx.steps.append(
            {
                "id": f"s{ctx.step_id}",
                "kind": "tool",
                "name": "get_stock_price",
                "inputs": {"ticker": ctx.primary_ticker},
                "why": "获取最新价格作为分析锚点",
                "optional": False,
            }
        )
        ctx.step_id += 1

    if operation == "technical" and ctx.primary_ticker and "get_technical_snapshot" in ctx.allowed_tools:
        ctx.steps.append(
            {
                "id": f"s{ctx.step_id}",
                "kind": "tool",
                "name": "get_technical_snapshot",
                "inputs": {"ticker": ctx.primary_ticker},
                "why": "计算 MA/RSI/MACD 等技术指标用于技术面分析",
                "optional": False,
            }
        )
        ctx.step_id += 1

    if subject_type in ("company",) and ctx.primary_ticker and "get_company_info" in ctx.allowed_tools and operation in (
        "summarize",
        "analyze_impact",
        "generate_report",
    ):
        ctx.steps.append(
            {
                "id": f"s{ctx.step_id}",
                "kind": "tool",
                "name": "get_company_info",
                "inputs": {"ticker": ctx.primary_ticker},
                "why": "补齐公司基础信息，便于解释新闻/财务信息的语境",
                "optional": True,
            }
        )
        ctx.step_id += 1

    # Keyword routing for new tools (stub mode fallback).
    normalized_tickers = [
        str(t).strip().upper()
        for t in (ctx.tickers if isinstance(ctx.tickers, list) else [])
        if isinstance(t, str) and str(t).strip()
    ]
    if not normalized_tickers and isinstance(ctx.primary_ticker, str) and ctx.primary_ticker.strip():
        normalized_tickers = [ctx.primary_ticker.strip().upper()]

    if ctx.primary_ticker and _contains_any(ctx, 
        (
            "eps",
            "earnings estimate",
            "earnings estimates",
            "earnings revision",
            "eps revision",
            "consensus estimate",
            "guidance",
        )
    ):
        _append_tool_step(ctx, 
            "get_earnings_estimates",
            {"ticker": ctx.primary_ticker},
            why="关键词命中盈利预期，补充 forward EPS 与预期分歧数据。",
        )
        _append_tool_step(ctx, 
            "get_eps_revisions",
            {"ticker": ctx.primary_ticker},
            why="关键词命中 EPS 修正，补充上修/下修趋势信号。",
        )

    if ctx.primary_ticker and _contains_any(ctx, 
        (
            "option",
            "options",
            "implied volatility",
            " iv ",
            " pcr ",
            "put/call",
            "put call ratio",
            "skew",
            "vol smile",
        )
    ):
        _append_tool_step(ctx, 
            "get_option_chain_metrics",
            {"ticker": ctx.primary_ticker},
            why="关键词命中期权衍生指标，补充 IV/PCR/Skew。",
        )

    if ctx.primary_ticker and _contains_any(ctx, 
        (
            "sec filing",
            "sec filings",
            "edgar",
            "10-k",
            "10-q",
            "filing history",
            "annual report filing",
            "quarterly filing",
            "regulatory filing",
        )
    ):
        _append_tool_step(ctx, 
            "get_sec_filings",
            {"ticker": ctx.primary_ticker, "forms": "10-K,10-Q,8-K", "limit": 12},
            why="关键词命中监管披露需求，补充 SEC EDGAR 披露历史。",
        )

    if ctx.primary_ticker and _contains_any(ctx, 
        (
            "material event",
            "material events",
            "8-k",
            "current report",
            "major event filing",
        )
    ):
        _append_tool_step(ctx, 
            "get_sec_material_events",
            {"ticker": ctx.primary_ticker, "limit": 10},
            why="关键词命中重大事件披露需求，补充 SEC 8-K 信息。",
        )

    if ctx.primary_ticker and _contains_any(ctx, 
        (
            "risk factor",
            "risk factors",
            "item 1a",
            "1a risk",
        )
    ):
        _append_tool_step(ctx, 
            "get_sec_risk_factors",
            {"ticker": ctx.primary_ticker},
            why="关键词命中风险因子分析，从最新 10-K/10-Q 提取 Item 1A 摘要。",
        )

    if normalized_tickers and _contains_any(ctx, 
        (
            "factor exposure",
            "stress test",
            "scenario shock",
            "volatility shock",
            "drawdown shock",
            "beta exposure",
            "risk factor",
        )
    ):
        weight = round(1.0 / len(normalized_tickers), 4)
        positions = [{"ticker": ticker, "weight": weight} for ticker in normalized_tickers[:6]]
        _append_tool_step(ctx, 
            "get_factor_exposure",
            {"positions": positions, "lookback_days": 252},
            why="关键词命中因子暴露分析，生成组合 beta 与因子敞口。",
        )
        _append_tool_step(ctx, 
            "run_portfolio_stress_test",
            {"positions": positions, "lookback_days": 252},
            why="关键词命中压力测试，生成情景冲击下的收益敏感性。",
        )

    if ctx.primary_ticker and _contains_any(ctx, 
        (
            "event calendar",
            "earnings calendar",
            "earnings date",
            "dividend",
            "ex-dividend",
            "macro event",
            "fomc",
            "cpi",
            "payroll",
            "nfp",
            "calendar",
        )
    ):
        _append_tool_step(ctx, 
            "get_event_calendar",
            {"ticker": ctx.primary_ticker, "days_ahead": 30},
            why="关键词命中事件日历，补充财报/分红/宏观事件时间点。",
        )

    if _contains_any(ctx, 
        (
            "source reliability",
            "reliability score",
            "credible source",
            "news source",
            "rumor",
            "可信",
            "信源",
            "来源可靠",
        )
    ):
        reliability_inputs: dict[str, str] = {}
        url_match = re.search(r"https?://[^\s]+", ctx.query)
        if url_match:
            reliability_inputs["url"] = url_match.group(0).rstrip(".,)")
        for source_hint in ("reuters", "bloomberg", "wsj", "ft", "cnbc", "marketwatch", "seekingalpha"):
            if source_hint in ctx.query_lower:
                reliability_inputs["source"] = source_hint
                break
        _append_tool_step(ctx, 
            "score_news_source_reliability",
            reliability_inputs,
            why="关键词命中信源可靠度评估，补充来源可信度分级。",
        )

    # Report mode can expand information gathering, but should remain minimal by default.
    if ctx.output_mode == "investment_report" and ctx.primary_ticker:
        if "get_stock_price" in ctx.allowed_tools:
            ctx.steps.append(
                {
                    "id": f"s{ctx.step_id}",
                    "kind": "tool",
                    "name": "get_stock_price",
                    "inputs": {"ticker": ctx.primary_ticker},
                    "why": "研报模式补充当前价格与估值/风险叙述的锚点",
                    "optional": True,
                }
            )
            ctx.step_id += 1
        if "analyze_historical_drawdowns" in ctx.allowed_tools:
            ctx.steps.append(
                {
                    "id": f"s{ctx.step_id}",
                    "kind": "tool",
                    "name": "analyze_historical_drawdowns",
                    "inputs": {"ticker": ctx.primary_ticker},
                    "why": "研报模式补充历史回撤信息用于风险章节",
                    "optional": True,
                }
            )
            ctx.step_id += 1
        if "get_local_market_filings" in ctx.allowed_tools:
            ctx.steps.append(
                {
                    "id": f"s{ctx.step_id}",
                    "kind": "tool",
                    "name": "get_local_market_filings",
                    "inputs": {"ticker": ctx.primary_ticker, "limit": 8},
                    "why": "Report mode: add CN/HK local market disclosures for non-US issuers.",
                    "optional": True,
                }
            )
            ctx.step_id += 1
        else:
            if "get_sec_filings" in ctx.allowed_tools:
                ctx.steps.append(
                    {
                        "id": f"s{ctx.step_id}",
                        "kind": "tool",
                        "name": "get_sec_filings",
                        "inputs": {"ticker": ctx.primary_ticker, "forms": "10-K,10-Q", "limit": 6},
                        "why": "Report mode: add SEC EDGAR 10-K/10-Q filing evidence.",
                        "optional": True,
                    }
                )
                ctx.step_id += 1
            if "get_sec_company_facts_quarterly" in ctx.allowed_tools:
                ctx.steps.append(
                    {
                        "id": f"s{ctx.step_id}",
                        "kind": "tool",
                        "name": "get_sec_company_facts_quarterly",
                        "inputs": {"ticker": ctx.primary_ticker, "limit": 8},
                        "why": "Report mode: add SEC CompanyFacts quarterly financial metrics.",
                        "optional": True,
                    }
                )
                ctx.step_id += 1
            if "get_sec_material_events" in ctx.allowed_tools:
                ctx.steps.append(
                    {
                        "id": f"s{ctx.step_id}",
                        "kind": "tool",
                        "name": "get_sec_material_events",
                        "inputs": {"ticker": ctx.primary_ticker, "limit": 5},
                        "why": "Report mode: add SEC 8-K material events as event evidence.",
                        "optional": True,
                    }
                )
                ctx.step_id += 1

        if ctx.is_deep_financial_report and "get_authoritative_media_news" in ctx.allowed_tools:
            ctx.steps.append(
                {
                    "id": f"s{ctx.step_id}",
                    "kind": "tool",
                    "name": "get_authoritative_media_news",
                    "inputs": {"query": f"{ctx.primary_ticker} earnings outlook", "max_results": 6, "authoritative_only": True},
                    "why": "Deep financial report: force authoritative media retrieval step.",
                    "optional": True,
                }
            )
            ctx.step_id += 1

        if ctx.is_deep_financial_report and "get_earnings_call_transcripts" in ctx.allowed_tools:
            ctx.steps.append(
                {
                    "id": f"s{ctx.step_id}",
                    "kind": "tool",
                    "name": "get_earnings_call_transcripts",
                    "inputs": {"ticker": ctx.primary_ticker, "limit": 5},
                    "why": "Deep financial report: add free earnings-call transcript evidence.",
                    "optional": True,
                }
            )
            ctx.step_id += 1

        all_agents = sorted(ctx.allowed_agents)
        policy_agent_selection = ctx.policy.get("agent_selection") if isinstance(ctx.policy, dict) else {}
        force_all_agents = bool(ctx.policy.get("force_all_agents")) if isinstance(ctx.policy, dict) else False
        if isinstance(policy_agent_selection, dict):
            force_all_agents = force_all_agents or bool(policy_agent_selection.get("force_all_agents"))
        dashboard_forced = bool(policy_agent_selection.get("forced_by_dashboard")) if isinstance(policy_agent_selection, dict) else False
        selected_agents: list[str] = []

        if force_all_agents:
            ordered = [
                "price_agent",
                "news_agent",
                "fundamental_agent",
                "technical_agent",
                "macro_agent",
                "risk_agent",
                "deep_search_agent",
            ]
            selected_agents = [name for name in ordered if name in ctx.allowed_agents]
            max_agents = len(selected_agents)
        elif dashboard_forced:
            ordered = [
                "price_agent",
                "news_agent",
                "fundamental_agent",
                "technical_agent",
                "macro_agent",
                "risk_agent",
                "deep_search_agent",
            ]
            selected_agents = [name for name in ordered if name in ctx.allowed_agents]
            max_agents = len(selected_agents)
        else:
            try:
                max_agents = int((os.getenv("LANGGRAPH_REPORT_MAX_AGENTS") or "4").strip())
            except Exception:
                max_agents = 4
            max_agents = max(1, min(max_agents, len(all_agents))) if all_agents else 0
            try:
                min_agents = int((os.getenv("LANGGRAPH_REPORT_MIN_AGENTS") or "2").strip())
            except Exception:
                min_agents = 2
            min_agents = max(1, min(min_agents, max_agents)) if max_agents else 0

            if all_agents and max_agents > 0:
                selected = select_agents_for_request(
                    state,
                    all_agents,
                    max_agents=max_agents,
                    min_agents=min_agents,
                )
                selected_agents = [str(name) for name in (selected.get("selected") or []) if isinstance(name, str) and name]

        ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
        analysis_depth = str((ui_context or {}).get("analysis_depth") or "").strip().lower()
        if analysis_depth == "report":
            selected_agents = [name for name in selected_agents if name != "deep_search_agent"]
        elif analysis_depth == "deep_research":
            if "deep_search_agent" in all_agents and "deep_search_agent" not in selected_agents:
                if not force_all_agents and max_agents > 0 and len(selected_agents) >= max_agents:
                    if max_agents == 1:
                        selected_agents = ["deep_search_agent"]
                    else:
                        selected_agents = selected_agents[: max_agents - 1] + ["deep_search_agent"]
                else:
                    selected_agents.append("deep_search_agent")

        # In report mode, run score-selected expert agents for richer cards (ReportView).
        # All report agents share the same parallel_group so the executor
        # runs them concurrently via asyncio.gather.
        agent_parallel_group = "report_agents" if len(selected_agents) > 1 else None

        for agent_name in selected_agents:
            if agent_name not in ctx.allowed_agents:
                continue
            ctx.steps.append(
                {
                    "id": f"s{ctx.step_id}",
                    "kind": "agent",
                    "name": agent_name,
                    "inputs": {"query": ctx.query, "ticker": ctx.primary_ticker},
                    "parallel_group": agent_parallel_group,
                    "why": f"研报模式：运行 {agent_name} 产出结构化摘要+证据（用于卡片展示）",
                    "optional": True,
                }
            )
            ctx.step_id += 1

    if ctx.output_mode == "investment_report" and subject_type == "macro" and not ctx.primary_ticker:
        policy_agent_selection = ctx.policy.get("agent_selection") if isinstance(ctx.policy, dict) else {}
        required_agents = []
        if isinstance(policy_agent_selection, dict):
            required_agents = [str(name) for name in (policy_agent_selection.get("required") or []) if isinstance(name, str)]
        ordered_agents = ["macro_agent", "news_agent", "deep_search_agent"]
        selected_agents = [name for name in ordered_agents if name in ctx.allowed_agents]
        if not selected_agents and "macro_agent" in ctx.allowed_agents:
            selected_agents = ["macro_agent"]
        agent_parallel_group = "report_agents" if len(selected_agents) > 1 else None

        for agent_name in selected_agents:
            ctx.steps.append(
                {
                    "id": f"s{ctx.step_id}",
                    "kind": "agent",
                    "name": agent_name,
                    "inputs": {"query": ctx.query, "ticker": ""},
                    "parallel_group": agent_parallel_group,
                    "why": f"宏观/主题研报模式：运行 {agent_name} 产出结构化摘要与证据。",
                    "optional": agent_name not in required_agents,
                }
            )
            ctx.step_id += 1

    raw_plan = {
        "goal": ctx.query or "N/A",
        "subject": _plan_subject_payload(ctx),
        "output_mode": ctx.output_mode,
        "tasks": _plan_task_summary(ctx),
        "steps": ctx.steps,
        "synthesis": {"style": "concise", "sections": []},
        "budget": budget.model_dump(),
    }

    try:
        plan = PlanIR.model_validate(raw_plan)
        coverage_validation = validate_plan_coverage_for_frames(
            request_frames=ctx.request_frames,
            plan_ir=plan.model_dump(),
            market=ctx.market,
        ) if ctx.request_frames else None
        trace.update(
            {
                "planner": {
                    "type": "stub",
                    "validated": True,
                    "steps": len(plan.steps),
                    "operation": operation,
                }
            }
        )
        if coverage_validation is not None:
            trace["coverage_validator"] = coverage_validation
        return {"plan_ir": plan.model_dump(), "trace": trace}
    except Exception as exc:
        fallback = PlanIR(
            goal=ctx.query or "N/A",
            subject=PlanSubject(subject_type="unknown"),
            output_mode="brief",
            steps=[],
            budget=PlanBudget(max_rounds=1, max_tools=0),
        )
        trace.update(
            {
                "planner": {
                    "type": "stub",
                    "validated": False,
                    "fallback": True,
                    "error": str(exc),
                }
            }
        )
        return {"plan_ir": fallback.model_dump(), "trace": trace}

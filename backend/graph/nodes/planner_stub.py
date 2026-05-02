# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re

from backend.graph.capability_registry import select_agents_for_request
from backend.graph.state import GraphState
from backend.graph.plan_ir import PlanIR, PlanBudget, PlanSubject


def planner_stub(state: GraphState) -> dict:
    """
    Phase 1 stub: produce a minimal PlanIR.
    Later phases will replace this with an LLM-constrained Planner.
    """
    raw_subject = state.get("subject")
    subject = raw_subject if isinstance(raw_subject, dict) else {}
    output_mode = state.get("output_mode") or "brief"
    query = (state.get("query") or "").strip()
    operation = (state.get("operation") or {}).get("name") or "qa"

    trace = state.get("trace") or {}

    policy = state.get("policy") or {}
    raw_budget = policy.get("budget") if isinstance(policy, dict) else None
    budget = PlanBudget.model_validate(raw_budget or {"max_rounds": 1, "max_tools": 0})
    allowed_tools = set((policy.get("allowed_tools") or []) if isinstance(policy, dict) else [])
    allowed_agents = set((policy.get("allowed_agents") or []) if isinstance(policy, dict) else [])
    raw_tasks = state.get("tasks")
    ready_tasks = [
        task for task in (raw_tasks if isinstance(raw_tasks, list) else [])
        if isinstance(task, dict) and str(task.get("status") or "ready").strip().lower() != "blocked"
    ]

    steps: list[dict] = []
    step_id = 1

    selection_payload = subject.get("selection_payload") if isinstance(subject, dict) else None
    if isinstance(selection_payload, list) and selection_payload:
        steps.append(
            {
                "id": f"s{step_id}",
                "kind": "llm",
                "name": "summarize_selection",
                "inputs": {"selection": selection_payload, "query": query},
                "why": "Selection 是高权重证据，先读/先总结以避免跑偏",
                "optional": False,
            }
        )
        step_id += 1

    tickers = subject.get("tickers") if isinstance(subject, dict) else None
    primary_ticker = (tickers or [None])[0] if isinstance(tickers, list) else None
    subject_type = subject.get("subject_type") if isinstance(subject, dict) else None
    query_lower = query.lower()

    def _contains_any(tokens: tuple[str, ...]) -> bool:
        return any(token in query_lower for token in tokens)

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
    is_deep_financial_report = output_mode == "investment_report" and (
        _contains_any(deep_financial_tokens) or "deep_search_agent" in allowed_agents
    )

    def _append_tool_step(
        name: str,
        inputs: dict,
        *,
        why: str,
        optional: bool = True,
        parallel_group: str | None = None,
    ) -> None:
        nonlocal step_id
        if name not in allowed_tools:
            return
        step = {
            "id": f"s{step_id}",
            "kind": "tool",
            "name": name,
            "inputs": inputs,
            "why": why,
            "optional": optional,
        }
        if parallel_group:
            step["parallel_group"] = parallel_group
        steps.append(step)
        step_id += 1

    def _task_operation_name(task: dict) -> str:
        op = task.get("operation")
        if isinstance(op, dict):
            name = op.get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
        return "qa"

    def _task_tickers(task: dict) -> list[str]:
        values = task.get("tickers")
        if not isinstance(values, list):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            ticker = str(value or "").strip().upper()
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            result.append(ticker)
        return result

    def _plan_task_summary() -> list[dict]:
        rows: list[dict] = []
        for task in ready_tasks[:16]:
            task_id = str(task.get("id") or f"task_{len(rows) + 1}").strip()
            rows.append(
                {
                    "id": task_id or f"task_{len(rows) + 1}",
                    "subject_type": str(task.get("subject_type") or "unknown"),
                    "tickers": _task_tickers(task),
                    "operation": _task_operation_name(task),
                    "status": str(task.get("status") or "ready"),
                }
            )
        return rows

    def _append_company_task_steps(task: dict, *, group: str) -> None:
        op_name = _task_operation_name(task)
        tickers_for_task = _task_tickers(task)
        if op_name == "compare" and len(tickers_for_task) >= 2:
            mapping = {ticker: ticker for ticker in tickers_for_task[:6]}
            _append_tool_step(
                "get_performance_comparison",
                {"tickers": mapping},
                why="多标的对比任务：先取标准化表现数据。",
                optional=False,
                parallel_group=group,
            )
            return

        for ticker in tickers_for_task[:6]:
            if op_name in {"price", "technical", "qa", "analyze_impact", "daily_brief"}:
                _append_tool_step(
                    "get_stock_price",
                    {"ticker": ticker},
                    why=f"{ticker} 任务：获取价格/涨跌幅作为回答锚点。",
                    optional=op_name not in {"price", "technical"},
                    parallel_group=group,
                )
            if op_name == "technical":
                _append_tool_step(
                    "get_technical_snapshot",
                    {"ticker": ticker},
                    why=f"{ticker} 技术面任务：获取技术指标快照。",
                    optional=False,
                    parallel_group=group,
                )
            if op_name in {"fetch", "qa", "analyze_impact", "daily_brief"}:
                _append_tool_step(
                    "get_company_news",
                    {"ticker": ticker},
                    why=f"{ticker} 任务：获取相关新闻用于事件解释。",
                    optional=op_name not in {"fetch", "analyze_impact"},
                    parallel_group=group,
                )
            if op_name in {"qa", "analyze_impact"}:
                _append_tool_step(
                    "get_company_info",
                    {"ticker": ticker},
                    why=f"{ticker} 任务：补充公司基础信息，避免只看新闻标题。",
                    optional=True,
                    parallel_group=group,
                )

    def _append_macro_task_steps(task: dict, *, group: str) -> None:
        task_query = str(task.get("subject_label") or query).strip() or query
        _append_tool_step(
            "get_current_datetime",
            {},
            why="宏观任务：获取当前日期，防止把旧政策当成当前事实。",
            optional=True,
            parallel_group=group,
        )
        _append_tool_step(
            "get_official_macro_releases",
            {"query": query, "max_results": 8},
            why="宏观任务：优先检查官方宏观/央行发布。",
            optional=False,
            parallel_group=group,
        )
        _append_tool_step(
            "get_authoritative_media_news",
            {"query": task_query, "max_results": 6, "authoritative_only": True},
            why="宏观任务：用权威媒体交叉验证市场影响。",
            optional=True,
            parallel_group=group,
        )
        _append_tool_step(
            "search",
            {"query": task_query},
            why="宏观任务：补充开放搜索证据。",
            optional=True,
            parallel_group=group,
        )

    def _append_portfolio_task_steps(task: dict, *, group: str) -> None:
        tickers_for_task = _task_tickers(task)
        if tickers_for_task:
            weight = round(1.0 / len(tickers_for_task), 4)
            positions = [{"ticker": ticker, "weight": weight} for ticker in tickers_for_task[:8]]
            _append_tool_step(
                "get_factor_exposure",
                {"positions": positions, "lookback_days": 252},
                why="组合任务：估算持仓因子暴露。",
                optional=True,
                parallel_group=group,
            )
            _append_tool_step(
                "run_portfolio_stress_test",
                {"positions": positions, "lookback_days": 252},
                why="组合任务：估算压力情景下的组合敏感性。",
                optional=True,
                parallel_group=group,
            )
        _append_tool_step(
            "search",
            {"query": query},
            why="组合任务：检索影响持仓的近期市场事件。",
            optional=True,
            parallel_group=group,
        )

    def _append_theme_task_steps(task: dict, *, group: str) -> None:
        task_query = str(task.get("subject_label") or query).strip() or query
        _append_tool_step(
            "get_current_datetime",
            {},
            why="主题任务：获取当前日期，限定近期事件语境。",
            optional=True,
            parallel_group=group,
        )
        _append_tool_step(
            "get_authoritative_media_news",
            {"query": query, "max_results": 6, "authoritative_only": True},
            why="主题任务：优先用权威媒体验证行业事件。",
            optional=True,
            parallel_group=group,
        )
        _append_tool_step(
            "search",
            {"query": task_query},
            why="主题任务：检索行业/主题的近期事件与影响。",
            optional=False,
            parallel_group=group,
        )

    def _append_understanding_task_steps() -> bool:
        if len(ready_tasks) <= 1:
            return False
        for idx, task in enumerate(ready_tasks[:12], 1):
            subject_for_task = str(task.get("subject_type") or "unknown").strip().lower()
            group = f"task_{idx}"
            if subject_for_task in {"company", "index", "commodity"}:
                _append_company_task_steps(task, group=group)
            elif subject_for_task == "macro":
                _append_macro_task_steps(task, group=group)
            elif subject_for_task == "portfolio":
                _append_portfolio_task_steps(task, group=group)
            elif subject_for_task == "theme":
                _append_theme_task_steps(task, group=group)
        return True

    used_understanding_task_plan = _append_understanding_task_steps()

    if used_understanding_task_plan:
        task_sections = []
        for task in ready_tasks[:8]:
            label = str(task.get("subject_label") or ", ".join(_task_tickers(task)) or task.get("subject_type") or "任务")
            task_sections.append(f"{label}:{_task_operation_name(task)}")
        raw_plan = {
            "goal": query or "N/A",
            "subject": subject or PlanSubject(subject_type="unknown").model_dump(),
            "output_mode": output_mode,
            "tasks": _plan_task_summary(),
            "steps": steps,
            "synthesis": {"style": "structured", "sections": task_sections},
            "budget": budget.model_dump(),
        }
        try:
            plan = PlanIR.model_validate(raw_plan)
            trace.update(
                {
                    "planner": {
                        "type": "stub",
                        "validated": True,
                        "steps": len(plan.steps),
                        "operation": operation,
                        "understanding_task_count": len(ready_tasks),
                    }
                }
            )
            return {"plan_ir": plan.model_dump(), "trace": trace}
        except Exception as exc:
            fallback = PlanIR(
                goal=query or "N/A",
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
        _append_tool_step(
            "get_current_datetime",
            {},
            why="宏观/主题问题先获取当前日期，避免把旧政策路径当成当前事实。",
            optional=True,
        )
        _append_tool_step(
            "get_official_macro_releases",
            {"query": query, "max_results": 8},
            why="宏观/主题问题优先检索官方宏观发布与央行材料。",
            optional=True,
        )
        _append_tool_step(
            "get_authoritative_media_news",
            {"query": query, "max_results": 6, "authoritative_only": True},
            why="补充权威媒体对宏观路径和市场估值影响的交叉验证。",
            optional=True,
        )
        _append_tool_step(
            "search",
            {"query": query},
            why="补充开放搜索证据，用于覆盖主题研究中未被官方发布直接解释的市场影响。",
            optional=True,
        )

    # Morning brief: per-ticker price + news in parallel.
    if operation == "morning_brief":
        brief_tickers = [t for t in (tickers if isinstance(tickers, list) else []) if isinstance(t, str) and t.strip()]
        if not brief_tickers and isinstance(primary_ticker, str) and primary_ticker.strip():
            brief_tickers = [primary_ticker]
        for ticker in brief_tickers[:6]:
            if "get_stock_price" in allowed_tools:
                steps.append(
                    {
                        "id": f"s{step_id}",
                        "kind": "tool",
                        "name": "get_stock_price",
                        "inputs": {"ticker": ticker},
                        "parallel_group": "brief_data",
                        "why": f"晨报：获取 {ticker} 最新价格",
                        "optional": False,
                    }
                )
                step_id += 1
            if "get_company_news" in allowed_tools:
                steps.append(
                    {
                        "id": f"s{step_id}",
                        "kind": "tool",
                        "name": "get_company_news",
                        "inputs": {"ticker": ticker},
                        "parallel_group": "brief_data",
                        "why": f"晨报：获取 {ticker} 最新新闻",
                        "optional": False,
                    }
                )
                step_id += 1
        if "get_current_datetime" in allowed_tools:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "get_current_datetime",
                    "inputs": {},
                    "why": "晨报：获取当前日期时间用于报告标题",
                    "optional": True,
                }
            )
            step_id += 1

    if operation == "screen":
        screen_inputs = {
            "market": str((state.get("ui_context") or {}).get("market") or "US").upper(),
            "filters": {},
            "limit": 20,
            "page": 1,
            "sort_by": "marketCap",
            "sort_order": "desc",
        }
        if "screen_stocks" in allowed_tools:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "screen_stocks",
                    "inputs": screen_inputs,
                    "why": "筛选类请求直接调用 screener 工具生成候选池。",
                    "optional": False,
                }
            )
            step_id += 1

    if operation == "cn_market":
        _append_tool_step(
            "get_cn_market_fund_flow",
            {"limit": 20},
            why="A股市场请求先给出资金流向快照。",
            optional=False,
        )
        _append_tool_step(
            "get_cn_market_northbound",
            {"limit": 20},
            why="补充北向资金维度。",
            optional=True,
        )
        _append_tool_step(
            "get_cn_limit_board",
            {"limit": 20},
            why="补充涨跌停板块异动。",
            optional=True,
        )
        _append_tool_step(
            "get_cn_lhb",
            {"limit": 20},
            why="补充龙虎榜交易信息。",
            optional=True,
        )
        _append_tool_step(
            "get_cn_concept_map",
            {"keyword": "", "limit": 20},
            why="补充概念板块信息。",
            optional=True,
        )

    if operation == "backtest":
        ticker_for_backtest = primary_ticker or ((tickers or [None])[0] if isinstance(tickers, list) else None) or ""
        _append_tool_step(
            "run_strategy_backtest",
            {
                "ticker": ticker_for_backtest,
                "strategy": "ma_cross",
                "params": {},
                "initial_cash": 100000.0,
                "t_plus_one": True,
            },
            why="回测类请求调用策略回测工具并返回指标与交易明细。",
            optional=False,
        )

    # Rule-based minimal plan (Phase 3 scaffolding).
    if operation == "fetch" and primary_ticker and "get_company_news" in allowed_tools:
        steps.append(
            {
                "id": f"s{step_id}",
                "kind": "tool",
                "name": "get_company_news",
                "inputs": {"ticker": primary_ticker},
                "why": "获取标的最新新闻用于后续解读/对话",
                "optional": True,
            }
        )
        step_id += 1

    if operation == "compare":
        tickers_list = tickers if isinstance(tickers, list) else []
        tickers_list = [t for t in tickers_list if isinstance(t, str) and t.strip()]
        if len(tickers_list) >= 2 and "get_performance_comparison" in allowed_tools:
            mapping = {t: t for t in tickers_list[:6]}
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "get_performance_comparison",
                    "inputs": {"tickers": mapping},
                    "why": "对比多标的 YTD/1Y 表现，作为对比分析的第一性数据",
                    "optional": False,
                }
            )
            step_id += 1

    if operation in ("price", "technical") and primary_ticker and "get_stock_price" in allowed_tools:
        steps.append(
            {
                "id": f"s{step_id}",
                "kind": "tool",
                "name": "get_stock_price",
                "inputs": {"ticker": primary_ticker},
                "why": "获取最新价格作为分析锚点",
                "optional": False,
            }
        )
        step_id += 1

    if operation == "technical" and primary_ticker and "get_technical_snapshot" in allowed_tools:
        steps.append(
            {
                "id": f"s{step_id}",
                "kind": "tool",
                "name": "get_technical_snapshot",
                "inputs": {"ticker": primary_ticker},
                "why": "计算 MA/RSI/MACD 等技术指标用于技术面分析",
                "optional": False,
            }
        )
        step_id += 1

    if subject_type in ("company",) and primary_ticker and "get_company_info" in allowed_tools and operation in (
        "summarize",
        "analyze_impact",
        "qa",
        "generate_report",
    ):
        steps.append(
            {
                "id": f"s{step_id}",
                "kind": "tool",
                "name": "get_company_info",
                "inputs": {"ticker": primary_ticker},
                "why": "补齐公司基础信息，便于解释新闻/财务信息的语境",
                "optional": True,
            }
        )
        step_id += 1

    # Keyword routing for new tools (stub mode fallback).
    normalized_tickers = [
        str(t).strip().upper()
        for t in (tickers if isinstance(tickers, list) else [])
        if isinstance(t, str) and str(t).strip()
    ]
    if not normalized_tickers and isinstance(primary_ticker, str) and primary_ticker.strip():
        normalized_tickers = [primary_ticker.strip().upper()]

    if primary_ticker and _contains_any(
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
        _append_tool_step(
            "get_earnings_estimates",
            {"ticker": primary_ticker},
            why="关键词命中盈利预期，补充 forward EPS 与预期分歧数据。",
        )
        _append_tool_step(
            "get_eps_revisions",
            {"ticker": primary_ticker},
            why="关键词命中 EPS 修正，补充上修/下修趋势信号。",
        )

    if primary_ticker and _contains_any(
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
        _append_tool_step(
            "get_option_chain_metrics",
            {"ticker": primary_ticker},
            why="关键词命中期权衍生指标，补充 IV/PCR/Skew。",
        )

    if primary_ticker and _contains_any(
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
        _append_tool_step(
            "get_sec_filings",
            {"ticker": primary_ticker, "forms": "10-K,10-Q,8-K", "limit": 12},
            why="关键词命中监管披露需求，补充 SEC EDGAR 披露历史。",
        )

    if primary_ticker and _contains_any(
        (
            "material event",
            "material events",
            "8-k",
            "current report",
            "major event filing",
        )
    ):
        _append_tool_step(
            "get_sec_material_events",
            {"ticker": primary_ticker, "limit": 10},
            why="关键词命中重大事件披露需求，补充 SEC 8-K 信息。",
        )

    if primary_ticker and _contains_any(
        (
            "risk factor",
            "risk factors",
            "item 1a",
            "1a risk",
        )
    ):
        _append_tool_step(
            "get_sec_risk_factors",
            {"ticker": primary_ticker},
            why="关键词命中风险因子分析，从最新 10-K/10-Q 提取 Item 1A 摘要。",
        )

    if normalized_tickers and _contains_any(
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
        _append_tool_step(
            "get_factor_exposure",
            {"positions": positions, "lookback_days": 252},
            why="关键词命中因子暴露分析，生成组合 beta 与因子敞口。",
        )
        _append_tool_step(
            "run_portfolio_stress_test",
            {"positions": positions, "lookback_days": 252},
            why="关键词命中压力测试，生成情景冲击下的收益敏感性。",
        )

    if primary_ticker and _contains_any(
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
        _append_tool_step(
            "get_event_calendar",
            {"ticker": primary_ticker, "days_ahead": 30},
            why="关键词命中事件日历，补充财报/分红/宏观事件时间点。",
        )

    if _contains_any(
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
        url_match = re.search(r"https?://[^\s]+", query)
        if url_match:
            reliability_inputs["url"] = url_match.group(0).rstrip(".,)")
        for source_hint in ("reuters", "bloomberg", "wsj", "ft", "cnbc", "marketwatch", "seekingalpha"):
            if source_hint in query_lower:
                reliability_inputs["source"] = source_hint
                break
        _append_tool_step(
            "score_news_source_reliability",
            reliability_inputs,
            why="关键词命中信源可靠度评估，补充来源可信度分级。",
        )

    # Report mode can expand information gathering, but should remain minimal by default.
    if output_mode == "investment_report" and primary_ticker:
        if "get_stock_price" in allowed_tools:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "get_stock_price",
                    "inputs": {"ticker": primary_ticker},
                    "why": "研报模式补充当前价格与估值/风险叙述的锚点",
                    "optional": True,
                }
            )
            step_id += 1
        if "analyze_historical_drawdowns" in allowed_tools:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "analyze_historical_drawdowns",
                    "inputs": {"ticker": primary_ticker},
                    "why": "研报模式补充历史回撤信息用于风险章节",
                    "optional": True,
                }
            )
            step_id += 1
        if "get_local_market_filings" in allowed_tools:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "get_local_market_filings",
                    "inputs": {"ticker": primary_ticker, "limit": 8},
                    "why": "Report mode: add CN/HK local market disclosures for non-US issuers.",
                    "optional": True,
                }
            )
            step_id += 1
        else:
            if "get_sec_filings" in allowed_tools:
                steps.append(
                    {
                        "id": f"s{step_id}",
                        "kind": "tool",
                        "name": "get_sec_filings",
                        "inputs": {"ticker": primary_ticker, "forms": "10-K,10-Q", "limit": 6},
                        "why": "Report mode: add SEC EDGAR 10-K/10-Q filing evidence.",
                        "optional": True,
                    }
                )
                step_id += 1
            if "get_sec_company_facts_quarterly" in allowed_tools:
                steps.append(
                    {
                        "id": f"s{step_id}",
                        "kind": "tool",
                        "name": "get_sec_company_facts_quarterly",
                        "inputs": {"ticker": primary_ticker, "limit": 8},
                        "why": "Report mode: add SEC CompanyFacts quarterly financial metrics.",
                        "optional": True,
                    }
                )
                step_id += 1
            if "get_sec_material_events" in allowed_tools:
                steps.append(
                    {
                        "id": f"s{step_id}",
                        "kind": "tool",
                        "name": "get_sec_material_events",
                        "inputs": {"ticker": primary_ticker, "limit": 5},
                        "why": "Report mode: add SEC 8-K material events as event evidence.",
                        "optional": True,
                    }
                )
                step_id += 1

        if is_deep_financial_report and "get_authoritative_media_news" in allowed_tools:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "get_authoritative_media_news",
                    "inputs": {"query": f"{primary_ticker} earnings outlook", "max_results": 6, "authoritative_only": True},
                    "why": "Deep financial report: force authoritative media retrieval step.",
                    "optional": True,
                }
            )
            step_id += 1

        if is_deep_financial_report and "get_earnings_call_transcripts" in allowed_tools:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "tool",
                    "name": "get_earnings_call_transcripts",
                    "inputs": {"ticker": primary_ticker, "limit": 5},
                    "why": "Deep financial report: add free earnings-call transcript evidence.",
                    "optional": True,
                }
            )
            step_id += 1

        all_agents = sorted(allowed_agents)
        policy_agent_selection = policy.get("agent_selection") if isinstance(policy, dict) else {}
        force_all_agents = bool(policy.get("force_all_agents")) if isinstance(policy, dict) else False
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
            selected_agents = [name for name in ordered if name in allowed_agents]
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
            selected_agents = [name for name in ordered if name in allowed_agents]
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
            if agent_name not in allowed_agents:
                continue
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "agent",
                    "name": agent_name,
                    "inputs": {"query": query, "ticker": primary_ticker},
                    "parallel_group": agent_parallel_group,
                    "why": f"研报模式：运行 {agent_name} 产出结构化摘要+证据（用于卡片展示）",
                    "optional": True,
                }
            )
            step_id += 1

    if output_mode == "investment_report" and subject_type == "macro" and not primary_ticker:
        policy_agent_selection = policy.get("agent_selection") if isinstance(policy, dict) else {}
        required_agents = []
        if isinstance(policy_agent_selection, dict):
            required_agents = [str(name) for name in (policy_agent_selection.get("required") or []) if isinstance(name, str)]
        ordered_agents = ["macro_agent", "news_agent", "deep_search_agent"]
        selected_agents = [name for name in ordered_agents if name in allowed_agents]
        if not selected_agents and "macro_agent" in allowed_agents:
            selected_agents = ["macro_agent"]
        agent_parallel_group = "report_agents" if len(selected_agents) > 1 else None

        for agent_name in selected_agents:
            steps.append(
                {
                    "id": f"s{step_id}",
                    "kind": "agent",
                    "name": agent_name,
                    "inputs": {"query": query, "ticker": ""},
                    "parallel_group": agent_parallel_group,
                    "why": f"宏观/主题研报模式：运行 {agent_name} 产出结构化摘要与证据。",
                    "optional": agent_name not in required_agents,
                }
            )
            step_id += 1

    raw_plan = {
        "goal": query or "N/A",
        "subject": subject or PlanSubject(subject_type="unknown").model_dump(),
        "output_mode": output_mode,
        "tasks": _plan_task_summary(),
        "steps": steps,
        "synthesis": {"style": "concise", "sections": []},
        "budget": budget.model_dump(),
    }

    try:
        plan = PlanIR.model_validate(raw_plan)
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
        return {"plan_ir": plan.model_dump(), "trace": trace}
    except Exception as exc:
        fallback = PlanIR(
            goal=query or "N/A",
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

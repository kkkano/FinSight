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

    def _append_tool_step(
        name: str,
        inputs: dict,
        *,
        why: str,
        optional: bool = True,
    ) -> None:
        nonlocal step_id
        if name not in allowed_tools:
            return
        steps.append(
            {
                "id": f"s{step_id}",
                "kind": "tool",
                "name": name,
                "inputs": inputs,
                "why": why,
                "optional": optional,
            }
        )
        step_id += 1

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

        all_agents = sorted(allowed_agents)
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

        selected_agents: list[str] = []
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
                if max_agents > 0 and len(selected_agents) >= max_agents:
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

    raw_plan = {
        "goal": query or "N/A",
        "subject": subject or PlanSubject(subject_type="unknown").model_dump(),
        "output_mode": output_mode,
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

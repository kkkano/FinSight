# -*- coding: utf-8 -*-
from __future__ import annotations

import os

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

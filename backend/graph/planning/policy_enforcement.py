# -*- coding: utf-8 -*-
"""Planner 输出的政策、预算与执行步骤约束。"""
from __future__ import annotations

import os
import re
from typing import Any

from backend.graph.capability_registry import select_agents_for_request
from backend.graph.plan_ir import PlanBudget
from backend.graph.planning.steps import finalize_step_dependencies
from backend.graph.state import GraphState


_HIGH_COST_AGENTS: set[str] = {"macro_agent", "deep_search_agent"}


def _env_str(key: str, default: str) -> str:
    raw = os.getenv(key)
    return raw.strip() if isinstance(raw, str) and raw.strip() else default


def _is_deep_hint(query: str, state: GraphState | None = None) -> bool:
    if isinstance(state, dict):
        ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
        analysis_depth = str((ui_context or {}).get("analysis_depth") or "").strip().lower()
        if analysis_depth == "deep_research":
            return True
    q = (query or "").lower()
    if re.search(r"\b(without|no|not|skip|exclude|avoid)\s+(deep\s+research|deep\s+search|deepsearch|deep)\b", q):
        return False
    return any(token in q for token in ("deep", "deepsearch", "filing", "document", "longform"))


def _is_dashboard_source(state: GraphState) -> bool:
    """来源是否为 dashboard（包括 dashboard_news、dashboard_header 等）。"""
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    source = str((ui_context or {}).get("source") or "").strip().lower()
    return source.startswith("dashboard")


def _is_dashboard_forced_report(policy: dict[str, Any], state: GraphState) -> bool:
    if not isinstance(policy, dict):
        return False
    agent_selection = policy.get("agent_selection")
    if isinstance(agent_selection, dict) and bool(agent_selection.get("forced_by_dashboard")):
        return True
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    source = str((ui_context or {}).get("source") or "").strip().lower()
    output_mode = str(state.get("output_mode") or "").strip().lower()
    return output_mode == "investment_report" and source.startswith("dashboard")


def _estimate_step_cost_latency(step: dict[str, Any]) -> tuple[float, int]:
    kind = str(step.get("kind") or "")
    name = str(step.get("name") or "")
    if kind == "llm":
        return (0.8, 450)
    if kind == "tool":
        # Tools are generally cheaper than agent calls.
        if name in ("search", "get_current_datetime"):
            return (0.6, 250)
        if name in ("get_stock_price", "get_technical_snapshot", "get_performance_comparison"):
            return (0.8, 350)
        return (1.0, 500)
    if kind == "agent":
        if name == "deep_search_agent":
            return (3.8, 2800)
        if name == "macro_agent":
            return (2.6, 1700)
        return (1.6, 900)
    return (1.0, 500)


def _build_budget_assertions(steps: list[dict[str, Any]], safe_budget: dict[str, Any]) -> dict[str, Any]:
    total_cost = 0.0
    total_latency_ms = 0
    for step in steps:
        cost, latency_ms = _estimate_step_cost_latency(step)
        total_cost += cost
        total_latency_ms += latency_ms

    max_tools = int(safe_budget.get("max_tools", 0) or 0)
    max_rounds = int(safe_budget.get("max_rounds", 0) or 0)
    latency_per_round_ms = int(_env_str("LANGGRAPH_BUDGET_LATENCY_PER_ROUND_MS", "1400"))
    cost_per_tool_unit = float(_env_str("LANGGRAPH_BUDGET_COST_PER_TOOL_UNIT", "1.5"))

    cost_budget_units = round(max_tools * cost_per_tool_unit, 4) if max_tools > 0 else 0.0
    latency_budget_ms = max_rounds * latency_per_round_ms if max_rounds > 0 else 0

    return {
        "estimated_cost_units": round(total_cost, 4),
        "estimated_latency_ms": total_latency_ms,
        "cost_budget_units": cost_budget_units,
        "latency_budget_ms": latency_budget_ms,
        "cost_within_budget": True if cost_budget_units <= 0 else total_cost <= cost_budget_units,
        "latency_within_budget": True if latency_budget_ms <= 0 else total_latency_ms <= latency_budget_ms,
        "step_count": len(steps),
    }


def _plan_tasks_from_state(state: GraphState) -> list[dict[str, Any]]:
    raw_tasks = state.get("tasks")
    if not isinstance(raw_tasks, list):
        return []
    rows: list[dict[str, Any]] = []
    for idx, task in enumerate(raw_tasks[:16], 1):
        if not isinstance(task, dict):
            continue
        operation = task.get("operation")
        op_name = "qa"
        if isinstance(operation, dict):
            candidate = operation.get("name")
            if isinstance(candidate, str) and candidate.strip():
                op_name = candidate.strip()
        tickers = task.get("tickers")
        rows.append(
            {
                "id": str(task.get("id") or f"task_{idx}"),
                "subject_type": str(task.get("subject_type") or "unknown"),
                "tickers": [
                    str(ticker).strip().upper()
                    for ticker in (tickers if isinstance(tickers, list) else [])
                    if str(ticker).strip()
                ],
                "operation": op_name,
                "status": str(task.get("status") or "ready"),
            }
        )
    return rows


def _enforce_policy(plan_payload: dict[str, Any], state: GraphState) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    Enforce critical invariants from state + policy:
    - output_mode comes from state (UI override already applied)
    - budget comes from PolicyGate
    - steps must stay within allowlists
    """
    policy = state.get("policy") or {}
    budget = policy.get("budget") if isinstance(policy, dict) else None
    allowed_tools = set((policy.get("allowed_tools") or []) if isinstance(policy, dict) else [])

    # Force output_mode + budget to avoid "model self-upgrades".
    output_mode = state.get("output_mode") or "brief"
    safe_budget = PlanBudget.model_validate(budget or {"max_rounds": 3, "max_tools": 4}).model_dump()
    allowed_agents = set((policy.get("allowed_agents") or []) if isinstance(policy, dict) else [])
    agent_selection = policy.get("agent_selection") if isinstance(policy, dict) else {}
    force_all_agents = bool(policy.get("force_all_agents")) if isinstance(policy, dict) else False
    if isinstance(agent_selection, dict):
        force_all_agents = force_all_agents or bool(agent_selection.get("force_all_agents"))
    selected_agent_order: list[str] = []
    report_agent_cap: int | None = None
    dashboard_forced_report = _is_dashboard_forced_report(policy, state)
    if output_mode == "investment_report" and allowed_agents and not dashboard_forced_report and not force_all_agents:
        try:
            report_max_agents = int(_env_str("LANGGRAPH_REPORT_MAX_AGENTS", "4"))
        except Exception:
            report_max_agents = 4
        report_max_agents = max(1, min(report_max_agents, len(allowed_agents)))
        report_agent_cap = report_max_agents
        try:
            report_min_agents = int(_env_str("LANGGRAPH_REPORT_MIN_AGENTS", "2"))
        except Exception:
            report_min_agents = 2
        report_min_agents = max(1, min(report_min_agents, report_max_agents))
        selection = select_agents_for_request(
            state,
            sorted(allowed_agents),
            max_agents=report_max_agents,
            min_agents=report_min_agents,
        )
        selected_agent_order = [str(name) for name in (selection.get("selected") or []) if isinstance(name, str) and name]
        if selected_agent_order:
            allowed_agents = set(selected_agent_order)
    required_agents = set(agent_selection.get("required") or []) if isinstance(agent_selection, dict) else set()
    if force_all_agents and output_mode == "investment_report":
        required_agents.update(allowed_agents)

    subject = state.get("subject") or {"subject_type": "unknown"}
    query = (state.get("query") or "").strip()
    operation = state.get("operation") or {}
    op_name = operation.get("name") if isinstance(operation, dict) else None
    op_name = str(op_name) if isinstance(op_name, str) and op_name else "qa"
    reply_contract = state.get("reply_contract") if isinstance(state.get("reply_contract"), dict) else {}
    source_constraints = (
        reply_contract.get("source_constraints")
        if isinstance(reply_contract.get("source_constraints"), dict)
        else {}
    )
    requires_links = bool(source_constraints.get("requires_links"))
    disallow_news = bool(source_constraints.get("disallow_news"))
    has_deep_hint = _is_deep_hint(query, state)
    plan_tasks = _plan_tasks_from_state(state)
    plan_task_ids = {str(task.get("id") or "").strip() for task in plan_tasks if str(task.get("id") or "").strip()}

    tickers = subject.get("tickers") if isinstance(subject, dict) else None
    tickers = tickers if isinstance(tickers, list) else []
    tickers = [str(t).strip().upper() for t in tickers if isinstance(t, str) and str(t).strip()]
    primary_ticker = tickers[0] if tickers else None
    subject_type = str(subject.get("subject_type") or "unknown").strip().lower() if isinstance(subject, dict) else "unknown"
    is_macro_subject = subject_type == "macro"
    selection_ids = subject.get("selection_ids") if isinstance(subject, dict) else None
    selection_ids = selection_ids if isinstance(selection_ids, list) else []
    selection_ids = [str(s).strip() for s in selection_ids if isinstance(s, str) and s.strip()]

    goal = plan_payload.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        goal = query or "N/A"
    goal = goal.strip()

    synthesis = plan_payload.get("synthesis")
    if not isinstance(synthesis, dict):
        synthesis = {}
    style = synthesis.get("style")
    style = style if style in ("concise", "structured") else "concise"
    sections = synthesis.get("sections")
    if not isinstance(sections, list):
        sections = []
    sections = [str(s) for s in sections if str(s).strip()][:20]
    safe_synthesis = {"style": style, "sections": sections}

    steps = plan_payload.get("steps") or []
    if not isinstance(steps, list):
        steps = []

    filtered_steps: list[dict[str, Any]] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        kind = step.get("kind")
        name = step.get("name")
        if kind == "tool" and isinstance(name, str) and name in allowed_tools:
            filtered_steps.append(step)
        elif kind == "agent" and isinstance(name, str) and name in allowed_agents:
            filtered_steps.append(step)
        elif kind == "llm" and isinstance(name, str) and name in ("summarize_selection",):
            filtered_steps.append(step)

    def _next_step_id(existing: set[str]) -> str:
        i = 1
        while True:
            candidate = f"s{i}"
            if candidate not in existing:
                existing.add(candidate)
                return candidate
            i += 1

    def _sanitize_step(raw: dict[str, Any], *, existing: set[str]) -> dict[str, Any] | None:
        kind = raw.get("kind")
        name = raw.get("name")
        if kind not in ("tool", "agent", "llm") or not isinstance(name, str) or not name.strip():
            return None

        step_id = raw.get("id")
        step_id = str(step_id).strip() if step_id is not None else ""
        if not step_id or step_id in existing:
            step_id = _next_step_id(existing)
        existing.add(step_id)

        inputs = raw.get("inputs")
        inputs = inputs if isinstance(inputs, dict) else {}
        parallel_group = raw.get("parallel_group")
        parallel_group = str(parallel_group).strip() if isinstance(parallel_group, str) and parallel_group.strip() else None
        why = raw.get("why")
        why = str(why).strip() if isinstance(why, str) and why.strip() else None
        optional = bool(raw.get("optional"))
        raw_depends_on = raw.get("depends_on")
        depends_on = [
            str(value or "").strip()
            for value in (raw_depends_on if isinstance(raw_depends_on, list) else [])
            if str(value or "").strip()
        ]
        raw_task_ids = raw.get("task_ids")
        task_ids = [
            str(value or "").strip()
            for value in (raw_task_ids if isinstance(raw_task_ids, list) else [])
            if str(value or "").strip() in plan_task_ids
        ]
        raw_task_id = str(raw.get("task_id") or "").strip()
        if raw_task_id in plan_task_ids and raw_task_id not in task_ids:
            task_ids.insert(0, raw_task_id)
        if not task_ids and isinstance(parallel_group, str) and parallel_group in plan_task_ids:
            task_ids = [parallel_group]

        # Normalize known tool inputs for robustness.
        if kind == "tool" and name == "get_performance_comparison":
            tickers_value = inputs.get("tickers")
            if isinstance(tickers_value, list):
                mapping = {str(t).strip().upper(): str(t).strip().upper() for t in tickers_value if str(t).strip()}
                inputs = {**inputs, "tickers": mapping}
        elif kind == "tool" and name in ("get_stock_price", "get_technical_snapshot", "get_company_info", "get_company_news"):
            ticker_value = inputs.get("ticker")
            if _is_dashboard_source(state) and primary_ticker:
                # Dashboard 场景强制使用 subject 中的 ticker，防止新闻标题误导 ticker。
                inputs = {**inputs, "ticker": primary_ticker}
            elif (not isinstance(ticker_value, str) or not ticker_value.strip()) and primary_ticker:
                inputs = {**inputs, "ticker": primary_ticker}
            if name == "get_company_news" and requires_links:
                inputs = {**inputs, "fast": False}

        if kind == "agent":
            # Ensure agent steps are runnable and traceable even when the model omits inputs.
            q = inputs.get("query")
            if not isinstance(q, str) or not q.strip():
                inputs = {**inputs, "query": query}

            t = inputs.get("ticker")
            if _is_dashboard_source(state) and primary_ticker:
                inputs = {**inputs, "ticker": primary_ticker}
            elif (not isinstance(t, str) or not t.strip()) and primary_ticker:
                inputs = {**inputs, "ticker": primary_ticker}

            if selection_ids and "selection_ids" not in inputs:
                inputs = {**inputs, "selection_ids": selection_ids}

        sanitized = {
            "id": step_id,
            "kind": kind,
            "name": name.strip(),
            "inputs": inputs,
            "parallel_group": parallel_group,
            "why": why,
            "optional": optional,
            "depends_on": depends_on,
        }
        if task_ids:
            sanitized["task_ids"] = task_ids
            sanitized["task_id"] = task_ids[0]
        return sanitized

    # Enforce selection summary constraint deterministically.
    selection_payload = None
    if isinstance(subject, dict):
        selection_payload = subject.get("selection_payload")
    has_selection = isinstance(selection_payload, list) and bool(selection_payload)
    existing_ids: set[str] = set()
    sanitized_steps: list[dict[str, Any]] = []

    if has_selection:
        # Always keep the first step as selection summarization (high-signal evidence).
        sid = _next_step_id(existing_ids)
        sanitized_steps.append(
            {
                "id": sid,
                "kind": "llm",
                "name": "summarize_selection",
                "inputs": {"selection": selection_payload or [], "query": query},
                "task_ids": [
                    task["id"]
                    for task in plan_tasks
                    if task.get("subject_type") in {"news_item", "news_set", "filing", "research_doc"}
                ],
                "parallel_group": None,
                "why": "Selection is high-signal evidence; summarize it first to avoid redundant tool calls.",
                "optional": False,
            }
        )

    for step in filtered_steps:
        if has_selection and step.get("kind") == "llm" and step.get("name") == "summarize_selection":
            # We insert this step deterministically as the first step.
            continue
        sanitized = _sanitize_step(step, existing=existing_ids)
        if sanitized:
            sanitized_steps.append(sanitized)

    # Enforce operation-specific required steps for reliability.
    existing_tool_names = {s.get("name") for s in sanitized_steps if s.get("kind") == "tool"}
    required_tool_names: set[str] = set()

    def _insert_required_tool(name: str, inputs: dict[str, Any], why: str) -> None:
        if name not in allowed_tools:
            return
        if name in existing_tool_names:
            required_tool_names.add(name)
            for existing_step in sanitized_steps:
                if existing_step.get("kind") == "tool" and existing_step.get("name") == name:
                    existing_step["optional"] = False
            return
        step = {
            "id": _next_step_id(existing_ids),
            "kind": "tool",
            "name": name,
            "inputs": inputs,
            "parallel_group": None,
            "why": why,
            "optional": False,
        }
        # Insert right after selection summary (if present), else at start.
        insert_at = 1 if (sanitized_steps and sanitized_steps[0].get("name") == "summarize_selection") else 0
        sanitized_steps.insert(insert_at, step)
        existing_tool_names.add(name)
        required_tool_names.add(name)

    def _insert_optional_tool(name: str, inputs: dict[str, Any], why: str) -> None:
        if name not in allowed_tools:
            return
        if name in existing_tool_names:
            return
        step = {
            "id": _next_step_id(existing_ids),
            "kind": "tool",
            "name": name,
            "inputs": inputs,
            "parallel_group": None,
            "why": why,
            "optional": True,
        }
        # Keep optional enrichment tools after required tools / selection summary.
        insert_at = 0
        if sanitized_steps and sanitized_steps[0].get("name") == "summarize_selection":
            insert_at = 1
        while (
            insert_at < len(sanitized_steps)
            and sanitized_steps[insert_at].get("kind") == "tool"
            and sanitized_steps[insert_at].get("optional") is False
        ):
            insert_at += 1
        sanitized_steps.insert(insert_at, step)
        existing_tool_names.add(name)

    if op_name == "price" and primary_ticker:
        _insert_required_tool("get_stock_price", {"ticker": primary_ticker}, "Price/quote request: fetch latest price first.")
    if op_name == "technical" and primary_ticker:
        _insert_required_tool("get_stock_price", {"ticker": primary_ticker}, "Technical request: fetch latest price first.")
        _insert_required_tool(
            "get_technical_snapshot",
            {"ticker": primary_ticker},
            "Technical request: compute MA/RSI/MACD snapshot before synthesis.",
        )
    if op_name == "compare" and len(tickers) >= 2:
        mapping = {str(t).strip().upper(): str(t).strip().upper() for t in tickers[:6] if str(t).strip()}
        _insert_required_tool(
            "get_performance_comparison",
            {"tickers": mapping},
            "Compare request: fetch multi-ticker performance baseline (YTD/1Y) first",
        )
    if is_macro_subject:
        _insert_optional_tool(
            "get_current_datetime",
            {},
            "Macro/theme request: anchor the policy and market context to the current date.",
        )
        _insert_optional_tool(
            "get_official_macro_releases",
            {"query": query, "max_results": 8},
            "Macro/theme request: retrieve official macro and central-bank releases first.",
        )
        _insert_optional_tool(
            "get_authoritative_media_news",
            {"query": query, "max_results": 6, "authoritative_only": True},
            "Macro/theme request: add authoritative market interpretation as cross-check evidence.",
        )
        _insert_optional_tool(
            "search",
            {"query": query},
            "Macro/theme request: cover market-impact context not directly present in official releases.",
        )
    if output_mode == "investment_report" and primary_ticker:
        filing_inserter = _insert_required_tool if has_deep_hint else _insert_optional_tool
        if "get_local_market_filings" in allowed_tools:
            filing_inserter(
                "get_local_market_filings",
                {"ticker": primary_ticker, "limit": 8},
                "Report mode: add CN/HK local market disclosures for non-US issuers.",
            )
        else:
            filing_inserter(
                "get_sec_filings",
                {"ticker": primary_ticker, "forms": "10-K,10-Q", "limit": 6},
                "Report mode: add SEC EDGAR 10-K/10-Q filing evidence.",
            )
            filing_inserter(
                "get_sec_company_facts_quarterly",
                {"ticker": primary_ticker, "limit": 8},
                "Report mode: add SEC CompanyFacts quarterly financial metrics.",
            )
            _insert_optional_tool(
                "get_sec_material_events",
                {"ticker": primary_ticker, "limit": 5},
                "Report mode: add SEC 8-K material events as event evidence.",
            )
        if has_deep_hint:
            _insert_required_tool(
                "get_authoritative_media_news",
                {"query": f"{primary_ticker} earnings outlook", "max_results": 6, "authoritative_only": True},
                "Deep financial report: force authoritative media retrieval step.",
            )
            _insert_required_tool(
                "get_earnings_call_transcripts",
                {"ticker": primary_ticker, "limit": 5},
                "Deep financial report: add free earnings-call transcript evidence.",
            )

    company_like_subjects = {"company", "index", "commodity", "fund"}
    link_news_ops = {"fetch", "news_impact", "analyze_impact", "daily_brief", "qa"}
    link_tickers: list[str] = []
    if requires_links and not disallow_news:
        for task in plan_tasks:
            task_subject = str(task.get("subject_type") or "").strip().lower()
            task_op = str(task.get("operation") or "").strip().lower()
            if task_subject not in company_like_subjects or task_op not in link_news_ops:
                continue
            for ticker in task.get("tickers") or []:
                symbol = str(ticker or "").strip().upper()
                if symbol and symbol not in link_tickers:
                    link_tickers.append(symbol)
        if not link_tickers and primary_ticker and subject_type in company_like_subjects and op_name in link_news_ops:
            link_tickers.append(primary_ticker)

    if link_tickers:
        target_ticker = link_tickers[0]
        if "get_company_news" in existing_tool_names:
            for step in sanitized_steps:
                if step.get("kind") != "tool" or step.get("name") != "get_company_news":
                    continue
                inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
                ticker_value = str(inputs.get("ticker") or "").strip().upper()
                if not ticker_value:
                    inputs = {**inputs, "ticker": target_ticker}
                inputs = {**inputs, "fast": False}
                step["inputs"] = inputs
                step["optional"] = False
            required_tool_names.add("get_company_news")
        else:
            _insert_required_tool(
                "get_company_news",
                {"ticker": target_ticker, "limit": 5, "fast": False},
                "Link-required news task: fetch company headlines with article URLs when available.",
            )
        if "get_authoritative_media_news" in existing_tool_names:
            for step in sanitized_steps:
                if step.get("kind") != "tool" or step.get("name") != "get_authoritative_media_news":
                    continue
                inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
                media_query = str(inputs.get("query") or "").strip()
                if target_ticker not in media_query.upper():
                    media_query = f"{target_ticker} {query}".strip()
                try:
                    max_results = int(inputs.get("max_results") or 6)
                except Exception:
                    max_results = 6
                inputs = {
                    **inputs,
                    "query": media_query,
                    "max_results": max_results,
                    "authoritative_only": bool(inputs.get("authoritative_only", False)),
                }
                step["inputs"] = inputs
                step["optional"] = False
            required_tool_names.add("get_authoritative_media_news")
        else:
            _insert_required_tool(
                "get_authoritative_media_news",
                {"query": f"{target_ticker} {query}".strip(), "max_results": 6, "authoritative_only": False},
                "Link-required news task: supplement citable article URLs from media/RSS feeds.",
            )

    default_agent_order = [
        "price_agent",
        "news_agent",
        "fundamental_agent",
        "technical_agent",
        "macro_agent",
        "risk_agent",
        "deep_search_agent",
    ]
    if selected_agent_order:
        agent_order = [name for name in selected_agent_order if name in allowed_agents]
    else:
        agent_order = [name for name in default_agent_order if name in allowed_agents]
    if isinstance(report_agent_cap, int) and report_agent_cap > 0 and not force_all_agents:
        agent_order = agent_order[:report_agent_cap]
    if output_mode == "investment_report" and has_deep_hint and "deep_search_agent" in allowed_agents and not force_all_agents:
        if "deep_search_agent" not in agent_order:
            if isinstance(report_agent_cap, int) and report_agent_cap > 0 and len(agent_order) >= report_agent_cap:
                if report_agent_cap == 1:
                    agent_order = ["deep_search_agent"]
                else:
                    agent_order = agent_order[: report_agent_cap - 1] + ["deep_search_agent"]
            else:
                agent_order.append("deep_search_agent")

    # In report mode, enforce a deterministic score-selected agent baseline.
    if output_mode == "investment_report" and (primary_ticker or is_macro_subject):
        existing_agent_names = {s.get("name") for s in sanitized_steps if s.get("kind") == "agent"}

        insert_at = 0
        if sanitized_steps and sanitized_steps[0].get("kind") == "llm" and sanitized_steps[0].get("name") == "summarize_selection":
            insert_at = 1
        # Keep required tools first, then agents, then optional remainder.
        while (
            insert_at < len(sanitized_steps)
            and sanitized_steps[insert_at].get("kind") == "tool"
            and sanitized_steps[insert_at].get("optional") is False
        ):
            insert_at += 1

        for agent_name in agent_order:
            if agent_name not in allowed_agents:
                continue
            if agent_name in existing_agent_names:
                continue
            is_required_agent = agent_name in required_agents
            force_escalation = agent_name in required_agents or (agent_name == "deep_search_agent" and has_deep_hint)
            agent_inputs = {"query": query, "ticker": primary_ticker or "", "selection_ids": selection_ids}
            if agent_name in _HIGH_COST_AGENTS:
                agent_inputs = {
                    **agent_inputs,
                    "__escalation_stage": "high_cost",
                    "__run_if_min_confidence": float(_env_str("LANGGRAPH_ESCALATION_MIN_CONFIDENCE", "0.72")),
                    "__force_run": bool(force_escalation),
                }
            sanitized_steps.insert(
                insert_at,
                {
                    "id": _next_step_id(existing_ids),
                    "kind": "agent",
                    "name": agent_name,
                    "inputs": agent_inputs,
                    "parallel_group": "report_agents",
                    "why": f"Report mode: run {agent_name} to output explainable cards and evidence.",
                    "optional": not force_escalation and not is_required_agent,
                },
            )
            insert_at += 1
            existing_agent_names.add(agent_name)

    if output_mode == "investment_report":
        escalation_threshold = float(_env_str("LANGGRAPH_ESCALATION_MIN_CONFIDENCE", "0.72"))
        for step in sanitized_steps:
            if step.get("kind") != "agent":
                continue
            name = str(step.get("name") or "")
            if name not in _HIGH_COST_AGENTS:
                continue
            inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
            if "__escalation_stage" not in inputs:
                inputs["__escalation_stage"] = "high_cost"
            if "__run_if_min_confidence" not in inputs:
                inputs["__run_if_min_confidence"] = escalation_threshold
            if "__force_run" not in inputs:
                inputs["__force_run"] = bool(name in required_agents or (name == "deep_search_agent" and has_deep_hint))
            step["inputs"] = inputs

    # Cap tool/agent steps count (rough) to budget.max_tools. Keep required tools first.
    max_tools = int(safe_budget.get("max_tools", 0) or 0)
    if output_mode == "investment_report" and has_deep_hint and primary_ticker:
        # Deep financial reports must keep filing + transcript + authoritative media
        # enrichment in addition to baseline report agents.
        max_tools = max(max_tools, 10)
        safe_budget["max_tools"] = max_tools
    if max_tools > 0:
        # In report mode, prioritize keeping the baseline agent cards so the UI is stable/readable.
        baseline_agents: set[str] = set()
        if output_mode == "investment_report" and (primary_ticker or is_macro_subject):
            baseline_agents = {a for a in agent_order if a in allowed_agents}

        if baseline_agents:
            pinned_remaining = sum(
                1
                for step in sanitized_steps
                if (
                    (step.get("kind") == "agent" and step.get("name") in baseline_agents)
                    or (step.get("kind") == "tool" and step.get("name") in required_tool_names)
                )
            )
            kept: list[dict[str, Any]] = []
            tool_count = 0

            for step in sanitized_steps:
                kind = step.get("kind")
                if kind not in ("tool", "agent"):
                    kept.append(step)
                    continue

                is_pinned = (
                    (kind == "agent" and step.get("name") in baseline_agents)
                    or (kind == "tool" and step.get("name") in required_tool_names)
                )
                if is_pinned:
                    kept.append(step)
                    tool_count += 1
                    pinned_remaining -= 1
                    continue

                # Reserve budget slots for pinned agents not yet encountered.
                if tool_count + pinned_remaining >= max_tools:
                    continue
                kept.append(step)
                tool_count += 1

            sanitized_steps = kept
        else:
            kept: list[dict[str, Any]] = []
            tool_count = 0
            for step in sanitized_steps:
                if step.get("kind") in ("tool", "agent"):
                    tool_count += 1
                    if tool_count > max_tools:
                        continue
                kept.append(step)
            sanitized_steps = kept

    budget_assertions = _build_budget_assertions(sanitized_steps, safe_budget)
    dropped_for_budget: list[str] = []
    if not (budget_assertions.get("cost_within_budget") and budget_assertions.get("latency_within_budget")):
        # Progressive escalation: drop optional high-cost steps first until budget assertions pass.
        drop_order = []
        for idx in range(len(sanitized_steps) - 1, -1, -1):
            step = sanitized_steps[idx]
            if not bool(step.get("optional")):
                continue
            inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
            if bool(inputs.get("__force_run")):
                continue
            kind = str(step.get("kind") or "")
            name = str(step.get("name") or "")
            if kind == "agent" and name in required_agents:
                continue
            is_high_cost_agent = kind == "agent" and name in _HIGH_COST_AGENTS
            drop_order.append((0 if is_high_cost_agent else 1, idx))
        drop_order.sort(key=lambda pair: (pair[0], -pair[1]))
        for _priority, idx in drop_order:
            if idx < 0 or idx >= len(sanitized_steps):
                continue
            step = sanitized_steps[idx]
            dropped_for_budget.append(str(step.get("id") or step.get("name") or f"idx:{idx}"))
            sanitized_steps.pop(idx)
            budget_assertions = _build_budget_assertions(sanitized_steps, safe_budget)
            if budget_assertions.get("cost_within_budget") and budget_assertions.get("latency_within_budget"):
                break
    budget_assertions["dropped_steps"] = dropped_for_budget
    finalize_step_dependencies(sanitized_steps)

    return ({
        "goal": goal,
        "subject": subject,
        "output_mode": output_mode,
        "tasks": _plan_tasks_from_state(state),
        "budget": safe_budget,
        "steps": sanitized_steps,
        "synthesis": safe_synthesis,
    }, budget_assertions)


__all__ = [
    "_HIGH_COST_AGENTS",
    "_build_budget_assertions",
    "_enforce_policy",
    "_estimate_step_cost_latency",
    "_is_dashboard_forced_report",
    "_is_dashboard_source",
    "_is_deep_hint",
    "_plan_tasks_from_state",
]

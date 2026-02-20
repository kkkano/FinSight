# -*- coding: utf-8 -*-
from __future__ import annotations

import os

from backend.graph.capability_registry import REPORT_AGENT_CANDIDATES, select_agents_for_request
from backend.graph.state import GraphState


_DASHBOARD_CORE_AGENTS: tuple[str, ...] = (
    "price_agent",
    "news_agent",
    "fundamental_agent",
    "technical_agent",
    "macro_agent",
    "risk_agent",
)


def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = os.getenv(name)
    if not isinstance(raw, str) or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except Exception:
        return default
    return max(min_value, min(max_value, value))


def _is_dashboard_source(ui_context: dict | None) -> bool:
    if not isinstance(ui_context, dict):
        return False
    source = str(ui_context.get("source") or "").strip().lower()
    return bool(source) and source.startswith("dashboard")


def _infer_market_from_ticker(ticker: str) -> str | None:
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        return None
    if symbol.endswith((".SS", ".SZ", ".BJ")):
        return "CN"
    if symbol.endswith(".HK"):
        return "HK"
    return "US"


def _infer_market_from_subject(subject: dict | None) -> str | None:
    if not isinstance(subject, dict):
        return None
    tickers = subject.get("tickers")
    if not isinstance(tickers, list):
        return None
    for ticker in tickers:
        if not isinstance(ticker, str):
            continue
        inferred = _infer_market_from_ticker(ticker)
        if inferred:
            return inferred
    return None


def _legacy_select_tools(subject_type: str, op_name: str) -> list[str]:
    """Legacy hardcoded allowlist selector kept as manifest fallback."""
    if subject_type in ("news_item", "news_set"):
        return [
            "get_company_news",
            "get_event_calendar",
            "score_news_source_reliability",
            "get_authoritative_media_news",
            "search",
            "get_current_datetime",
        ]
    if subject_type == "company":
        if op_name == "price":
            return [
                "get_stock_price",
                "get_option_chain_metrics",
                "get_current_datetime",
                "search",
            ]
        if op_name == "technical":
            return [
                "get_stock_price",
                "get_technical_snapshot",
                "get_option_chain_metrics",
                "get_current_datetime",
                "search",
            ]
        if op_name == "compare":
            return ["get_performance_comparison", "get_current_datetime", "search"]
        return [
            "get_stock_price",
            "get_technical_snapshot",
            "get_option_chain_metrics",
            "get_company_info",
            "get_company_news",
            "get_event_calendar",
            "get_authoritative_media_news",
            "get_earnings_call_transcripts",
            "score_news_source_reliability",
            "get_local_market_filings",
            "get_earnings_estimates",
            "get_eps_revisions",
            "analyze_historical_drawdowns",
            "get_factor_exposure",
            "run_portfolio_stress_test",
            "get_current_datetime",
            "search",
        ]
    return ["search", "get_current_datetime"]


def policy_gate(state: GraphState) -> dict:
    """
    Phase 3 stub policy gate.

    Responsibilities:
    - Provide a per-request "allowed tools/agents" whitelist
    - Provide a per-request budget (max rounds/tools)
    - Apply user agent_preferences (depth filtering, budget override)

    Later phases will make this stricter (tool schemas, per-subject budgets, safety gates).
    """
    subject = state.get("subject") or {}
    subject_type = subject.get("subject_type") or "unknown"
    output_mode = state.get("output_mode") or "brief"
    operation = state.get("operation") or {}
    op_name = operation.get("name") if isinstance(operation, dict) else None
    op_name = str(op_name) if isinstance(op_name, str) and op_name else "qa"

    # --- Read user preferences from ui_context ---
    ui_context = state.get("ui_context") or {}
    agents_override = ui_context.get("agents_override")
    budget_override = ui_context.get("budget_override")
    analysis_depth_raw = ui_context.get("analysis_depth")
    analysis_depth = (
        str(analysis_depth_raw).strip().lower()
        if isinstance(analysis_depth_raw, str) and str(analysis_depth_raw).strip()
        else None
    )
    if analysis_depth not in {"quick", "report", "deep_research"}:
        analysis_depth = None
    raw_prefs = ui_context.get("agent_preferences") or {}
    agent_preferences: dict = raw_prefs if isinstance(raw_prefs, dict) else {}

    # Budget baseline
    if output_mode == "investment_report":
        budget = {"max_rounds": 6, "max_tools": 8}
    elif output_mode == "chat":
        budget = {"max_rounds": 4, "max_tools": 4}
    else:
        budget = {"max_rounds": 3, "max_tools": 4}

    # Apply budget_override from ui_context (validated: 1-10)
    if isinstance(budget_override, (int, float)):
        clamped = max(1, min(10, int(budget_override)))
        budget["max_rounds"] = clamped

    # Tool whitelist (manifest-first, legacy fallback)
    market_raw = ui_context.get("market") if isinstance(ui_context, dict) else None
    if isinstance(market_raw, str) and market_raw.strip():
        market = str(market_raw).strip().upper()
    else:
        market = _infer_market_from_subject(subject) or "US"
    fallback_reason: str | None = None
    try:
        from backend.tools.manifest import select_tools

        allowed_tools = select_tools(
            subject_type=subject_type,
            operation_name=op_name,
            output_mode=output_mode,
            analysis_depth=analysis_depth,
            market=market,
        )
        if not allowed_tools:
            allowed_tools = _legacy_select_tools(subject_type, op_name)
            fallback_reason = "manifest_empty_selection"
    except Exception:
        allowed_tools = _legacy_select_tools(subject_type, op_name)
        fallback_reason = "manifest_exception"

    # Agent whitelist:
    # Priority: agents_override (explicit) > agent_preferences (depth) > default selection
    allowed_agents: list[str] = []
    agent_selection: dict[str, object] = {}

    # --- agents_override: highest priority (validated against whitelist) ---
    if agents_override and isinstance(agents_override, list):
        validated = [
            a for a in agents_override
            if isinstance(a, str) and a in REPORT_AGENT_CANDIDATES
        ]
        if validated:
            allowed_agents = validated
            agent_selection = {"selected": validated, "override": True}
    elif output_mode == "investment_report":
        dashboard_forced = _is_dashboard_source(ui_context)
        if dashboard_forced:
            allowed_agents = [name for name in _DASHBOARD_CORE_AGENTS if name in REPORT_AGENT_CANDIDATES]
            agent_selection = {
                "selected": allowed_agents,
                "required": list(allowed_agents),
                "forced_by_dashboard": True,
            }
        else:
            max_agents = _env_int("LANGGRAPH_REPORT_MAX_AGENTS", 4, min_value=1, max_value=len(REPORT_AGENT_CANDIDATES))
            min_agents = _env_int("LANGGRAPH_REPORT_MIN_AGENTS", 2, min_value=1, max_value=max_agents)
            selection = select_agents_for_request(
                state,
                REPORT_AGENT_CANDIDATES,
                max_agents=max_agents,
                min_agents=min_agents,
            )
            allowed_agents = list(selection.get("selected") or [])
            scores = selection.get("scores") if isinstance(selection.get("scores"), dict) else {}
            reasons = selection.get("reasons") if isinstance(selection.get("reasons"), dict) else {}
            selected_scores = {name: scores.get(name) for name in allowed_agents}
            selected_reasons = {name: reasons.get(name) for name in allowed_agents}
            agent_selection = {
                "selected": allowed_agents,
                "required": list(selection.get("required") or []),
                "max_agents": max_agents,
                "min_agents": min_agents,
                "scores": selected_scores,
                "reasons": selected_reasons,
            }

            # --- Apply agent_preferences depth filtering (whitelist validated) ---
            _VALID_DEPTHS = {"standard", "deep", "off"}
            pref_agents = agent_preferences.get("agents")
            if isinstance(pref_agents, dict):
                removed_by_prefs: list[str] = []
                for name, depth in pref_agents.items():
                    if not isinstance(name, str) or name not in REPORT_AGENT_CANDIDATES:
                        continue  # Ignore unknown agent names
                    depth_str = str(depth) if depth else "standard"
                    if depth_str not in _VALID_DEPTHS:
                        depth_str = "standard"
                    if depth_str == "off" and name in allowed_agents:
                        allowed_agents.remove(name)
                        removed_by_prefs.append(name)
                    elif depth_str == "deep":
                        # Boost budget for deep analysis
                        budget["max_rounds"] = min(budget["max_rounds"] + 1, 10)
                if removed_by_prefs:
                    agent_selection["removed_by_prefs"] = removed_by_prefs

        if analysis_depth == "report" and "deep_search_agent" in allowed_agents:
            allowed_agents.remove("deep_search_agent")
            removed = list(agent_selection.get("removed_by_analysis_depth") or [])
            removed.append("deep_search_agent")
            agent_selection["removed_by_analysis_depth"] = removed

        if analysis_depth == "deep_research":
            if "deep_search_agent" not in allowed_agents:
                allowed_agents.append("deep_search_agent")
            required_list = [str(x) for x in (agent_selection.get("required") or []) if isinstance(x, str)]
            if "deep_search_agent" not in required_list:
                required_list.append("deep_search_agent")
            agent_selection["required"] = required_list
            budget["max_rounds"] = min(max(int(budget.get("max_rounds", 6)), 7), 10)

    # Tool schemas (Pydantic JSON schema) for planner constraints.
    tool_schemas: dict[str, dict] = {}
    try:  # pragma: no cover - import guard
        from backend.langchain_tools import FINANCIAL_TOOLS

        for tool in FINANCIAL_TOOLS:
            if tool.name not in allowed_tools:
                continue
            schema = None
            args_schema = getattr(tool, "args_schema", None)
            if args_schema and hasattr(args_schema, "model_json_schema"):
                schema = args_schema.model_json_schema()
            tool_schemas[tool.name] = schema or {}
    except Exception:
        # If tool registry import fails, keep schemas empty (planner will fallback).
        tool_schemas = {}

    policy = {
        "budget": budget,
        "allowed_tools": allowed_tools,
        "tool_schemas": tool_schemas,
        "allowed_agents": allowed_agents,
        "analysis_depth": analysis_depth,
        "agent_selection": agent_selection,
        "agent_schemas": {
            name: {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string"},
                    "ticker": {"type": "string"},
                    "selection_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["query"],
            }
            for name in allowed_agents
        },
    }

    trace = state.get("trace") or {}
    trace.update(
        {
            "policy": {
                "output_mode": output_mode,
                "subject_type": subject_type,
                "budget": budget,
                "allowed_tools": allowed_tools,
                "allowed_agents": allowed_agents,
                "analysis_depth": analysis_depth,
                "market": market,
                "tool_selection_fallback": fallback_reason,
                "agent_selection": {
                    "required": list(agent_selection.get("required") or []),
                    "max_agents": agent_selection.get("max_agents"),
                    "min_agents": agent_selection.get("min_agents"),
                },
            }
        }
    )

    return {"policy": policy, "trace": trace}

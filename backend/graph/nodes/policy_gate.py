# -*- coding: utf-8 -*-
from __future__ import annotations

import os

from backend.graph.capability_registry import REPORT_AGENT_CANDIDATES, select_agents_for_request
from backend.graph.state import GraphState


def _env_int(name: str, default: int, *, min_value: int, max_value: int) -> int:
    raw = os.getenv(name)
    if not isinstance(raw, str) or not raw.strip():
        return default
    try:
        value = int(raw.strip())
    except Exception:
        return default
    return max(min_value, min(max_value, value))


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

    # Tool whitelist (minimal, can expand later)
    if subject_type in ("news_item", "news_set"):
        allowed_tools = ["get_company_news", "search", "get_current_datetime"]
    elif subject_type == "company":
        # Keep allowlist tight for better planner accuracy (avoid "grab everything").
        if op_name == "price":
            allowed_tools = ["get_stock_price", "get_current_datetime", "search"]
        elif op_name == "technical":
            allowed_tools = ["get_stock_price", "get_technical_snapshot", "get_current_datetime", "search"]
        elif op_name == "compare":
            allowed_tools = ["get_performance_comparison", "get_current_datetime", "search"]
        else:
            allowed_tools = [
                "get_stock_price",
                "get_technical_snapshot",
                "get_company_info",
                "get_company_news",
                "analyze_historical_drawdowns",
                "get_current_datetime",
                "search",
            ]
    else:
        allowed_tools = ["search", "get_current_datetime"]

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
                "agent_selection": {
                    "required": list(agent_selection.get("required") or []),
                    "max_agents": agent_selection.get("max_agents"),
                    "min_agents": agent_selection.get("min_agents"),
                },
            }
        }
    )

    return {"policy": policy, "trace": trace}

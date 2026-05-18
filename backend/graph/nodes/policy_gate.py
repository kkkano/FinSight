# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re

from backend.graph.capability_registry import REPORT_AGENT_CANDIDATES, select_agents_for_request
from backend.graph.request_task_contract import NEWS_TOOL_NAMES, reply_contract_disallows_news
from backend.graph.state import GraphState


_DASHBOARD_CORE_AGENTS: tuple[str, ...] = (
    "price_agent",
    "news_agent",
    "fundamental_agent",
    "technical_agent",
    "macro_agent",
    "risk_agent",
)


_DEEP_RESEARCH_HINTS: tuple[str, ...] = (
    "deep report",
    "deep research",
    "deep dive",
    "longform",
    "filing",
    "10-k",
    "10-q",
    "earnings call",
    "transcript",
    "深度",
    "深度研报",
    "深度研究",
    "财报电话会",
)

_SEC_HOLDINGS_TOOL_NAMES: tuple[str, ...] = (
    "get_institutional_holdings",
    "get_institution_holdings_by_ticker",
    "get_insider_transactions",
    "get_holdings_overlap",
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


def _is_truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(str(needle or "").lower() in lowered for needle in needles)


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


def _ready_understanding_tasks(state: GraphState) -> list[dict]:
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        return []
    ready: list[dict] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        status = str(task.get("status") or "ready").strip().lower()
        if status == "blocked":
            continue
        ready.append(task)
    return ready


def _state_contains_url_reference(state: GraphState, ui_context: dict) -> bool:
    query = str(state.get("query") or "")
    if re.search(r"https?://[^\s<>\]\)\"']+", query, re.IGNORECASE):
        return True
    raw_selections = ui_context.get("selections")
    if not raw_selections and isinstance(ui_context.get("selection"), dict):
        raw_selections = [ui_context["selection"]]
    if not isinstance(raw_selections, list):
        return False
    for item in raw_selections:
        if isinstance(item, dict) and str(item.get("url") or "").startswith(("http://", "https://")):
            return True
    return False


def _task_operation_name(task: dict) -> str:
    operation = task.get("operation")
    if isinstance(operation, dict):
        name = operation.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return "qa"


def _task_subject_type(task: dict) -> str:
    value = task.get("subject_type")
    return str(value).strip().lower() if isinstance(value, str) and value.strip() else "unknown"


def _infer_market_from_task(task: dict, fallback: str) -> str:
    tickers = task.get("tickers")
    if isinstance(tickers, list):
        for ticker in tickers:
            if not isinstance(ticker, str):
                continue
            inferred = _infer_market_from_ticker(ticker)
            if inferred:
                return inferred
    return fallback


def _with_us_holdings_tools(tools: list[str], *, subject_type: str, op_name: str, market: str) -> list[str]:
    if market != "US" or op_name != "holdings" or subject_type not in {"company", "portfolio"}:
        return tools
    result = list(tools)
    seen = set(result)
    for tool_name in _SEC_HOLDINGS_TOOL_NAMES:
        if tool_name in seen:
            continue
        seen.add(tool_name)
        result.append(tool_name)
    return result


def _without_holdings_tools(tools: list[str]) -> list[str]:
    return [tool_name for tool_name in tools if tool_name not in _SEC_HOLDINGS_TOOL_NAMES]


def _legacy_select_tools(subject_type: str, op_name: str) -> list[str]:
    """Legacy hardcoded allowlist selector kept as manifest fallback."""
    if op_name == "holdings" and subject_type in {"company", "portfolio"}:
        return [
            "get_institutional_holdings",
            "get_institution_holdings_by_ticker",
            "get_insider_transactions",
            "get_holdings_overlap",
            "get_current_datetime",
            "search",
        ]
    if op_name == "screen":
        return ["screen_stocks", "search", "get_current_datetime"]
    if op_name == "cn_market":
        return [
            "get_cn_market_fund_flow",
            "get_cn_market_northbound",
            "get_cn_limit_board",
            "get_cn_lhb",
            "get_cn_concept_map",
            "search",
            "get_current_datetime",
        ]
    if op_name == "backtest":
        return ["run_strategy_backtest", "search", "get_current_datetime"]
    if op_name == "morning_brief":
        return ["get_stock_price", "get_company_news", "get_current_datetime"]
    if subject_type in ("news_item", "news_set"):
        return [
            "fetch_url_content",
            "get_company_news",
            "get_event_calendar",
            "score_news_source_reliability",
            "get_authoritative_media_news",
            "search",
            "get_current_datetime",
        ]
    if subject_type in ("filing", "research_doc"):
        return ["fetch_url_content", "search", "get_current_datetime"]
    if subject_type == "macro":
        return [
            "get_official_macro_releases",
            "get_authoritative_media_news",
            "search",
            "get_current_datetime",
        ]
    if subject_type in ("theme", "unknown"):
        return [
            "fetch_url_content",
            "get_authoritative_media_news",
            "search",
            "get_current_datetime",
        ]
    if subject_type in ("company", "index", "commodity"):
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
            return [
                "get_performance_comparison",
                "get_stock_price",
                "get_company_news",
                "get_company_info",
                "get_current_datetime",
                "search",
            ]
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
    return ["fetch_url_content", "search", "get_current_datetime"]


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
    if analysis_depth is None and output_mode == "investment_report":
        query_text = str(state.get("query") or "")
        analysis_depth = "deep_research" if _contains_any(query_text, _DEEP_RESEARCH_HINTS) else "report"
    raw_prefs = ui_context.get("agent_preferences") or {}
    agent_preferences: dict = raw_prefs if isinstance(raw_prefs, dict) else {}

    # Budget baseline
    ready_tasks = _ready_understanding_tasks(state)

    if output_mode == "investment_report":
        budget = {"max_rounds": 6, "max_tools": 8}
    elif output_mode == "chat":
        budget = {"max_rounds": 4, "max_tools": 4}
    else:
        budget = {"max_rounds": 3, "max_tools": 4}

    if ready_tasks:
        task_count = len(ready_tasks)
        if output_mode == "investment_report":
            budget["max_tools"] = max(budget["max_tools"], min(18, task_count * 3))
        elif output_mode == "chat":
            budget["max_tools"] = max(budget["max_tools"], min(10, task_count * 2))
        else:
            budget["max_tools"] = max(budget["max_tools"], min(12, task_count * 2))

    # Apply budget_override from ui_context (validated: 1-10)
    if isinstance(budget_override, (int, float)):
        clamped = max(1, min(10, int(budget_override)))
        budget["max_rounds"] = clamped

    # Tool whitelist (manifest-first, legacy fallback)
    market_raw = ui_context.get("market") if isinstance(ui_context, dict) else None
    if isinstance(market_raw, str) and market_raw.strip():
        market = str(market_raw).strip().upper()
        market_explicit = True
    else:
        market = _infer_market_from_subject(subject) or "US"
        market_explicit = False
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
        allowed_tools = _with_us_holdings_tools(
            list(allowed_tools),
            subject_type=str(subject_type).strip().lower(),
            op_name=op_name,
            market=market,
        )
        if subject_type in {"index", "commodity"}:
            for tool_name in _legacy_select_tools(subject_type, op_name):
                if tool_name not in allowed_tools:
                    allowed_tools.append(tool_name)
        if ready_tasks:
            union_tools = list(allowed_tools)
            seen_tools = set(union_tools)
            for task in ready_tasks:
                task_subject_type = _task_subject_type(task)
                task_op_name = _task_operation_name(task)
                task_market = market if market_explicit else _infer_market_from_task(task, market)
                task_tools = select_tools(
                    subject_type=task_subject_type,
                    operation_name=task_op_name,
                    output_mode=output_mode,
                    analysis_depth=analysis_depth,
                    market=task_market,
                )
                if not task_tools:
                    task_tools = _legacy_select_tools(task_subject_type, task_op_name)
                task_tools = _with_us_holdings_tools(
                    list(task_tools),
                    subject_type=task_subject_type,
                    op_name=task_op_name,
                    market=task_market,
                )
                if task_subject_type in {"index", "commodity"}:
                    task_tools = list(task_tools) + [
                        name for name in _legacy_select_tools(task_subject_type, task_op_name)
                        if name not in task_tools
                    ]
                for tool_name in task_tools:
                    if tool_name in seen_tools:
                        continue
                    seen_tools.add(tool_name)
                    union_tools.append(tool_name)
            allowed_tools = union_tools
    except Exception:
        allowed_tools = _legacy_select_tools(subject_type, op_name)
        fallback_reason = "manifest_exception"
        allowed_tools = _with_us_holdings_tools(
            list(allowed_tools),
            subject_type=str(subject_type).strip().lower(),
            op_name=op_name,
            market=market,
        )
        if ready_tasks:
            union_tools = list(allowed_tools)
            seen_tools = set(union_tools)
            for task in ready_tasks:
                task_subject_type = _task_subject_type(task)
                task_op_name = _task_operation_name(task)
                task_market = market if market_explicit else _infer_market_from_task(task, market)
                task_tools = _with_us_holdings_tools(
                    _legacy_select_tools(task_subject_type, task_op_name),
                    subject_type=task_subject_type,
                    op_name=task_op_name,
                    market=task_market,
                )
                for tool_name in task_tools:
                    if tool_name in seen_tools:
                        continue
                    seen_tools.add(tool_name)
                    union_tools.append(tool_name)
            allowed_tools = union_tools

    if market != "US":
        allowed_tools = _without_holdings_tools(list(allowed_tools))

    if _state_contains_url_reference(state, ui_context) and "fetch_url_content" not in allowed_tools:
        allowed_tools = ["fetch_url_content", *allowed_tools]
        budget["max_tools"] = max(int(budget.get("max_tools", 0)), 1)

    if output_mode != "investment_report" and reply_contract_disallows_news(state):
        allowed_tools = [tool_name for tool_name in allowed_tools if tool_name not in NEWS_TOOL_NAMES]

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
        force_all_agents = _is_truthy(ui_context.get("ensure_all_agents")) if isinstance(ui_context, dict) else False
        dashboard_forced = _is_dashboard_source(ui_context)
        if force_all_agents:
            allowed_agents = list(REPORT_AGENT_CANDIDATES)
            agent_selection = {
                "selected": list(allowed_agents),
                "required": list(allowed_agents),
                "force_all_agents": True,
            }
        elif dashboard_forced:
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

        if (
            analysis_depth == "report"
            and not bool(agent_selection.get("force_all_agents"))
            and "deep_search_agent" in allowed_agents
        ):
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
        "force_all_agents": bool(agent_selection.get("force_all_agents")),
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
                "understanding_task_count": len(ready_tasks),
                "agent_selection": {
                    "required": list(agent_selection.get("required") or []),
                    "max_agents": agent_selection.get("max_agents"),
                    "min_agents": agent_selection.get("min_agents"),
                },
            }
        }
    )

    return {"policy": policy, "trace": trace}

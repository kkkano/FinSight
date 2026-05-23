# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import re

from backend.graph.earnings_intent import query_requests_earnings_price_impact
from backend.graph.capability_registry import REPORT_AGENT_CANDIDATES, select_agents_for_request
from backend.graph.intent_contract import (
    canonical_evidence_kinds,
    evidence_agents_for_kinds,
    evidence_plan_for_contract,
    evidence_plan_for_kinds,
    evidence_tools_for_kinds,
    is_valuation_contract,
)
from backend.graph.request_task_contract import NEWS_TOOL_NAMES, reply_contract_disallows_news
from backend.graph.state import GraphState
from backend.graph.understanding_v2 import (
    VALUATION_COMPARE_LIGHT_PROFILE,
    evidence_profiles,
    project_v2_tasks_to_legacy,
)


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

_VALUATION_COMPARE_LIGHT_TOOLS: tuple[str, ...] = (
    "get_stock_price",
    "get_company_info",
    "get_earnings_estimates",
    "get_current_datetime",
    "search",
)

_SHORT_RESEARCH_AGENT_CONFIG: dict[str, dict[str, object]] = {
    "earnings_impact": {
        "max_agents": 3,
        "min_agents": 2,
        "max_rounds": 5,
        "max_tools": 9,
        "reason": "semantic_earnings_price_impact_request",
    },
    "earnings_performance": {
        "max_agents": 2,
        "min_agents": 1,
        "max_rounds": 5,
        "max_tools": 8,
        "reason": "semantic_earnings_performance_request",
    },
    "investment_opinion": {
        "max_agents": 4,
        "min_agents": 3,
        "max_rounds": 5,
        "max_tools": 8,
        "reason": "semantic_investment_opinion_request",
    },
    "technical": {
        "max_agents": 1,
        "min_agents": 1,
        "max_rounds": 4,
        "max_tools": 5,
        "reason": "semantic_technical_indicator_request",
    },
}


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


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return _is_truthy(raw)


def _agent_research_config(agent_preferences: dict) -> dict[str, int | bool]:
    """Build the per-agent research config.

    ``FINSIGHT_FORCE_AGENT_RESEARCH_CONFIG`` is an ops override for production
    experiments: it wins over stale browser-local preferences that still submit
    ``enableLLMAnalysis=false``.
    """

    forced = _env_bool("FINSIGHT_FORCE_AGENT_RESEARCH_CONFIG", False)
    env_reflections = _env_int(
        "FINSIGHT_AGENT_REFLECTION_ROUNDS",
        _env_int("BASE_AGENT_MAX_REFLECTIONS", 3 if forced else 0, min_value=0, max_value=3),
        min_value=0,
        max_value=3,
    )
    env_analysis_timeout = _env_int(
        "FINSIGHT_AGENT_ANALYSIS_TIMEOUT_SECONDS",
        _env_int("AGENT_LLM_ANALYZE_CALL_TIMEOUT_SECONDS", 120 if forced else 0, min_value=0, max_value=120),
        min_value=0,
        max_value=120,
    )
    env_token_timeout = _env_int(
        "FINSIGHT_AGENT_TOKEN_ACQUIRE_TIMEOUT_SECONDS",
        _env_int("AGENT_LLM_ANALYZE_TIMEOUT_SECONDS", 60 if forced else 0, min_value=0, max_value=60),
        min_value=0,
        max_value=60,
    )

    if forced:
        return {
            "enable_llm_analysis": True,
            "max_reflections": env_reflections,
            "analysis_timeout_seconds": env_analysis_timeout,
            "token_acquire_timeout_seconds": env_token_timeout,
        }

    enable_default = _env_bool("AGENT_LLM_ANALYZE_ENABLED", False)
    pref_enable = agent_preferences.get("enableLLMAnalysis")
    enable_llm = pref_enable if isinstance(pref_enable, bool) else enable_default

    def _pref_int(key: str, default: int, *, min_value: int, max_value: int) -> int:
        raw = agent_preferences.get(key)
        try:
            value = int(raw)
        except Exception:
            value = default
        return max(min_value, min(max_value, value))

    return {
        "enable_llm_analysis": bool(enable_llm),
        "max_reflections": _pref_int("reflectionRounds", env_reflections, min_value=0, max_value=3),
        "analysis_timeout_seconds": _pref_int(
            "analysisTimeoutSeconds",
            env_analysis_timeout,
            min_value=0,
            max_value=120,
        ),
        "token_acquire_timeout_seconds": _pref_int(
            "tokenAcquireTimeoutSeconds",
            env_token_timeout,
            min_value=0,
            max_value=60,
        ),
    }


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    lowered = str(text or "").lower()
    return any(str(needle or "").lower() in lowered for needle in needles)


def _append_missing(items: list[str], names: tuple[str, ...]) -> list[str]:
    seen = set(items)
    for name in names:
        if name in seen:
            continue
        items.append(name)
        seen.add(name)
    return items


def _task_param_profiles(tasks: list[dict]) -> set[str]:
    profiles: set[str] = set()
    for task in tasks:
        operation = task.get("operation") if isinstance(task.get("operation"), dict) else {}
        params = operation.get("params") if isinstance(operation.get("params"), dict) else {}
        for key in ("evidence_profile", "comparison_data_profile", "budget_profile"):
            value = str(params.get(key) or "").strip()
            if value:
                profiles.add(value)
        if str(params.get("evidence_focus") or "").strip().lower() == "valuation":
            profiles.add(VALUATION_COMPARE_LIGHT_PROFILE)
    return profiles


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
        tasks = project_v2_tasks_to_legacy(state.get("understanding_v2"))
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


def _has_ready_operation(tasks: list[dict], operation_name: str) -> bool:
    target = str(operation_name or "").strip().lower()
    if not target:
        return False
    return any(_task_operation_name(task).strip().lower() == target for task in tasks)


def _operation_params(operation: object) -> dict:
    if isinstance(operation, dict) and isinstance(operation.get("params"), dict):
        return operation.get("params") or {}
    return {}


def _required_evidence_from_state(
    *,
    intent_contract: dict,
    operation: object,
    ready_tasks: list[dict],
) -> list[str]:
    required: list[str] = []
    contract_required = intent_contract.get("required_evidence") if isinstance(intent_contract, dict) else []
    if isinstance(contract_required, list):
        required.extend(str(item) for item in contract_required if str(item).strip())
    op_required = _operation_params(operation).get("required_evidence")
    if isinstance(op_required, list):
        required.extend(str(item) for item in op_required if str(item).strip())
    for task in ready_tasks:
        task_operation = task.get("operation")
        task_required = _operation_params(task_operation).get("required_evidence")
        if isinstance(task_required, list):
            required.extend(str(item) for item in task_required if str(item).strip())
        task_params = task.get("params")
        if isinstance(task_params, dict) and isinstance(task_params.get("required_evidence"), list):
            required.extend(str(item) for item in task_params.get("required_evidence") if str(item).strip())
    return canonical_evidence_kinds(required)


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


def _filter_tools_for_market(tools: list[str], *, market: str) -> list[str]:
    market_norm = str(market or "US").strip().upper() or "US"
    try:
        from backend.tools.manifest import TOOL_MANIFEST

        markets_by_tool = {entry.name: set(entry.markets) for entry in TOOL_MANIFEST}
    except Exception:
        markets_by_tool = {}
    filtered: list[str] = []
    seen: set[str] = set()
    for tool_name in tools:
        if tool_name in seen:
            continue
        seen.add(tool_name)
        markets = markets_by_tool.get(tool_name)
        if markets and market_norm not in markets:
            continue
        filtered.append(tool_name)
    return filtered


def _with_earnings_impact_tools(tools: list[str], *, market: str) -> list[str]:
    result = list(tools)
    seen = set(result)
    required = [
        "get_stock_price",
        "get_company_info",
        "get_company_news",
        "get_authoritative_media_news",
        "get_earnings_call_transcripts",
        "get_earnings_estimates",
        "get_eps_revisions",
        "analyze_historical_drawdowns",
        "get_current_datetime",
        "search",
    ]
    if str(market or "").strip().upper() == "US":
        required.insert(2, "get_sec_company_facts_quarterly")
    else:
        required.insert(2, "get_local_market_filings")
    for tool_name in required:
        if tool_name in seen:
            continue
        seen.add(tool_name)
        result.append(tool_name)
    return result


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
    query_text = str(state.get("query") or "")
    intent_contract = state.get("intent_contract") if isinstance(state.get("intent_contract"), dict) else {}
    valuation_contract = bool(is_valuation_contract(intent_contract))

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
    required_evidence = _required_evidence_from_state(
        intent_contract=intent_contract,
        operation=operation,
        ready_tasks=ready_tasks,
    )
    v2_profiles = set(evidence_profiles(state.get("understanding_v2")))
    v2_profiles.update(_task_param_profiles(ready_tasks))
    valuation_compare_light = VALUATION_COMPARE_LIGHT_PROFILE in v2_profiles
    earnings_impact_requested = (
        op_name == "earnings_impact"
        or _has_ready_operation(ready_tasks, "earnings_impact")
        or query_requests_earnings_price_impact(query_text)
    )

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

    evidence_tools = evidence_tools_for_kinds(required_evidence, market=market)
    if evidence_tools:
        allowed_tools = _append_missing(list(allowed_tools), tuple(evidence_tools + ["get_current_datetime", "search"]))
        budget["max_tools"] = max(int(budget.get("max_tools", 4)), min(12, len(evidence_tools) + len(ready_tasks) + 2))

    if earnings_impact_requested:
        allowed_tools = _with_earnings_impact_tools(list(allowed_tools), market=market)
        budget["max_tools"] = max(int(budget.get("max_tools", 4)), 9)

    if valuation_contract:
        budget["max_rounds"] = max(int(budget.get("max_rounds", 4)), 4)
        budget["max_tools"] = max(int(budget.get("max_tools", 4)), 6)

    if _state_contains_url_reference(state, ui_context) and "fetch_url_content" not in allowed_tools:
        allowed_tools = ["fetch_url_content", *allowed_tools]
        budget["max_tools"] = max(int(budget.get("max_tools", 0)), 1)

    if output_mode != "investment_report" and reply_contract_disallows_news(state):
        allowed_tools = [tool_name for tool_name in allowed_tools if tool_name not in NEWS_TOOL_NAMES]

    if valuation_compare_light and output_mode != "investment_report":
        allowed_tools = [
            tool_name for tool_name in _append_missing(list(allowed_tools), _VALUATION_COMPARE_LIGHT_TOOLS)
            if tool_name in _VALUATION_COMPARE_LIGHT_TOOLS
        ]
        budget["max_rounds"] = max(int(budget.get("max_rounds", 4)), 4)
        budget["max_tools"] = max(int(budget.get("max_tools", 4)), 6)

    if isinstance(state.get("understanding_v2"), dict):
        default_cap = 18 if output_mode == "investment_report" else (10 if output_mode == "chat" else 12)
        global_cap = _env_int("FINSIGHT_UNDERSTANDING_V2_MAX_TOOLS", default_cap, min_value=1, max_value=40)
        mode_env = f"FINSIGHT_UNDERSTANDING_V2_{str(output_mode).upper()}_MAX_TOOLS"
        mode_cap = _env_int(mode_env, global_cap, min_value=1, max_value=40)
        budget["max_tools"] = min(int(budget.get("max_tools", mode_cap)), mode_cap)

    allowed_tools = _filter_tools_for_market(list(allowed_tools), market=market)

    # Agent whitelist:
    # Priority: agents_override (explicit) > evidence contract > v2 shadow profile
    # > agent_preferences (depth) > default selection.
    allowed_agents: list[str] = []
    agent_selection: dict[str, object] = {}
    evidence_agents = [
        name
        for name in evidence_agents_for_kinds(required_evidence, market=market)
        if name in REPORT_AGENT_CANDIDATES
    ]
    short_research_operation = ""
    if earnings_impact_requested:
        short_research_operation = "earnings_impact"
    elif op_name == "earnings_performance" or _has_ready_operation(ready_tasks, "earnings_performance"):
        short_research_operation = "earnings_performance"
    elif op_name == "investment_opinion" or _has_ready_operation(ready_tasks, "investment_opinion"):
        short_research_operation = "investment_opinion"
    elif op_name == "technical" or _has_ready_operation(ready_tasks, "technical"):
        short_research_operation = "technical"

    if agents_override and isinstance(agents_override, list):
        validated = [
            a for a in agents_override
            if isinstance(a, str) and a in REPORT_AGENT_CANDIDATES
        ]
        if validated:
            allowed_agents = validated
            agent_selection = {"selected": validated, "override": True}
    elif evidence_agents and output_mode != "investment_report":
        allowed_agents = list(evidence_agents)
        agent_selection = {
            "selected": list(allowed_agents),
            "required": list(allowed_agents),
            "reason": "intent_contract_required_evidence",
            "selection_mode": "research_obligation",
            "required_evidence": list(required_evidence),
            "budget_profile": str(intent_contract.get("budget_profile") or "default"),
        }
    elif valuation_compare_light and output_mode != "investment_report":
        allowed_agents = ["fundamental_agent"]
        agent_selection = {
            "selected": list(allowed_agents),
            "required": list(allowed_agents),
            "reason": "understanding_v2_valuation_evidence",
            "selection_mode": "evidence_profile",
            "budget_profile": VALUATION_COMPARE_LIGHT_PROFILE,
        }
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
            agent_selection = {
                "selected": allowed_agents,
                "required": list(selection.get("required") or []),
                "max_agents": max_agents,
                "min_agents": min_agents,
                "scores": {name: scores.get(name) for name in allowed_agents},
                "reasons": {name: reasons.get(name) for name in allowed_agents},
            }

            valid_depths = {"standard", "deep", "off"}
            pref_agents = agent_preferences.get("agents")
            if isinstance(pref_agents, dict):
                removed_by_prefs: list[str] = []
                for name, depth in pref_agents.items():
                    if not isinstance(name, str) or name not in REPORT_AGENT_CANDIDATES:
                        continue
                    depth_str = str(depth) if depth else "standard"
                    if depth_str not in valid_depths:
                        depth_str = "standard"
                    if depth_str == "off" and name in allowed_agents:
                        allowed_agents.remove(name)
                        removed_by_prefs.append(name)
                    elif depth_str == "deep":
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
    elif short_research_operation:
        config = _SHORT_RESEARCH_AGENT_CONFIG[short_research_operation]
        selection_state = {
            **state,
            "operation": {"name": short_research_operation, "confidence": 0.9, "params": {}},
        }
        max_agents = int(config.get("max_agents") or 1)
        min_agents = int(config.get("min_agents") or 1)
        selection = select_agents_for_request(
            selection_state,
            REPORT_AGENT_CANDIDATES,
            max_agents=max_agents,
            min_agents=min_agents,
        )
        allowed_agents = list(selection.get("selected") or [])
        scores = selection.get("scores") if isinstance(selection.get("scores"), dict) else {}
        reasons = selection.get("reasons") if isinstance(selection.get("reasons"), dict) else {}
        agent_selection = {
            "selected": list(allowed_agents),
            "required": list(selection.get("required") or []),
            "max_agents": max_agents,
            "min_agents": min_agents,
            "scores": {name: scores.get(name) for name in allowed_agents},
            "reasons": {name: reasons.get(name) for name in allowed_agents},
            "reason": str(config.get("reason") or "semantic_short_research_request"),
            "selection_mode": "capability_score",
        }
        budget["max_rounds"] = max(int(budget.get("max_rounds", 4)), int(config.get("max_rounds") or 4))
        budget["max_tools"] = max(int(budget.get("max_tools", 4)), int(config.get("max_tools") or 4))

        pref_agents = agent_preferences.get("agents")
        if isinstance(pref_agents, dict):
            removed_by_prefs: list[str] = []
            for name in list(allowed_agents):
                if str(pref_agents.get(name) or "").strip().lower() == "off":
                    allowed_agents.remove(name)
                    removed_by_prefs.append(name)
            if removed_by_prefs:
                agent_selection["selected"] = list(allowed_agents)
                agent_selection["required"] = [
                    name for name in (agent_selection.get("required") or []) if name not in removed_by_prefs
                ]
                agent_selection["removed_by_prefs"] = removed_by_prefs
    elif agent_preferences:
        if agent_preferences.get("include_all"):
            allowed_agents = list(REPORT_AGENT_CANDIDATES)
        else:
            requested = agent_preferences.get("agents")
            if isinstance(requested, list):
                allowed_agents = [
                    a for a in requested
                    if isinstance(a, str) and a in REPORT_AGENT_CANDIDATES
                ]
        agent_selection = {"selected": list(allowed_agents), "preferences": True}
    else:
        allowed_agents = []
        agent_selection = {"selected": [], "reason": "brief_or_tool_only"}
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
        "required_evidence": list(required_evidence),
        "evidence_plan": evidence_plan_for_contract(intent_contract, market=market)
        if intent_contract
        else evidence_plan_for_kinds(required_evidence, market=market),
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
        "agent_research_config": _agent_research_config(agent_preferences),
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

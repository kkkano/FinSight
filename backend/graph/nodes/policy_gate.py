# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.graph.capability_registry import (
    REPORT_AGENT_CANDIDATES,
    select_agents_for_request,
)
from backend.graph.earnings_intent import query_requests_earnings_price_impact
from backend.graph.intent_contract import (
    canonical_evidence_kinds,
    evidence_agents_for_kinds,
    evidence_plan_for_contract,
    evidence_plan_for_kinds,
    evidence_tools_for_kinds,
    is_valuation_contract,
)
from backend.graph.policy.runtime import (
    _agent_research_config as _agent_research_config,
)
from backend.graph.policy.runtime import (
    _append_missing as _append_missing,
)
from backend.graph.policy.runtime import (
    _contains_any as _contains_any,
)
from backend.graph.policy.runtime import (
    _env_bool as _env_bool,
)
from backend.graph.policy.runtime import (
    _bounded_env_int as _env_int,
)
from backend.graph.policy.runtime import (
    _has_ready_operation as _has_ready_operation,
)
from backend.graph.policy.runtime import (
    _infer_market_from_subject as _infer_market_from_subject,
)
from backend.graph.policy.runtime import (
    _infer_market_from_task as _infer_market_from_task,
)
from backend.graph.policy.runtime import (
    _infer_market_from_ticker as _infer_market_from_ticker,
)
from backend.graph.policy.runtime import (
    _is_dashboard_source as _is_dashboard_source,
)
from backend.graph.policy.runtime import (
    _is_truthy as _is_truthy,
)
from backend.graph.policy.runtime import (
    _operation_params as _operation_params,
)
from backend.graph.policy.runtime import (
    _ready_understanding_tasks as _ready_understanding_tasks,
)
from backend.graph.policy.runtime import (
    _request_frame_evidence_from_state as _request_frame_evidence_from_state,
)
from backend.graph.policy.runtime import (
    _request_frame_results_from_state as _request_frame_results_from_state,
)
from backend.graph.policy.runtime import (
    _request_frames_from_state as _request_frames_from_state,
)
from backend.graph.policy.runtime import (
    _required_evidence_from_state as _required_evidence_from_state,
)
from backend.graph.policy.runtime import (
    _state_contains_url_reference as _state_contains_url_reference,
)
from backend.graph.policy.runtime import (
    _task_operation_name as _task_operation_name,
)
from backend.graph.policy.runtime import (
    _task_param_profiles as _task_param_profiles,
)
from backend.graph.policy.runtime import (
    _task_subject_type as _task_subject_type,
)
from backend.graph.policy.tools import (
    _ACTION_RESULT_TOOLS as _ACTION_RESULT_TOOLS,
)
from backend.graph.policy.tools import (
    _SEC_HOLDINGS_TOOL_NAMES as _SEC_HOLDINGS_TOOL_NAMES,
)
from backend.graph.policy.tools import (
    _VALUATION_COMPARE_LIGHT_TOOLS as _VALUATION_COMPARE_LIGHT_TOOLS,
)
from backend.graph.policy.tools import (
    _filter_tools_for_market as _filter_tools_for_market,
)
from backend.graph.policy.tools import (
    _legacy_select_tools as _legacy_select_tools,
)
from backend.graph.policy.tools import (
    _tools_for_required_results as _tools_for_required_results,
)
from backend.graph.policy.tools import (
    _valuation_compare_light_tool_floor as _valuation_compare_light_tool_floor,
)
from backend.graph.policy.tools import (
    _with_earnings_impact_tools as _with_earnings_impact_tools,
)
from backend.graph.policy.tools import (
    _with_us_holdings_tools as _with_us_holdings_tools,
)
from backend.graph.policy.tools import (
    _without_holdings_tools as _without_holdings_tools,
)
from backend.graph.request_facets import derive_request_facets
from backend.graph.request_task_contract import (
    NEWS_TOOL_NAMES,
    reply_contract_disallows_news,
)
from backend.graph.state import GraphState
from backend.graph.understanding_v2 import (
    VALUATION_COMPARE_LIGHT_PROFILE,
    evidence_profiles,
)
from backend.skills.registry import get_builtin_skill_registry
from backend.skills.selector import extract_explicit_skill, select_skill_for_facets

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
    facets = state.get("facets") if isinstance(state.get("facets"), dict) else derive_request_facets(
        query=query_text,
        operation=operation if isinstance(operation, dict) else {},
        subject=subject if isinstance(subject, dict) else {},
    )
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
    explicit_skill = (
        str(ui_context.get("skill") or ui_context.get("selected_skill") or "").strip()
        if isinstance(ui_context, dict)
        else ""
    ) or (extract_explicit_skill(query_text) or "")
    skill_registry = get_builtin_skill_registry()
    skill_selection_model = select_skill_for_facets(
        facets,
        registry=skill_registry,
        explicit_skill=explicit_skill or None,
    )
    skill_manifest = skill_registry.get(skill_selection_model.selected_skill or "")
    skill_selection: dict[str, object] = {
        "selected_skill": skill_selection_model.selected_skill,
        "reason": skill_selection_model.reason,
        "candidates": skill_selection_model.candidates,
    }
    if skill_manifest is not None:
        skill_selection.update(
            {
                "preferred_tools": list(skill_manifest.preferred_tools),
                "preferred_agents": list(skill_manifest.preferred_agents),
                "optional_python_operations": list(skill_manifest.optional_python_operations),
                "output_contract": dict(skill_manifest.output_contract),
                "risk_level": skill_manifest.risk_level,
                "perspective": skill_manifest.perspective,
                "display_name": skill_manifest.display_name or skill_manifest.name,
                "category": skill_manifest.category,
            }
        )

    # Budget baseline
    ready_tasks = _ready_understanding_tasks(state)
    opinion_missing_subject = bool(
        (op_name == "investment_opinion" or _has_ready_operation(ready_tasks, "investment_opinion"))
        and not any(
            isinstance(task.get("tickers"), list) and any(str(item or "").strip() for item in task["tickers"])
            for task in ready_tasks
        )
    )
    required_evidence = _required_evidence_from_state(
        intent_contract=intent_contract,
        operation=operation,
        ready_tasks=ready_tasks,
    )
    request_frame_evidence = _request_frame_evidence_from_state(state)
    if request_frame_evidence:
        required_evidence = canonical_evidence_kinds(list(required_evidence) + list(request_frame_evidence))
    required_results = _request_frame_results_from_state(state)
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

    action_tools = _tools_for_required_results(required_results)
    if action_tools:
        allowed_tools = _append_missing(list(allowed_tools), tuple(action_tools))
        budget["max_tools"] = max(int(budget.get("max_tools", 4)), min(12, len(action_tools) + len(ready_tasks) + 2))

    if earnings_impact_requested:
        allowed_tools = _with_earnings_impact_tools(list(allowed_tools), market=market)
        budget["max_tools"] = max(int(budget.get("max_tools", 4)), 9)

    if skill_manifest is not None:
        seen_tools = set(allowed_tools)
        for tool_name in skill_manifest.preferred_tools:
            if tool_name in seen_tools:
                continue
            seen_tools.add(tool_name)
            allowed_tools.append(tool_name)
        skill_budget = skill_manifest.budget
        if isinstance(skill_budget, dict):
            for key in ("max_rounds", "max_tools"):
                if key in skill_budget:
                    budget[key] = max(int(budget.get(key, 0)), int(skill_budget.get(key) or 0))

    if valuation_contract:
        budget["max_rounds"] = max(int(budget.get("max_rounds", 4)), 4)
        budget["max_tools"] = max(int(budget.get("max_tools", 4)), 6)

    if _state_contains_url_reference(state, ui_context) and "fetch_url_content" not in allowed_tools:
        allowed_tools = ["fetch_url_content", *allowed_tools]
        budget["max_tools"] = max(int(budget.get("max_tools", 0)), 1)

    if output_mode != "investment_report" and reply_contract_disallows_news(state):
        allowed_tools = [tool_name for tool_name in allowed_tools if tool_name not in NEWS_TOOL_NAMES]

    if valuation_compare_light and output_mode != "investment_report":
        light_tool_floor = _valuation_compare_light_tool_floor(required_evidence, market=market)
        allowed_tools = [
            tool_name for tool_name in _append_missing(list(allowed_tools), light_tool_floor)
            if tool_name in light_tool_floor
        ]
        budget["max_rounds"] = max(int(budget.get("max_rounds", 4)), 4)
        budget["max_tools"] = max(int(budget.get("max_tools", 4)), min(12, len(light_tool_floor)))

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
            "reason": "request_frame_required_evidence" if request_frame_evidence else "intent_contract_required_evidence",
            "selection_mode": "research_obligation",
            "required_evidence": list(required_evidence),
            "budget_profile": str(intent_contract.get("budget_profile") or "default"),
        }
    elif valuation_compare_light and output_mode != "investment_report":
        allowed_agents = []
        agent_selection = {
            "selected": list(allowed_agents),
            "required": list(allowed_agents),
            "reason": "valuation_compare_light_tool_only",
            "selection_mode": "lightweight_evidence_profile",
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

    # skill 注入（skill 分支）：在 agent 选择链完成后，把所选 skill 的 preferred_agents 补入。
    if skill_manifest is not None:
        skill_added_agents: list[str] = []
        seen_agents = set(allowed_agents)
        for name in skill_manifest.preferred_agents:
            if name not in REPORT_AGENT_CANDIDATES or name in seen_agents:
                continue
            seen_agents.add(name)
            allowed_agents.append(name)
            skill_added_agents.append(name)
        if skill_added_agents:
            agent_selection["skill_added_agents"] = skill_added_agents
            agent_selection["selected"] = list(allowed_agents)
        skill_budget = skill_manifest.budget
        if isinstance(skill_budget, dict) and "max_agents" in skill_budget:
            agent_selection["skill_max_agents"] = int(skill_budget.get("max_agents") or 0)

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

    if opinion_missing_subject:
        allowed_tools = []
        allowed_agents = []
        agent_selection = {
            "selected": [],
            "required": [],
            "reason": "task_missing_subject",
        }

    policy = {
        "budget": budget,
        "market": market,
        "allowed_tools": allowed_tools,
        "tool_schemas": tool_schemas,
        "allowed_agents": allowed_agents,
        "required_results": list(required_results),
        "required_evidence": list(required_evidence),
        "evidence_plan": evidence_plan_for_contract(intent_contract, market=market)
        if intent_contract
        else evidence_plan_for_kinds(required_evidence, market=market),
        "force_all_agents": bool(agent_selection.get("force_all_agents")),
        "analysis_depth": analysis_depth,
        "agent_selection": agent_selection,
        "skill_selection": skill_selection,
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
                "required_results": list(required_results),
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

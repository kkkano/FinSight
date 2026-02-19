# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time
from typing import Any

from langchain_core.messages import HumanMessage

from backend.graph.failure import append_failure, build_runtime, utc_now_iso
from backend.graph.capability_registry import REPORT_AGENT_CANDIDATES, select_agents_for_request
from backend.graph.plan_ir import PlanIR, PlanBudget
from backend.graph.planner_prompt import build_planner_prompt
from backend.graph.event_bus import emit_event
from backend.graph.state import GraphState
from backend.graph.nodes.planner_stub import planner_stub
from backend.services.llm_retry import ainvoke_with_rate_limit_retry, is_rate_limit_error

logger = logging.getLogger(__name__)


def _env_str(key: str, default: str) -> str:
    raw = os.getenv(key)
    return raw.strip() if isinstance(raw, str) and raw.strip() else default


def _env_bool(key: str, default: bool = False) -> bool:
    raw = os.getenv(key)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_int(key: str, default: int) -> int:
    raw = os.getenv(key)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except Exception:
        return default


def _resolve_planner_variant(state: GraphState) -> str:
    if not _env_bool("LANGGRAPH_PLANNER_AB_ENABLED", False):
        return "A"

    split_percent = max(0, min(100, _env_int("LANGGRAPH_PLANNER_AB_SPLIT", 50)))
    salt = _env_str("LANGGRAPH_PLANNER_AB_SALT", "planner-ab-v1")
    thread_id = str(
        state.get("thread_id")
        or state.get("session_id")
        or ((state.get("ui_context") or {}).get("session_id") if isinstance(state.get("ui_context"), dict) else "")
        or "anonymous"
    )
    digest = hashlib.sha256(f"{salt}:{thread_id}".encode("utf-8")).hexdigest()
    bucket = int(digest[:8], 16) % 100
    return "A" if bucket < split_percent else "B"


_PLANNER_AB_LOCK = threading.Lock()
_PLANNER_AB_METRICS: dict[str, dict[str, float | int]] = {
    "A": {"requests": 0, "fallbacks": 0, "retry_attempts": 0, "steps_total": 0},
    "B": {"requests": 0, "fallbacks": 0, "retry_attempts": 0, "steps_total": 0},
}


def _record_planner_ab_metrics(*, variant: str, fallback: bool, retry_attempts: int, steps: int) -> None:
    key = "B" if str(variant).upper() == "B" else "A"
    with _PLANNER_AB_LOCK:
        row = _PLANNER_AB_METRICS[key]
        row["requests"] = int(row["requests"]) + 1
        if fallback:
            row["fallbacks"] = int(row["fallbacks"]) + 1
        row["retry_attempts"] = int(row["retry_attempts"]) + max(0, int(retry_attempts))
        row["steps_total"] = int(row["steps_total"]) + max(0, int(steps))


def get_planner_ab_metrics() -> dict[str, Any]:
    split_percent = max(0, min(100, _env_int("LANGGRAPH_PLANNER_AB_SPLIT", 50)))
    enabled = _env_bool("LANGGRAPH_PLANNER_AB_ENABLED", False)
    with _PLANNER_AB_LOCK:
        by_variant: dict[str, Any] = {}
        totals = {"requests": 0, "fallbacks": 0, "retry_attempts": 0, "steps_total": 0}
        for key in ("A", "B"):
            row = _PLANNER_AB_METRICS[key]
            requests = int(row["requests"])
            fallbacks = int(row["fallbacks"])
            retries = int(row["retry_attempts"])
            steps_total = int(row["steps_total"])
            totals["requests"] += requests
            totals["fallbacks"] += fallbacks
            totals["retry_attempts"] += retries
            totals["steps_total"] += steps_total
            by_variant[key] = {
                "requests": requests,
                "fallbacks": fallbacks,
                "fallback_rate": round((fallbacks / requests), 6) if requests > 0 else 0.0,
                "retry_attempts": retries,
                "avg_steps": round((steps_total / requests), 3) if requests > 0 else 0.0,
            }

    total_requests = totals["requests"]
    return {
        "enabled": enabled,
        "split_percent": split_percent,
        "variants": by_variant,
        "totals": {
            "requests": total_requests,
            "fallbacks": totals["fallbacks"],
            "fallback_rate": round((totals["fallbacks"] / total_requests), 6) if total_requests > 0 else 0.0,
            "retry_attempts": totals["retry_attempts"],
            "avg_steps": round((totals["steps_total"] / total_requests), 3) if total_requests > 0 else 0.0,
        },
    }


def _extract_json_object(text: str) -> str:
    """
    Extract the first JSON object from a model response.
    Handles code fences and surrounding commentary.
    """
    if not text:
        raise ValueError("empty model output")

    cleaned = text.strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("no json object found")
    return cleaned[start : end + 1]


def _extract_error_snippet(text: str, pos: int, *, radius: int = 220) -> str:
    raw = str(text or "")
    idx = max(0, min(len(raw), int(pos or 0)))
    start = max(0, idx - radius)
    end = min(len(raw), idx + radius)
    return raw[start:end].strip()


def _build_parse_error_info(raw_output: str, exc: BaseException) -> dict[str, Any]:
    payload: dict[str, Any] = {"error": str(exc)}
    raw = str(raw_output or "")

    try:
        json_candidate = _extract_json_object(raw)
    except Exception:
        json_candidate = raw

    payload["output_preview"] = json_candidate[:1200]
    if isinstance(exc, json.JSONDecodeError):
        payload["line"] = int(exc.lineno)
        payload["column"] = int(exc.colno)
        payload["pos"] = int(exc.pos)
        payload["snippet"] = _extract_error_snippet(json_candidate, exc.pos)
    else:
        payload["snippet"] = json_candidate[:320]
    return payload


def _repair_json_text(text: str) -> str:
    repaired = str(text or "")
    if not repaired:
        return repaired

    repaired = repaired.replace("\ufeff", "")
    repaired = repaired.translate(
        str.maketrans(
            {
                "“": '"',
                "”": '"',
                "‘": "'",
                "’": "'",
                "，": ",",
                "：": ":",
            }
        )
    )
    repaired = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", repaired)
    repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
    repaired = re.sub(r"([{,]\s*)'([^'\\]+?)'(\s*:)", r'\1"\2"\3', repaired)
    repaired = re.sub(r"([{,]\s*)([A-Za-z_][A-Za-z0-9_\-]*)(\s*:)", r'\1"\2"\3', repaired)

    def _replace_single_quoted_value(match: re.Match[str]) -> str:
        body = match.group(1).replace('\\"', '"').replace("\\'", "'")
        escaped = json.dumps(body, ensure_ascii=False)
        return f": {escaped}{match.group(2)}"

    repaired = re.sub(r":\s*'([^'\\]*(?:\\.[^'\\]*)*)'(\s*[,}])", _replace_single_quoted_value, repaired)
    return repaired


def _load_json_with_repair(json_text: str) -> tuple[Any, dict[str, Any]]:
    raw = str(json_text or "")
    attempts: list[tuple[str, str]] = [("raw", raw)]

    sanitized = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", raw)
    if sanitized != raw:
        attempts.append(("control_char_sanitized", sanitized))

    repaired = _repair_json_text(sanitized)
    if repaired != sanitized:
        attempts.append(("syntax_repaired", repaired))

    last_exc: BaseException | None = None
    for mode, candidate in attempts:
        try:
            return json.loads(candidate, strict=False), {"parse_mode": mode}
        except Exception as exc:  # noqa: PERF203
            last_exc = exc

    if last_exc is not None:
        raise last_exc
    raise ValueError("json_parse_failed")


def _build_json_retry_prompt(
    *,
    base_prompt: str,
    parse_error: dict[str, Any],
    invalid_output: str,
) -> str:
    line = parse_error.get("line")
    col = parse_error.get("column")
    position = f"line={line}, col={col}" if line and col else "unknown"
    snippet = str(parse_error.get("snippet") or "")[:800]
    preview = str(invalid_output or "")[:3200]
    return (
        f"{base_prompt}\n\n"
        "[FORMAT_RECOVERY]\n"
        "Your previous output was not valid JSON.\n"
        f"- Parse error: {parse_error.get('error')}\n"
        f"- Parse position: {position}\n"
        f"- Error snippet: {snippet}\n\n"
        "Return ONLY a valid JSON object. Do not include markdown/code fences/explanations.\n"
        "Rules:\n"
        "1) Use double quotes for every key and string value.\n"
        "2) No trailing commas.\n"
        "3) Output must be parseable by Python json.loads.\n\n"
        "[PREVIOUS_INVALID_OUTPUT]\n"
        f"{preview}\n"
    )


_HIGH_COST_AGENTS: set[str] = {"macro_agent", "deep_search_agent"}


def _is_deep_hint(query: str, state: GraphState | None = None) -> bool:
    if isinstance(state, dict):
        ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
        analysis_depth = str((ui_context or {}).get("analysis_depth") or "").strip().lower()
        if analysis_depth == "deep_research":
            return True
    q = (query or "").lower()
    return any(
        token in q
        for token in (
            "deep",
            "deepsearch",
            "report",
            "filing",
            "document",
            "longform",
        )
    )


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
    selected_agent_order: list[str] = []
    report_agent_cap: int | None = None
    dashboard_forced_report = _is_dashboard_forced_report(policy, state)
    if output_mode == "investment_report" and allowed_agents and not dashboard_forced_report:
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
    agent_selection = policy.get("agent_selection") if isinstance(policy, dict) else {}
    required_agents = set(agent_selection.get("required") or []) if isinstance(agent_selection, dict) else set()

    subject = state.get("subject") or {"subject_type": "unknown"}
    query = (state.get("query") or "").strip()
    operation = state.get("operation") or {}
    op_name = operation.get("name") if isinstance(operation, dict) else None
    op_name = str(op_name) if isinstance(op_name, str) and op_name else "qa"
    has_deep_hint = _is_deep_hint(query, state)

    tickers = subject.get("tickers") if isinstance(subject, dict) else None
    tickers = tickers if isinstance(tickers, list) else []
    tickers = [str(t).strip().upper() for t in tickers if isinstance(t, str) and str(t).strip()]
    primary_ticker = tickers[0] if tickers else None
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

        # Normalize known tool inputs for robustness.
        if kind == "tool" and name == "get_performance_comparison":
            tickers_value = inputs.get("tickers")
            if isinstance(tickers_value, list):
                mapping = {str(t).strip().upper(): str(t).strip().upper() for t in tickers_value if str(t).strip()}
                inputs = {**inputs, "tickers": mapping}
        elif kind == "tool" and name in ("get_stock_price", "get_technical_snapshot", "get_company_info", "get_company_news"):
            ticker_value = inputs.get("ticker")
            if _is_dashboard_source(state) and primary_ticker:
                # Dashboard 场景强制使用 subject 中的 ticker，
                # 防止 LLM 从新闻标题中误提取无关 ticker（如 KLM）。
                inputs = {**inputs, "ticker": primary_ticker}
            elif (not isinstance(ticker_value, str) or not ticker_value.strip()) and primary_ticker:
                # 非 dashboard 场景仅在 ticker 缺失时回填。
                inputs = {**inputs, "ticker": primary_ticker}

        if kind == "agent":
            # Ensure agent steps are runnable and traceable even when the model omits inputs.
            q = inputs.get("query")
            if not isinstance(q, str) or not q.strip():
                inputs = {**inputs, "query": query}

            t = inputs.get("ticker")
            if _is_dashboard_source(state) and primary_ticker:
                # Dashboard 场景同样强制使用 subject ticker。
                inputs = {**inputs, "ticker": primary_ticker}
            elif (not isinstance(t, str) or not t.strip()) and primary_ticker:
                inputs = {**inputs, "ticker": primary_ticker}

            if selection_ids and "selection_ids" not in inputs:
                inputs = {**inputs, "selection_ids": selection_ids}

        return {
            "id": step_id,
            "kind": kind,
            "name": name.strip(),
            "inputs": inputs,
            "parallel_group": parallel_group,
            "why": why,
            "optional": optional,
        }

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

    def _insert_required_tool(name: str, inputs: dict[str, Any], why: str) -> None:
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
            "optional": False,
        }
        # Insert right after selection summary (if present), else at start.
        insert_at = 1 if (sanitized_steps and sanitized_steps[0].get("name") == "summarize_selection") else 0
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
    if isinstance(report_agent_cap, int) and report_agent_cap > 0:
        agent_order = agent_order[:report_agent_cap]
    if output_mode == "investment_report" and has_deep_hint and "deep_search_agent" in allowed_agents:
        if "deep_search_agent" not in agent_order:
            if isinstance(report_agent_cap, int) and report_agent_cap > 0 and len(agent_order) >= report_agent_cap:
                if report_agent_cap == 1:
                    agent_order = ["deep_search_agent"]
                else:
                    agent_order = agent_order[: report_agent_cap - 1] + ["deep_search_agent"]
            else:
                agent_order.append("deep_search_agent")

    # In report mode, enforce a deterministic score-selected agent baseline.
    if output_mode == "investment_report" and primary_ticker:
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
            agent_inputs = {"query": query, "ticker": primary_ticker, "selection_ids": selection_ids}
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
    if max_tools > 0:
        # In report mode, prioritize keeping the baseline agent cards so the UI is stable/readable.
        baseline_agents: set[str] = set()
        if output_mode == "investment_report" and primary_ticker:
            baseline_agents = {a for a in agent_order if a in allowed_agents}

        if baseline_agents:
            pinned_remaining = sum(
                1
                for step in sanitized_steps
                if step.get("kind") == "agent" and step.get("name") in baseline_agents
            )
            kept: list[dict[str, Any]] = []
            tool_count = 0

            for step in sanitized_steps:
                kind = step.get("kind")
                if kind not in ("tool", "agent"):
                    kept.append(step)
                    continue

                is_pinned = kind == "agent" and step.get("name") in baseline_agents
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
        drop_order.sort()
        for _priority, idx in drop_order:
            step = sanitized_steps[idx]
            dropped_for_budget.append(str(step.get("id") or step.get("name") or f"idx:{idx}"))
            sanitized_steps.pop(idx)
            budget_assertions = _build_budget_assertions(sanitized_steps, safe_budget)
            if budget_assertions.get("cost_within_budget") and budget_assertions.get("latency_within_budget"):
                break
    budget_assertions["dropped_steps"] = dropped_for_budget

    return ({
        "goal": goal,
        "subject": subject,
        "output_mode": output_mode,
        "budget": safe_budget,
        "steps": sanitized_steps,
        "synthesis": safe_synthesis,
    }, budget_assertions)


def _dedupe_agent_names(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in items:
        name = str(raw or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        ordered.append(name)
    return ordered


def _extract_selected_agents(plan_dict: dict[str, Any]) -> list[str]:
    steps = plan_dict.get("steps")
    if not isinstance(steps, list):
        return []
    names: list[str] = []
    for step in steps:
        if not isinstance(step, dict):
            continue
        if str(step.get("kind") or "") != "agent":
            continue
        name = str(step.get("name") or "").strip()
        if name:
            names.append(name)
    return _dedupe_agent_names(names)


def _candidate_agents_for_plan(state: GraphState) -> list[str]:
    policy = state.get("policy") if isinstance(state.get("policy"), dict) else {}
    allowed = policy.get("allowed_agents") if isinstance(policy, dict) else None
    if isinstance(allowed, list):
        candidates = [str(item or "").strip() for item in allowed]
        deduped = _dedupe_agent_names(candidates)
        if deduped:
            return deduped
    return list(REPORT_AGENT_CANDIDATES)


def _build_plan_steps_summary(plan_dict: dict[str, Any]) -> list[dict[str, Any]]:
    raw_steps = plan_dict.get("steps")
    if not isinstance(raw_steps, list):
        return []
    summary: list[dict[str, Any]] = []
    for step in raw_steps[:24]:
        if not isinstance(step, dict):
            continue
        summary.append(
            {
                "id": str(step.get("id") or "").strip() or "unknown",
                "kind": str(step.get("kind") or "").strip() or "unknown",
                "name": str(step.get("name") or "").strip() or "unknown",
                "parallel_group": (
                    str(step.get("parallel_group") or "").strip()
                    if step.get("parallel_group") is not None
                    else None
                ),
                "optional": bool(step.get("optional")),
            }
        )
    return summary


def _build_planner_reasoning_brief(
    *,
    state: GraphState,
    selected_agents: list[str],
    skipped_agents: list[str],
    plan_steps_count: int,
    fallback: bool,
    fallback_reason: str | None = None,
) -> str:
    output_mode = str(state.get("output_mode") or "brief").strip() or "brief"
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    source = str((ui_context or {}).get("source") or "").strip() or "unknown"
    selected_preview = ", ".join(selected_agents[:5]) if selected_agents else "none"
    skipped_preview = ", ".join(skipped_agents[:5]) if skipped_agents else "none"
    if fallback:
        reason = str(fallback_reason or "planner_fallback").strip()
        return (
            f"Planner fallback mode ({reason}); output_mode={output_mode}; source={source}; "
            f"selected={selected_preview}; skipped={skipped_preview}; steps={plan_steps_count}."
        )
    return (
        f"Planner completed; output_mode={output_mode}; source={source}; "
        f"selected={selected_preview}; skipped={skipped_preview}; steps={plan_steps_count}."
    )


async def _emit_pipeline_stage(
    *,
    stage: str,
    status: str,
    message: str,
    duration_ms: int | None = None,
    error: str | None = None,
) -> None:
    payload: dict[str, Any] = {
        "type": "pipeline_stage",
        "stage": stage,
        "status": status,
        "message": message,
        "timestamp": utc_now_iso(),
    }
    if isinstance(duration_ms, int) and duration_ms >= 0:
        payload["duration_ms"] = duration_ms
    if error:
        payload["error"] = str(error)[:300]
    await emit_event(payload)


async def _emit_plan_ready(
    *,
    state: GraphState,
    plan_dict: dict[str, Any],
    fallback: bool,
    fallback_reason: str | None = None,
) -> None:
    selected_agents = _extract_selected_agents(plan_dict)
    candidate_agents = _candidate_agents_for_plan(state)
    selected_set = set(selected_agents)
    skipped_agents = [name for name in candidate_agents if name not in selected_set]
    reasoning_brief = _build_planner_reasoning_brief(
        state=state,
        selected_agents=selected_agents,
        skipped_agents=skipped_agents,
        plan_steps_count=len(plan_dict.get("steps") or []),
        fallback=fallback,
        fallback_reason=fallback_reason,
    )
    plan_steps = _build_plan_steps_summary(plan_dict)
    has_parallel = any(step.get("parallel_group") for step in plan_steps)
    await emit_event(
        {
            "type": "plan_ready",
            "plan_steps": plan_steps,
            "plan_steps_count": len(plan_steps),
            "agents": selected_agents,
            "selected_agents": selected_agents,
            "skipped_agents": skipped_agents,
            "has_parallel": has_parallel,
            "reasoning_brief": reasoning_brief,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    await emit_event(
        {
            "type": "decision_note",
            "scope": "planner",
            "title": "Planner selection summary",
            "reason": reasoning_brief,
            "impact": (
                f"selected_agents={len(selected_agents)}; skipped_agents={len(skipped_agents)}; "
                f"parallel={'yes' if has_parallel else 'no'}"
            ),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )


async def planner(state: GraphState) -> dict:
    """
    Planner node.

    Modes:
    - LANGGRAPH_PLANNER_MODE=stub (default): deterministic plan (no network)
    - LANGGRAPH_PLANNER_MODE=llm: ask LLM for PlanIR JSON; validate + enforce policy; fallback to stub
    """
    mode = _env_str("LANGGRAPH_PLANNER_MODE", "stub").lower()
    trace = state.get("trace") or {}
    planner_variant = _resolve_planner_variant(state)
    planner_started_at = time.perf_counter()

    await _emit_pipeline_stage(
        stage="planning",
        status="start",
        message="Planner started",
    )

    if mode != "llm":
        trace.update({"planner_runtime": {**build_runtime(mode="stub", fallback=False), "variant": planner_variant}})
        out = {**planner_stub(state), "trace": trace}
        steps = len(((out.get("plan_ir") or {}).get("steps") or []))
        _record_planner_ab_metrics(variant=planner_variant, fallback=False, retry_attempts=0, steps=steps)
        await _emit_plan_ready(
            state=state,
            plan_dict=(out.get("plan_ir") or {}),
            fallback=False,
        )
        await _emit_pipeline_stage(
            stage="planning",
            status="done",
            message="Planner completed",
            duration_ms=int((time.perf_counter() - planner_started_at) * 1000),
        )
        return out

    try:
        from backend.llm_config import create_llm

        _planner_temp = float(os.getenv("LANGGRAPH_PLANNER_TEMPERATURE", "0.2"))
        llm = create_llm(temperature=_planner_temp)
        llm_factory = lambda: create_llm(temperature=_planner_temp)  # noqa: E731
    except Exception as exc:
        append_failure(
            trace,
            node="planner",
            stage="llm_init",
            error=str(exc),
            fallback="planner_stub",
            retryable=False,
        )
        trace.update(
            {
                "planner_runtime": build_runtime(
                    mode="llm",
                    fallback=True,
                    reason=f"llm_unavailable: {exc}",
                    retry_attempts=0,
                )
                | {"variant": planner_variant}
            }
        )
        out = {**planner_stub(state), "trace": trace}
        steps = len(((out.get("plan_ir") or {}).get("steps") or []))
        _record_planner_ab_metrics(variant=planner_variant, fallback=True, retry_attempts=0, steps=steps)
        await _emit_plan_ready(
            state=state,
            plan_dict=(out.get("plan_ir") or {}),
            fallback=True,
            fallback_reason=f"llm_unavailable:{exc.__class__.__name__}",
        )
        await _emit_pipeline_stage(
            stage="planning",
            status="done",
            message="Planner fallback completed",
            duration_ms=int((time.perf_counter() - planner_started_at) * 1000),
        )
        return out

    prompt = build_planner_prompt(state, variant=planner_variant)
    retry_attempts = 0
    last_output_preview = ""
    parse_error_info: dict[str, Any] | None = None

    def _on_retry(attempt: int, _exc: BaseException) -> None:
        nonlocal retry_attempts
        retry_attempts = max(retry_attempts, int(attempt))

    try:
        await emit_event(
            {
                "type": "thinking",
                "stage": "llm_call_start",
                "message": "planner",
                "timestamp": utc_now_iso(),
            }
        )
        resp = await ainvoke_with_rate_limit_retry(
            llm,
            [HumanMessage(content=prompt)],
            llm_factory=llm_factory,
            acquire_token=True,
            on_retry=_on_retry,
        )
        await emit_event(
            {
                "type": "thinking",
                "stage": "llm_call_done",
                "message": "planner",
                "timestamp": utc_now_iso(),
            }
        )
        content = resp.content if hasattr(resp, "content") else str(resp)
        raw_text = str(content)
        last_output_preview = raw_text[:1200]
        parse_meta: dict[str, Any] = {}
        try:
            json_text = _extract_json_object(raw_text)
            payload, parse_meta = _load_json_with_repair(json_text)
        except Exception as first_parse_exc:
            parse_error_info = _build_parse_error_info(raw_text, first_parse_exc)
            logger.warning(
                "[Planner] invalid JSON from first LLM output: %s (line=%s col=%s)",
                parse_error_info.get("error"),
                parse_error_info.get("line"),
                parse_error_info.get("column"),
            )
            await emit_event(
                {
                    "type": "thinking",
                    "stage": "llm_output_invalid_json",
                    "message": f"planner_json_invalid: {parse_error_info.get('error')}",
                    "timestamp": utc_now_iso(),
                }
            )
            await emit_event(
                {
                    "type": "thinking",
                    "stage": "llm_call_retry_start",
                    "message": "planner_json_repair",
                    "timestamp": utc_now_iso(),
                }
            )
            repair_prompt = _build_json_retry_prompt(
                base_prompt=prompt,
                parse_error=parse_error_info,
                invalid_output=raw_text,
            )
            retry_resp = await ainvoke_with_rate_limit_retry(
                llm,
                [HumanMessage(content=repair_prompt)],
                llm_factory=llm_factory,
                acquire_token=True,
                on_retry=_on_retry,
            )
            await emit_event(
                {
                    "type": "thinking",
                    "stage": "llm_call_retry_done",
                    "message": "planner_json_repair",
                    "timestamp": utc_now_iso(),
                }
            )
            retry_content = retry_resp.content if hasattr(retry_resp, "content") else str(retry_resp)
            retry_text = str(retry_content)
            last_output_preview = retry_text[:1200]
            try:
                retry_json_text = _extract_json_object(retry_text)
                payload, parse_meta = _load_json_with_repair(retry_json_text)
                parse_meta["json_retry_used"] = True
                parse_meta["first_parse_error"] = {
                    "error": parse_error_info.get("error"),
                    "line": parse_error_info.get("line"),
                    "column": parse_error_info.get("column"),
                    "snippet": parse_error_info.get("snippet"),
                }
            except Exception as second_parse_exc:
                second_error_info = _build_parse_error_info(retry_text, second_parse_exc)
                parse_error_info = {
                    "json_retry_used": True,
                    "first_attempt": parse_error_info,
                    "second_attempt": second_error_info,
                }
                logger.warning(
                    "[Planner] invalid JSON after retry: %s (line=%s col=%s)",
                    second_error_info.get("error"),
                    second_error_info.get("line"),
                    second_error_info.get("column"),
                )
                raise
        if not isinstance(payload, dict):
            raise ValueError("PlanIR payload must be a JSON object")
        payload, budget_assertions = _enforce_policy(payload, state)
        plan = PlanIR.model_validate(payload)
        trace.update(
            {
                "planner_runtime": {
                    **build_runtime(mode="llm", fallback=False, retry_attempts=retry_attempts),
                    "variant": planner_variant,
                    "steps": len(plan.steps),
                    "budget_assertions": budget_assertions,
                    "json_parse": parse_meta,
                }
            }
        )
        _record_planner_ab_metrics(
            variant=planner_variant,
            fallback=False,
            retry_attempts=retry_attempts,
            steps=len(plan.steps),
        )
        plan_dict = plan.model_dump()
        await _emit_plan_ready(
            state=state,
            plan_dict=plan_dict,
            fallback=False,
        )
        await _emit_pipeline_stage(
            stage="planning",
            status="done",
            message="Planner completed",
            duration_ms=int((time.perf_counter() - planner_started_at) * 1000),
        )
        return {"plan_ir": plan_dict, "trace": trace}
    except Exception as exc:
        retryable = is_rate_limit_error(exc)
        append_failure(
            trace,
            node="planner",
            stage="llm_call",
            error=str(exc),
            fallback="planner_stub",
            retryable=retryable,
            retry_attempts=retry_attempts,
            metadata={
                "json_parse_error": parse_error_info or {},
                "last_output_preview": last_output_preview,
            },
        )
        await emit_event(
            {
                "type": "thinking",
                "stage": "llm_call_error",
                "message": f"planner: {exc}",
                "timestamp": utc_now_iso(),
            }
        )
        trace.update(
            {
                "planner_runtime": build_runtime(
                    mode="llm",
                    fallback=True,
                    reason=str(exc),
                    retry_attempts=retry_attempts,
                )
                | {
                    "variant": planner_variant,
                    "json_parse_error": parse_error_info or {},
                }
            }
        )
        out = {**planner_stub(state), "trace": trace}
        steps = len(((out.get("plan_ir") or {}).get("steps") or []))
        _record_planner_ab_metrics(
            variant=planner_variant,
            fallback=True,
            retry_attempts=retry_attempts,
            steps=steps,
        )
        await _emit_plan_ready(
            state=state,
            plan_dict=(out.get("plan_ir") or {}),
            fallback=True,
            fallback_reason=str(exc),
        )
        await _emit_pipeline_stage(
            stage="planning",
            status="error",
            message="Planner failed, fallback plan emitted",
            duration_ms=int((time.perf_counter() - planner_started_at) * 1000),
            error=str(exc),
        )
        return out

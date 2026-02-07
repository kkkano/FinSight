# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import os
import re
from typing import Any

from langchain_core.messages import HumanMessage

from backend.graph.failure import append_failure, build_runtime, utc_now_iso
from backend.graph.capability_registry import select_agents_for_request
from backend.graph.plan_ir import PlanIR, PlanBudget
from backend.graph.planner_prompt import build_planner_prompt
from backend.graph.event_bus import emit_event
from backend.graph.state import GraphState
from backend.graph.nodes.planner_stub import planner_stub
from backend.services.llm_retry import ainvoke_with_rate_limit_retry, is_rate_limit_error


def _env_str(key: str, default: str) -> str:
    raw = os.getenv(key)
    return raw.strip() if isinstance(raw, str) and raw.strip() else default


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


def _enforce_policy(plan_payload: dict[str, Any], state: GraphState) -> dict[str, Any]:
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
    if output_mode == "investment_report" and allowed_agents:
        try:
            report_max_agents = int(_env_str("LANGGRAPH_REPORT_MAX_AGENTS", "4"))
        except Exception:
            report_max_agents = 4
        report_max_agents = max(1, min(report_max_agents, len(allowed_agents)))
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

    subject = state.get("subject") or {"subject_type": "unknown"}
    query = (state.get("query") or "").strip()
    operation = state.get("operation") or {}
    op_name = operation.get("name") if isinstance(operation, dict) else None
    op_name = str(op_name) if isinstance(op_name, str) and op_name else "qa"

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
            # Fill missing ticker for common company tools.
            ticker_value = inputs.get("ticker")
            if (not isinstance(ticker_value, str) or not ticker_value.strip()) and primary_ticker:
                inputs = {**inputs, "ticker": primary_ticker}

        if kind == "agent":
            # Ensure agent steps are runnable and traceable even when the model omits inputs.
            q = inputs.get("query")
            if not isinstance(q, str) or not q.strip():
                inputs = {**inputs, "query": query}

            t = inputs.get("ticker")
            if (not isinstance(t, str) or not t.strip()) and primary_ticker:
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
                "why": "Selection 是高权重证据，先读/先总结以避免跑偏",
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
        _insert_required_tool("get_stock_price", {"ticker": primary_ticker}, "价格/行情问题：必须先拿到最新价格")
    if op_name == "technical" and primary_ticker:
        _insert_required_tool("get_stock_price", {"ticker": primary_ticker}, "技术面问题：必须先拿到最新价格")
        _insert_required_tool(
            "get_technical_snapshot",
            {"ticker": primary_ticker},
            "技术面问题：必须计算 MA/RSI/MACD 等指标",
        )
    if op_name == "compare" and len(tickers) >= 2:
        mapping = {str(t).strip().upper(): str(t).strip().upper() for t in tickers[:6] if str(t).strip()}
        _insert_required_tool(
            "get_performance_comparison",
            {"tickers": mapping},
            "对比问题：必须先拿到多标的 YTD/1Y 表现作为基础数据",
        )

    default_agent_order = [
        "price_agent",
        "news_agent",
        "fundamental_agent",
        "technical_agent",
        "macro_agent",
        "deep_search_agent",
    ]
    if selected_agent_order:
        agent_order = [name for name in selected_agent_order if name in allowed_agents]
    else:
        agent_order = [name for name in default_agent_order if name in allowed_agents]

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
            sanitized_steps.insert(
                insert_at,
                {
                    "id": _next_step_id(existing_ids),
                    "kind": "agent",
                    "name": agent_name,
                    "inputs": {"query": query, "ticker": primary_ticker, "selection_ids": selection_ids},
                    "parallel_group": None,
                    "why": f"研报模式：默认运行 {agent_name} 输出可解释的卡片摘要与证据",
                    "optional": True,
                },
            )
            insert_at += 1
            existing_agent_names.add(agent_name)

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

    return {
        "goal": goal,
        "subject": subject,
        "output_mode": output_mode,
        "budget": safe_budget,
        "steps": sanitized_steps,
        "synthesis": safe_synthesis,
    }


async def planner(state: GraphState) -> dict:
    """
    Planner node.

    Modes:
    - LANGGRAPH_PLANNER_MODE=stub (default): deterministic plan (no network)
    - LANGGRAPH_PLANNER_MODE=llm: ask LLM for PlanIR JSON; validate + enforce policy; fallback to stub
    """
    mode = _env_str("LANGGRAPH_PLANNER_MODE", "stub").lower()
    trace = state.get("trace") or {}

    if mode != "llm":
        trace.update({"planner_runtime": build_runtime(mode="stub", fallback=False)})
        return {**planner_stub(state), "trace": trace}

    try:
        from backend.llm_config import create_llm

        llm = create_llm(temperature=float(os.getenv("LANGGRAPH_PLANNER_TEMPERATURE", "0.2")))
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
            }
        )
        return {**planner_stub(state), "trace": trace}

    prompt = build_planner_prompt(state)
    retry_attempts = 0

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
        json_text = _extract_json_object(str(content))
        payload = json.loads(json_text)
        if not isinstance(payload, dict):
            raise ValueError("PlanIR payload must be a JSON object")
        payload = _enforce_policy(payload, state)
        plan = PlanIR.model_validate(payload)
        trace.update(
            {
                "planner_runtime": {
                    **build_runtime(mode="llm", fallback=False, retry_attempts=retry_attempts),
                    "steps": len(plan.steps),
                }
            }
        )
        return {"plan_ir": plan.model_dump(), "trace": trace}
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
            }
        )
        return {**planner_stub(state), "trace": trace}

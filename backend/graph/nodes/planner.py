# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from typing import Any

from langchain_core.messages import HumanMessage

from backend.graph.failure import append_failure, build_runtime, utc_now_iso
from backend.graph.plan_ir import PlanIR
from backend.graph.planner_prompt import build_planner_prompt
from backend.graph.preference_timeouts import timeout_seconds_from_state
from backend.graph.event_bus import emit_event
from backend.graph.state import GraphState
from backend.graph.planning.diagnostics import (
    _build_agent_selection_diagnostics,
    _build_plan_steps_summary,
    _build_planner_reasoning_brief,
    _candidate_agents_for_plan,
    _dedupe_agent_names,
    _extract_selected_agents,
    _skip_reason_for_agent,
)
from backend.graph.planning.llm_output import (
    PlannerSchemaShapeError,
    _assert_planner_payload_shape,
    _build_json_retry_prompt,
    _build_parse_error_info,
    _build_schema_error_info,
    _build_schema_retry_prompt,
    _extract_error_snippet,
    _extract_json_object,
    _load_json_with_repair,
    _parse_planner_json_output,
    _repair_json_text,
)
from backend.graph.planning.policy_enforcement import (
    _HIGH_COST_AGENTS,
    _build_budget_assertions,
    _enforce_policy,
    _estimate_step_cost_latency,
    _is_dashboard_forced_report,
    _is_dashboard_source,
    _is_deep_hint,
    _plan_tasks_from_state,
)
from backend.graph.planning.rule_planner import rule_based_planner
from backend.services.llm_retry import ainvoke_with_rate_limit_retry, is_rate_limit_error

logger = logging.getLogger(__name__)

__all__ = [
    "PlannerSchemaShapeError",
    "_HIGH_COST_AGENTS",
    "_assert_planner_payload_shape",
    "_build_agent_selection_diagnostics",
    "_build_budget_assertions",
    "_build_json_retry_prompt",
    "_build_parse_error_info",
    "_build_plan_steps_summary",
    "_build_planner_reasoning_brief",
    "_build_schema_error_info",
    "_build_schema_retry_prompt",
    "_candidate_agents_for_plan",
    "_dedupe_agent_names",
    "_enforce_policy",
    "_estimate_step_cost_latency",
    "_extract_error_snippet",
    "_extract_json_object",
    "_extract_selected_agents",
    "_is_dashboard_forced_report",
    "_is_dashboard_source",
    "_is_deep_hint",
    "_load_json_with_repair",
    "_parse_planner_json_output",
    "_plan_tasks_from_state",
    "_planner_llm_limits",
    "_repair_json_text",
    "_skip_reason_for_agent",
    "get_planner_ab_metrics",
    "planner",
]


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


def _planner_llm_limits(state: GraphState) -> dict[str, float | int]:
    output_mode = str(state.get("output_mode") or "chat").strip().lower()
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    analysis_depth = str((ui_context or {}).get("analysis_depth") or "").strip().lower()
    is_deep = output_mode == "investment_report" or analysis_depth == "deep_research"

    if is_deep:
        limits: dict[str, float | int] = {
            "request_timeout": _env_int("LANGGRAPH_PLANNER_REPORT_TIMEOUT_SEC", 240),
            "max_tokens": _env_int("LANGGRAPH_PLANNER_REPORT_MAX_TOKENS", 6000),
            "max_attempts": _env_int("LANGGRAPH_PLANNER_REPORT_MAX_ATTEMPTS", 3),
            "acquire_timeout": float(_env_int("LANGGRAPH_PLANNER_REPORT_ACQUIRE_TIMEOUT_SEC", 180)),
            "sleep_seconds": 2.0,
            "jitter_seconds": 1.0,
        }
        preferred_timeout = timeout_seconds_from_state(state)
        if preferred_timeout is not None:
            limits["request_timeout"] = int(preferred_timeout)
            limits["acquire_timeout"] = float(min(float(limits["acquire_timeout"]), preferred_timeout))
        return limits

    limits = {
        "request_timeout": _env_int("LANGGRAPH_PLANNER_CHAT_TIMEOUT_SEC", 150),
        "max_tokens": _env_int("LANGGRAPH_PLANNER_CHAT_MAX_TOKENS", 3000),
        "max_attempts": _env_int("LANGGRAPH_PLANNER_CHAT_MAX_ATTEMPTS", 2),
        "acquire_timeout": float(_env_int("LANGGRAPH_PLANNER_CHAT_ACQUIRE_TIMEOUT_SEC", 120)),
        "sleep_seconds": 1.0,
        "jitter_seconds": 0.5,
    }
    preferred_timeout = timeout_seconds_from_state(state)
    if preferred_timeout is not None:
        limits["request_timeout"] = int(preferred_timeout)
        limits["acquire_timeout"] = float(min(float(limits["acquire_timeout"]), preferred_timeout))
    return limits


def _should_use_task_graph_planner(state: GraphState, ready_tasks: list[dict[str, Any]]) -> bool:
    """WP2-T9: 判据收编至 planning.lane_selector（具名集合单源），此处仅保留兼容壳。"""
    from backend.graph.planning.lane_selector import select_planner_lane

    return select_planner_lane(state, ready_tasks) == "rule"


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
    agent_selection = _build_agent_selection_diagnostics(
        state=state,
        selected_agents=selected_agents,
        skipped_agents=skipped_agents,
    )
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
            "agent_selection": agent_selection,
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
            "details": {"agent_selection": agent_selection},
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
    mode = _env_str("LANGGRAPH_PLANNER_MODE", "llm").lower()
    llm_limits = _planner_llm_limits(state)
    trace = state.get("trace") or {}
    planner_variant = _resolve_planner_variant(state)
    planner_started_at = time.perf_counter()

    await _emit_pipeline_stage(
        stage="planning",
        status="start",
        message="Planner started",
    )

    tasks = state.get("tasks")
    ready_tasks = [task for task in (tasks if isinstance(tasks, list) else []) if isinstance(task, dict)]
    operation_name = str((state.get("operation") or {}).get("name") or "").strip().lower()
    if mode == "llm" and _should_use_task_graph_planner(state, ready_tasks):
        trace.update(
            {
                "planner_runtime": {
                    **build_runtime(mode="task_graph", fallback=False),
                    "variant": planner_variant,
                    "reason": "router_decomposed_short_task_graph",
                }
            }
        )
        out = {**rule_based_planner(state), "trace": trace}
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

    if (
        mode == "llm"
        and operation_name == "compare"
        and len(ready_tasks) >= 2
        and all(str((task.get("operation") or {}).get("name") or "").strip().lower() == "compare" for task in ready_tasks)
    ):
        trace.update(
            {
                "planner_runtime": {
                    **build_runtime(mode="stub", fallback=False),
                    "variant": planner_variant,
                    "reason": "fast_compare_plan",
                }
            }
        )
        out = {**rule_based_planner(state), "trace": trace}
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

    if mode != "llm":
        trace.update({"planner_runtime": {**build_runtime(mode="stub", fallback=False), "variant": planner_variant}})
        out = {**rule_based_planner(state), "trace": trace}
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
        llm = create_llm(
            temperature=_planner_temp,
            max_tokens=int(llm_limits["max_tokens"]),
            request_timeout=int(llm_limits["request_timeout"]),
        )
        llm_factory = lambda: create_llm(  # noqa: E731
            temperature=_planner_temp,
            max_tokens=int(llm_limits["max_tokens"]),
            request_timeout=int(llm_limits["request_timeout"]),
        )
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
        out = {**rule_based_planner(state), "trace": trace}
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
            max_attempts=int(llm_limits["max_attempts"]),
            sleep_seconds=float(llm_limits["sleep_seconds"]),
            jitter_seconds=float(llm_limits["jitter_seconds"]),
            acquire_timeout_seconds=float(llm_limits["acquire_timeout"]),
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
        json_parse_errors: list[dict[str, Any]] = []
        try:
            payload, parse_meta = _parse_planner_json_output(raw_text)
        except Exception as first_parse_exc:
            parse_error_info = _build_parse_error_info(raw_text, first_parse_exc)
            json_parse_errors.append(parse_error_info)
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
            current_error = parse_error_info
            current_invalid_output = raw_text
            max_json_repairs = max(1, min(_env_int("LANGGRAPH_PLANNER_JSON_REPAIR_ATTEMPTS", 2), 3))
            for repair_attempt in range(1, max_json_repairs + 1):
                repair_prompt = _build_json_retry_prompt(
                    base_prompt=prompt,
                    parse_error=current_error,
                    invalid_output=current_invalid_output,
                )
                retry_resp = await ainvoke_with_rate_limit_retry(
                    llm,
                    [HumanMessage(content=repair_prompt)],
                    llm_factory=llm_factory,
                    max_attempts=1,
                    sleep_seconds=float(llm_limits["sleep_seconds"]),
                    jitter_seconds=float(llm_limits["jitter_seconds"]),
                    acquire_timeout_seconds=float(llm_limits["acquire_timeout"]),
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
                    payload, parse_meta = _parse_planner_json_output(retry_text)
                    parse_meta["json_retry_used"] = True
                    parse_meta["json_repair_attempts"] = repair_attempt
                    parse_meta["first_parse_error"] = {
                        "error": json_parse_errors[0].get("error"),
                        "line": json_parse_errors[0].get("line"),
                        "column": json_parse_errors[0].get("column"),
                        "snippet": json_parse_errors[0].get("snippet"),
                    }
                    if len(json_parse_errors) > 1:
                        parse_meta["repair_parse_errors"] = json_parse_errors[1:]
                    break
                except Exception as retry_parse_exc:
                    retry_error_info = _build_parse_error_info(retry_text, retry_parse_exc)
                    json_parse_errors.append(retry_error_info)
                    parse_error_info = {
                        "json_retry_used": True,
                        "first_attempt": json_parse_errors[0],
                        "second_attempt": json_parse_errors[1] if len(json_parse_errors) > 1 else {},
                    }
                    if len(json_parse_errors) > 2:
                        parse_error_info["repair_attempts"] = json_parse_errors[1:]
                        parse_error_info["third_attempt"] = json_parse_errors[2]
                    logger.warning(
                        "[Planner] invalid JSON after retry %s/%s: %s (line=%s col=%s)",
                        repair_attempt,
                        max_json_repairs,
                        retry_error_info.get("error"),
                        retry_error_info.get("line"),
                        retry_error_info.get("column"),
                    )
                    if repair_attempt >= max_json_repairs:
                        raise
                    current_error = retry_error_info
                    current_invalid_output = retry_text
                    await emit_event(
                        {
                            "type": "thinking",
                            "stage": "llm_call_retry_start",
                            "message": "planner_json_repair",
                            "timestamp": utc_now_iso(),
                        }
                    )

        try:
            _assert_planner_payload_shape(payload)
        except PlannerSchemaShapeError as schema_exc:
            schema_error_info = _build_schema_error_info(last_output_preview, schema_exc)
            await emit_event(
                {
                    "type": "thinking",
                    "stage": "llm_call_retry_start",
                    "message": "planner_schema_repair",
                    "timestamp": utc_now_iso(),
                }
            )
            schema_prompt = _build_schema_retry_prompt(
                base_prompt=prompt,
                schema_error=schema_error_info,
                invalid_output=last_output_preview,
            )
            schema_resp = await ainvoke_with_rate_limit_retry(
                llm,
                [HumanMessage(content=schema_prompt)],
                llm_factory=llm_factory,
                max_attempts=1,
                sleep_seconds=float(llm_limits["sleep_seconds"]),
                jitter_seconds=float(llm_limits["jitter_seconds"]),
                acquire_timeout_seconds=float(llm_limits["acquire_timeout"]),
                acquire_token=True,
                on_retry=_on_retry,
            )
            await emit_event(
                {
                    "type": "thinking",
                    "stage": "llm_call_retry_done",
                    "message": "planner_schema_repair",
                    "timestamp": utc_now_iso(),
                }
            )
            schema_content = schema_resp.content if hasattr(schema_resp, "content") else str(schema_resp)
            schema_text = str(schema_content)
            last_output_preview = schema_text[:1200]
            try:
                payload, parse_meta = _parse_planner_json_output(schema_text)
                _assert_planner_payload_shape(payload)
                parse_meta["schema_retry_used"] = True
                parse_meta["schema_error"] = schema_error_info
            except Exception as schema_retry_exc:
                retry_schema_error = _build_parse_error_info(schema_text, schema_retry_exc)
                parse_error_info = {
                    "schema_retry_used": True,
                    "first_attempt": schema_error_info,
                    "second_attempt": retry_schema_error,
                }
                logger.warning("[Planner] invalid PlanIR schema after retry: %s", retry_schema_error.get("error"))
                raise

        payload, budget_assertions = _enforce_policy(payload, state)
        plan = PlanIR.model_validate(payload)
        trace.update(
            {
                "planner_runtime": {
                    **build_runtime(mode="llm", fallback=False, retry_attempts=retry_attempts),
                    "variant": planner_variant,
                    "steps": len(plan.steps),
                    "budget_assertions": budget_assertions,
                    "llm_limits": llm_limits,
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
                    "llm_limits": llm_limits,
                    "json_parse_error": parse_error_info or {},
                }
            }
        )
        out = {**rule_based_planner(state), "trace": trace}
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

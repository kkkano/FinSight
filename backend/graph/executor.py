# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import hashlib
import json
import time
from typing import Any, Awaitable, Callable, Mapping, MutableMapping

from backend.graph.event_bus import emit_event
from backend.graph.failure import FAILURE_STRATEGY_VERSION


AsyncInvoker = Callable[[dict[str, Any]], Awaitable[Any]]


def _stable_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def step_cache_key(kind: str, name: str, inputs: dict[str, Any]) -> str:
    blob = f"{kind}:{name}:{_stable_json(inputs)}".encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


def _as_async_invoker(fn: Callable[[dict[str, Any]], Any]) -> AsyncInvoker:
    async def _wrapped(inputs: dict[str, Any]) -> Any:
        return await asyncio.to_thread(fn, inputs)

    return _wrapped


def group_steps_by_parallel_group(steps: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """
    Convert a step list into serial "groups", where each group runs concurrently.

    Assumption (Phase 3): the planner emits parallel_group IDs in contiguous blocks.
    """
    groups: list[list[dict[str, Any]]] = []
    current_group_id: str | None = None
    current: list[dict[str, Any]] = []

    for step in steps:
        pg = step.get("parallel_group")
        group_id = pg if isinstance(pg, str) and pg.strip() else None

        # No parallel group => its own serial group
        if group_id is None:
            if current:
                groups.append(current)
                current = []
                current_group_id = None
            groups.append([step])
            continue

        # New group starts
        if current_group_id is None:
            current_group_id = group_id
            current = [step]
            continue

        # Same group continues
        if current_group_id == group_id:
            current.append(step)
            continue

        # Group changed
        groups.append(current)
        current_group_id = group_id
        current = [step]

    if current:
        groups.append(current)
    return groups


def summarize_selection(inputs: dict[str, Any]) -> str:
    selection = inputs.get("selection") or []
    if not isinstance(selection, list) or not selection:
        return "（未提供 selection，可跳过）"

    lines = []
    for item in selection[:8]:
        if not isinstance(item, dict):
            continue
        title = item.get("title") or item.get("headline") or "(untitled)"
        snippet = item.get("snippet") or item.get("summary")
        lines.append(f"- {title}")
        if snippet:
            lines.append(f"  - {str(snippet).strip()}")
    return "\n".join(lines) if lines else "（selection 为空）"


async def execute_plan(
    plan_ir: dict[str, Any],
    *,
    tool_invokers: Mapping[str, Callable[[dict[str, Any]], Any]] | None = None,
    agent_invokers: Mapping[str, Callable[[dict[str, Any]], Any]] | None = None,
    dry_run: bool = True,
    cache: MutableMapping[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """
    Execute a PlanIR `steps` list with:
    - parallel_group concurrency
    - step-level cache/dedupe
    - optional-step failure tolerance

    Returns (artifacts, exec_trace_events).
    """
    steps = plan_ir.get("steps") or []
    if not isinstance(steps, list):
        steps = []

    tool_invokers = tool_invokers or {}
    agent_invokers = agent_invokers or {}
    async_tools: dict[str, AsyncInvoker] = {
        name: (_as_async_invoker(fn) if not asyncio.iscoroutinefunction(fn) else fn)  # type: ignore[arg-type]
        for name, fn in tool_invokers.items()
    }
    async_agents: dict[str, AsyncInvoker] = {
        name: (_as_async_invoker(fn) if not asyncio.iscoroutinefunction(fn) else fn)  # type: ignore[arg-type]
        for name, fn in agent_invokers.items()
    }
    cache = cache if cache is not None else {}

    artifacts: dict[str, Any] = {
        "step_results": {},
        "errors": [],
        "signals": {
            "max_confidence": 0.0,
            "latest_confidence": None,
            "max_evidence_quality": 0.0,
            "latest_evidence_quality": None,
        },
    }
    exec_events: list[dict[str, Any]] = []

    def _as_float(value: Any) -> float | None:
        try:
            if value is None:
                return None
            return float(value)
        except Exception:
            return None

    def _update_signals_from_output(output: Any) -> None:
        if not isinstance(output, dict):
            return
        if output.get("skipped") is True:
            return
        signals = artifacts.get("signals")
        if not isinstance(signals, dict):
            return

        confidence = _as_float(output.get("confidence"))
        if confidence is not None:
            signals["latest_confidence"] = confidence
            prev_max = _as_float(signals.get("max_confidence")) or 0.0
            if confidence > prev_max:
                signals["max_confidence"] = confidence

        evidence_quality = output.get("evidence_quality")
        if isinstance(evidence_quality, dict):
            quality_score = _as_float(evidence_quality.get("overall_score"))
            if quality_score is not None:
                signals["latest_evidence_quality"] = quality_score
                prev_quality_max = _as_float(signals.get("max_evidence_quality")) or 0.0
                if quality_score > prev_quality_max:
                    signals["max_evidence_quality"] = quality_score

    async def _run_step(step: dict[str, Any]) -> None:
        step_id = step.get("id") or ""
        kind = step.get("kind") or ""
        name = step.get("name") or ""
        inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
        optional = bool(step.get("optional"))

        start = time.perf_counter()
        exec_events.append({"event": "executor.step_started", "step_id": step_id, "kind": kind, "name": name})
        await emit_event(
            {
                "type": "thinking",
                "stage": "executor_step_start",
                "message": f"{step_id} {kind}:{name}",
                "result": {"inputs": inputs},
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )

        key = step_cache_key(str(kind), str(name), inputs)
        if key in cache:
            artifacts["step_results"][step_id] = {"cached": True, "output": cache[key]}
            exec_events.append(
                {"event": "executor.step_finished", "step_id": step_id, "cached": True, "duration_ms": int((time.perf_counter() - start) * 1000)}
            )
            await emit_event(
                {
                    "type": "thinking",
                    "stage": "executor_step_done",
                    "message": f"{step_id} cached",
                    "result": {"cached": True},
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            )
            _update_signals_from_output(cache[key])
            return

        escalation_stage = inputs.get("__escalation_stage") if isinstance(inputs, dict) else None
        if optional and escalation_stage == "high_cost":
            force_run = bool(inputs.get("__force_run"))
            min_conf = _as_float(inputs.get("__run_if_min_confidence"))
            min_conf = min_conf if min_conf is not None else 0.72
            signals = artifacts.get("signals") if isinstance(artifacts.get("signals"), dict) else {}
            current_conf = _as_float((signals or {}).get("max_confidence")) or 0.0
            if (not force_run) and current_conf >= min_conf:
                output = {
                    "skipped": True,
                    "reason": "escalation_not_needed",
                    "current_confidence": current_conf,
                    "min_confidence": min_conf,
                }
                cache[key] = output
                artifacts["step_results"][step_id] = {"cached": False, "output": output}
                exec_events.append(
                    {
                        "event": "executor.step_finished",
                        "step_id": step_id,
                        "cached": False,
                        "duration_ms": int((time.perf_counter() - start) * 1000),
                        "skipped": True,
                    }
                )
                await emit_event(
                    {
                        "type": "thinking",
                        "stage": "executor_step_done",
                        "message": f"{step_id} skipped escalation",
                        "result": {
                            "cached": False,
                            "skipped": True,
                            "reason": "escalation_not_needed",
                            "duration_ms": int((time.perf_counter() - start) * 1000),
                        },
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    }
                )
                return

        try:
            # Deterministic local "LLM" step should run even in dry_run.
            if kind == "llm" and name == "summarize_selection":
                output = summarize_selection(inputs)
            elif dry_run:
                output = {"skipped": True, "reason": "dry_run", "inputs": inputs}
            else:
                if kind == "tool":
                    await emit_event({"type": "tool_start", "name": str(name), "step_id": step_id, "inputs": inputs})
                    invoker = async_tools.get(str(name))
                    if not invoker:
                        raise ValueError(f"tool not allowed/registered: {name}")
                    output = await _maybe_await(invoker(inputs))
                    await emit_event({"type": "tool_end", "step_id": step_id})
                elif kind == "agent":
                    await emit_event(
                        {
                            "type": "agent_start",
                            "agent": str(name),
                            "name": str(name),
                            "status": "running",
                            "step_id": step_id,
                            "inputs": inputs,
                        }
                    )
                    invoker = async_agents.get(str(name))
                    if not invoker:
                        raise ValueError(f"agent not allowed/registered: {name}")
                    output = await _maybe_await(invoker(inputs))
                    await emit_event(
                        {
                            "type": "agent_done",
                            "agent": str(name),
                            "name": str(name),
                            "status": "done",
                            "step_id": step_id,
                        }
                    )
                else:
                    raise ValueError(f"unsupported step kind/name in Phase 3 executor: {kind}:{name}")

            cache[key] = output
            artifacts["step_results"][step_id] = {"cached": False, "output": output}
            _update_signals_from_output(output)
            exec_events.append(
                {"event": "executor.step_finished", "step_id": step_id, "cached": False, "duration_ms": int((time.perf_counter() - start) * 1000)}
            )
            await emit_event(
                {
                    "type": "thinking",
                    "stage": "executor_step_done",
                    "message": f"{step_id} done",
                    "result": {
                        "cached": False,
                        "skipped": isinstance(output, dict) and output.get("skipped") is True,
                        "duration_ms": int((time.perf_counter() - start) * 1000),
                    },
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            )
        except Exception as exc:
            err = {
                "schema_version": FAILURE_STRATEGY_VERSION,
                "step_id": step_id,
                "kind": kind,
                "name": name,
                "error": str(exc),
                "error_type": exc.__class__.__name__,
                "optional": optional,
                "retryable": False,
                "retry_attempts": 0,
            }
            artifacts["errors"].append(err)
            exec_events.append(
                {"event": "executor.step_failed", "step_id": step_id, "duration_ms": int((time.perf_counter() - start) * 1000), "error": str(exc), "optional": optional}
            )
            await emit_event(
                {
                    "type": "thinking",
                    "stage": "executor_step_error",
                    "message": f"{step_id} failed: {exc}",
                    "result": {"optional": optional},
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            )
            if not optional:
                raise

    groups = group_steps_by_parallel_group(steps)
    for group in groups:
        try:
            await asyncio.gather(*[_run_step(step) for step in group])
        except Exception:
            # Required step failed; stop further execution but return partial artifacts.
            break

    return artifacts, exec_events


__all__ = ["execute_plan", "group_steps_by_parallel_group", "step_cache_key"]

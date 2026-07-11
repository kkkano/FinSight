# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, MutableMapping

from backend.graph.cancellation import get_cancel_event
from backend.graph.event_bus import emit_event
from backend.graph.failure import FAILURE_STRATEGY_VERSION
from backend.graph.json_utils import json_dumps_safe

logger = logging.getLogger(__name__)


AsyncInvoker = Callable[[dict[str, Any]], Awaitable[Any]]


def _stable_json(obj: Any) -> str:
    return json_dumps_safe(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


def _execution_progress_heartbeat_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("LANGGRAPH_EXECUTION_PROGRESS_HEARTBEAT_SECONDS", "2.5")))
    except Exception:
        return 2.5


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


def _identity_inputs(inputs: dict[str, Any]) -> dict[str, Any]:
    return inputs


@dataclass
class StepContext:
    """单步执行所需的共享状态，供 execute_plan 与 execute_plan_dag 共用（WP2 Task5）。"""

    steps: list[dict[str, Any]]
    async_tools: dict[str, AsyncInvoker]
    async_agents: dict[str, AsyncInvoker]
    dry_run: bool
    cache: MutableMapping[str, Any]
    artifacts: dict[str, Any]
    exec_events: list[dict[str, Any]]
    raise_if_cancelled: Callable[[], Awaitable[None]]
    emit_cancelled_stage: Callable[[], Awaitable[None]]
    # cache key 前对 inputs 的投影；旧执行器保持恒等（__escalation_stage 等历史上就参与 key）
    cache_key_inputs: Callable[[dict[str, Any]], dict[str, Any]] = _identity_inputs
    # 证据黑板（WP2 Task7 接线；None=不启用）
    context_bus: dict[str, Any] | None = None


def step_task_ids(step: dict[str, Any]) -> list[str]:
    raw = step.get("task_ids")
    values = raw if isinstance(raw, list) else []
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        task_id = str(value or "").strip()
        if task_id and task_id not in seen:
            seen.add(task_id)
            result.append(task_id)
    single = str(step.get("task_id") or "").strip()
    if single and single not in seen:
        result.insert(0, single)
    return result


def _as_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _update_signals_from_output(artifacts: dict[str, Any], output: Any) -> None:
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


def _resolve_step_ref(ref: str, *, steps: list[dict[str, Any]], artifacts: dict[str, Any]) -> Any:
    ref_name = str(ref or "").strip()
    if not ref_name.startswith("step:"):
        return None
    target = ref_name.removeprefix("step:").strip()
    if not target:
        return None
    step_results = artifacts.get("step_results") if isinstance(artifacts.get("step_results"), dict) else {}
    direct = step_results.get(target)
    if isinstance(direct, dict) and "output" in direct:
        return direct.get("output")
    matches: list[Any] = []
    for candidate in steps:
        if not isinstance(candidate, dict):
            continue
        if str(candidate.get("name") or "") != target:
            continue
        candidate_id = str(candidate.get("id") or "").strip()
        result = step_results.get(candidate_id)
        if isinstance(result, dict) and "output" in result:
            matches.append(result.get("output"))
    if len(matches) == 1:
        return matches[0]
    if matches:
        return matches
    return None


def _inject_python_compute_datasets(
    name: str, inputs: dict[str, Any], *, steps: list[dict[str, Any]], artifacts: dict[str, Any]
) -> dict[str, Any]:
    if str(name or "") != "run_python_compute":
        return inputs
    refs = inputs.get("dataset_refs")
    if not isinstance(refs, list):
        return inputs
    resolved = dict(inputs.get("datasets")) if isinstance(inputs.get("datasets"), dict) else {}
    for ref in refs:
        ref_name = str(ref or "").strip()
        if not ref_name or ref_name in resolved:
            continue
        output = _resolve_step_ref(ref_name, steps=steps, artifacts=artifacts)
        if output is not None:
            resolved[ref_name] = output
    return {**inputs, "datasets": resolved}


async def _await_step_output(
    value: Any,
    *,
    ctx: StepContext,
    kind: str,
    name: str,
    step_id: str,
    task_id: str | None,
    task_ids: list[str],
    parallel_group: str | None,
    started_at: float,
) -> Any:
    heartbeat_seconds = _execution_progress_heartbeat_seconds()
    if heartbeat_seconds <= 0:
        return await _maybe_await(value)

    task = asyncio.create_task(_maybe_await(value))
    heartbeat_count = 0
    try:
        while not task.done():
            done, _ = await asyncio.wait({task}, timeout=heartbeat_seconds)
            if done:
                break
            await ctx.raise_if_cancelled()
            heartbeat_count += 1
            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            progress = min(78, 38 + heartbeat_count * 4)
            payload: dict[str, Any] = {
                "type": "pipeline_stage",
                "stage": "executing",
                "status": "running",
                "message": f"{name or kind} still running",
                "progress": progress,
                "progress_percent": progress,
                "elapsed_ms": elapsed_ms,
                "step_id": step_id,
                "kind": kind,
                "name": name,
                "task_id": task_id,
                "task_ids": task_ids,
                "parallel_group": parallel_group,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            if kind == "agent":
                payload["agent"] = name
            elif kind == "tool":
                payload["tool"] = name
            await emit_event(payload)
        return await task
    except asyncio.CancelledError:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        raise


async def run_single_step(step: dict[str, Any], ctx: StepContext) -> None:
    """执行单个 step：缓存/事件/心跳/错误记录。语义与旧 execute_plan 内联版逐字一致。"""
    step_id = step.get("id") or ""
    kind = step.get("kind") or ""
    name = step.get("name") or ""
    raw_inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
    inputs = _inject_python_compute_datasets(
        str(name), dict(raw_inputs), steps=ctx.steps, artifacts=ctx.artifacts
    )
    optional = bool(step.get("optional"))
    parallel_group = step.get("parallel_group") if isinstance(step.get("parallel_group"), str) else None
    task_ids = step_task_ids(step)
    task_id = task_ids[0] if task_ids else None

    start = time.perf_counter()
    ctx.exec_events.append(
        {"event": "executor.step_started", "step_id": step_id, "kind": kind, "name": name, "task_ids": task_ids}
    )
    await ctx.raise_if_cancelled()
    await emit_event(
        {
            "type": "step_start",
            "step_id": step_id,
            "kind": kind,
            "name": name,
            "task_id": task_id,
            "task_ids": task_ids,
            "inputs_keys": list(inputs.keys()) if isinstance(inputs, dict) else [],
            "parallel_group": parallel_group,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )

    key = step_cache_key(str(kind), str(name), ctx.cache_key_inputs(inputs))
    if key in ctx.cache:
        duration_ms = int((time.perf_counter() - start) * 1000)
        ctx.artifacts["step_results"][step_id] = {
            "cached": True,
            "output": ctx.cache[key],
            "duration_ms": duration_ms,
            "status_reason": "cache_hit",
            "parallel_group": parallel_group,
            "task_id": task_id,
            "task_ids": task_ids,
        }
        ctx.exec_events.append(
            {
                "event": "executor.step_finished",
                "step_id": step_id,
                "cached": True,
                "duration_ms": duration_ms,
                "task_ids": task_ids,
            }
        )
        await emit_event(
            {
                "type": "step_done",
                "step_id": step_id,
                "kind": kind,
                "name": name,
                "cached": True,
                "duration_ms": duration_ms,
                "parallel_group": parallel_group,
                "task_id": task_id,
                "task_ids": task_ids,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        _update_signals_from_output(ctx.artifacts, ctx.cache[key])
        return

    escalation_stage = inputs.get("__escalation_stage") if isinstance(inputs, dict) else None
    if optional and escalation_stage == "high_cost":
        force_run = bool(inputs.get("__force_run"))
        min_conf = _as_float(inputs.get("__run_if_min_confidence"))
        min_conf = min_conf if min_conf is not None else 0.72
        signals = ctx.artifacts.get("signals") if isinstance(ctx.artifacts.get("signals"), dict) else {}
        current_conf = _as_float((signals or {}).get("max_confidence")) or 0.0
        if (not force_run) and current_conf >= min_conf:
            duration_ms = int((time.perf_counter() - start) * 1000)
            output = {
                "skipped": True,
                "reason": "escalation_not_needed",
                "current_confidence": current_conf,
                "min_confidence": min_conf,
            }
            ctx.cache[key] = output
            ctx.artifacts["step_results"][step_id] = {
                "cached": False,
                "output": output,
                "duration_ms": duration_ms,
                "status_reason": "escalation_not_needed",
                "parallel_group": parallel_group,
                "task_id": task_id,
                "task_ids": task_ids,
            }
            ctx.exec_events.append(
                {
                    "event": "executor.step_finished",
                    "step_id": step_id,
                    "cached": False,
                    "duration_ms": duration_ms,
                    "skipped": True,
                    "task_ids": task_ids,
                }
            )
            await emit_event(
                {
                    "type": "step_done",
                    "step_id": step_id,
                    "kind": kind,
                    "name": name,
                    "cached": False,
                    "skipped": True,
                    "reason": "escalation_not_needed",
                    "duration_ms": duration_ms,
                    "parallel_group": parallel_group,
                    "task_id": task_id,
                    "task_ids": task_ids,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                }
            )
            return

    try:
        # Deterministic local "LLM" step should run even in dry_run.
        if kind == "llm" and name == "summarize_selection":
            output = summarize_selection(inputs)
        elif ctx.dry_run:
            output = {"skipped": True, "reason": "dry_run", "inputs": inputs}
        else:
            if kind == "tool":
                await ctx.raise_if_cancelled()
                await emit_event(
                    {
                        "type": "tool_start",
                        "name": str(name),
                        "step_id": step_id,
                        "task_id": task_id,
                        "task_ids": task_ids,
                        "inputs": inputs,
                    }
                )
                invoker = ctx.async_tools.get(str(name))
                if not invoker:
                    raise ValueError(f"tool not allowed/registered: {name}")
                output = await _await_step_output(
                    invoker(inputs),
                    ctx=ctx,
                    kind=str(kind),
                    name=str(name),
                    step_id=str(step_id),
                    task_id=task_id,
                    task_ids=task_ids,
                    parallel_group=parallel_group,
                    started_at=start,
                )
                await ctx.raise_if_cancelled()
                await emit_event({"type": "tool_end", "step_id": step_id, "task_id": task_id, "task_ids": task_ids})
            elif kind == "agent":
                await ctx.raise_if_cancelled()
                await emit_event(
                    {
                        "type": "agent_start",
                        "agent": str(name),
                        "name": str(name),
                        "status": "running",
                        "step_id": step_id,
                        "task_id": task_id,
                        "task_ids": task_ids,
                        "inputs": inputs,
                    }
                )
                invoker = ctx.async_agents.get(str(name))
                if not invoker:
                    raise ValueError(f"agent not allowed/registered: {name}")
                output = await _await_step_output(
                    invoker(inputs),
                    ctx=ctx,
                    kind=str(kind),
                    name=str(name),
                    step_id=str(step_id),
                    task_id=task_id,
                    task_ids=task_ids,
                    parallel_group=parallel_group,
                    started_at=start,
                )
                await ctx.raise_if_cancelled()
                await emit_event(
                    {
                        "type": "agent_done",
                        "agent": str(name),
                        "name": str(name),
                        "status": "done",
                        "step_id": step_id,
                        "task_id": task_id,
                        "task_ids": task_ids,
                    }
                )
            else:
                raise ValueError(f"unsupported step kind/name in Phase 3 executor: {kind}:{name}")

        ctx.cache[key] = output
        duration_ms = int((time.perf_counter() - start) * 1000)
        status_reason = "done"
        if isinstance(output, dict) and output.get("skipped") is True:
            status_reason = str(output.get("reason") or "skipped")
        ctx.artifacts["step_results"][step_id] = {
            "cached": False,
            "output": output,
            "duration_ms": duration_ms,
            "status_reason": status_reason,
            "parallel_group": parallel_group,
            "task_id": task_id,
            "task_ids": task_ids,
        }
        _update_signals_from_output(ctx.artifacts, output)
        ctx.exec_events.append(
            {
                "event": "executor.step_finished",
                "step_id": step_id,
                "cached": False,
                "duration_ms": duration_ms,
                "task_ids": task_ids,
            }
        )
        await emit_event(
            {
                "type": "step_done",
                "step_id": step_id,
                "kind": kind,
                "name": name,
                "cached": False,
                "skipped": isinstance(output, dict) and output.get("skipped") is True,
                "duration_ms": duration_ms,
                "status_reason": status_reason,
                "parallel_group": parallel_group,
                "task_id": task_id,
                "task_ids": task_ids,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
    except asyncio.CancelledError:
        await ctx.emit_cancelled_stage()
        raise
    except Exception as exc:
        err = {
            "schema_version": FAILURE_STRATEGY_VERSION,
            "step_id": step_id,
            "kind": kind,
            "name": name,
            "error": str(exc),
            "error_type": exc.__class__.__name__,
            "optional": optional,
            "task_id": task_id,
            "task_ids": task_ids,
            "retryable": False,
            "retry_attempts": 0,
        }
        ctx.artifacts["errors"].append(err)
        logger.warning(
            "[Executor] step %s (%s:%s) FAILED%s: %s",
            step_id, kind, name,
            " (optional, continuing)" if optional else " (REQUIRED, aborting)",
            exc,
        )
        ctx.exec_events.append(
            {
                "event": "executor.step_failed",
                "step_id": step_id,
                "duration_ms": int((time.perf_counter() - start) * 1000),
                "error": str(exc),
                "optional": optional,
                "task_ids": task_ids,
            }
        )
        await emit_event(
            {
                "type": "step_error",
                "step_id": step_id,
                "kind": kind,
                "name": name,
                "error": str(exc)[:300],
                "error_type": exc.__class__.__name__,
                "optional": optional,
                "parallel_group": parallel_group,
                "task_id": task_id,
                "task_ids": task_ids,
                "duration_ms": int((time.perf_counter() - start) * 1000),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )
        if not optional:
            raise


def aggregate_task_results(steps: list[dict[str, Any]], artifacts: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """按 task_id 聚合 step_results 与 errors（两个执行器共用的收尾逻辑）。"""
    task_results: dict[str, dict[str, Any]] = {}
    step_results = artifacts.get("step_results") if isinstance(artifacts.get("step_results"), dict) else {}
    for step in steps:
        if not isinstance(step, dict):
            continue
        step_id = str(step.get("id") or "").strip()
        if not step_id or step_id not in step_results:
            continue
        for task_id in step_task_ids(step):
            bucket = task_results.setdefault(task_id, {"task_id": task_id, "step_ids": [], "results": {}, "errors": []})
            bucket["step_ids"].append(step_id)
            bucket["results"][step_id] = step_results[step_id]

    for err in artifacts.get("errors") or []:
        if not isinstance(err, dict):
            continue
        for task_id in [str(value or "").strip() for value in (err.get("task_ids") or []) if str(value or "").strip()]:
            bucket = task_results.setdefault(task_id, {"task_id": task_id, "step_ids": [], "results": {}, "errors": []})
            bucket["errors"].append(err)

    return task_results


def build_invoker_maps(
    tool_invokers: Mapping[str, Callable[[dict[str, Any]], Any]] | None,
    agent_invokers: Mapping[str, Callable[[dict[str, Any]], Any]] | None,
) -> tuple[dict[str, AsyncInvoker], dict[str, AsyncInvoker]]:
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
    return async_tools, async_agents


def new_artifacts() -> dict[str, Any]:
    return {
        "step_results": {},
        "task_results": {},
        "errors": [],
        "signals": {
            "max_confidence": 0.0,
            "latest_confidence": None,
            "max_evidence_quality": 0.0,
            "latest_evidence_quality": None,
        },
    }


async def execute_plan(
    plan_ir: dict[str, Any],
    *,
    tool_invokers: Mapping[str, Callable[[dict[str, Any]], Any]] | None = None,
    agent_invokers: Mapping[str, Callable[[dict[str, Any]], Any]] | None = None,
    dry_run: bool = True,
    cache: MutableMapping[str, Any] | None = None,
    cancel_event: asyncio.Event | None = None,
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
    execution_started_at = time.perf_counter()
    cancel_event = cancel_event or get_cancel_event()
    cancelled_stage_emitted = False

    async def _emit_cancelled_stage() -> None:
        nonlocal cancelled_stage_emitted
        if cancelled_stage_emitted:
            return
        cancelled_stage_emitted = True
        await emit_event(
            {
                "type": "pipeline_stage",
                "stage": "cancelled",
                "status": "cancelled",
                "message": "Executor cancelled by client",
                "duration_ms": int((time.perf_counter() - execution_started_at) * 1000),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )

    async def _raise_if_cancelled() -> None:
        if cancel_event is not None and cancel_event.is_set():
            await _emit_cancelled_stage()
            raise asyncio.CancelledError()

    await emit_event(
        {
            "type": "pipeline_stage",
            "stage": "executing",
            "status": "start",
            "message": "Executor started",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )

    async_tools, async_agents = build_invoker_maps(tool_invokers, agent_invokers)
    cache = cache if cache is not None else {}
    artifacts = new_artifacts()
    exec_events: list[dict[str, Any]] = []

    ctx = StepContext(
        steps=steps,
        async_tools=async_tools,
        async_agents=async_agents,
        dry_run=dry_run,
        cache=cache,
        artifacts=artifacts,
        exec_events=exec_events,
        raise_if_cancelled=_raise_if_cancelled,
        emit_cancelled_stage=_emit_cancelled_stage,
    )

    groups = group_steps_by_parallel_group(steps)
    aborted_by_required_error = False
    try:
        await _raise_if_cancelled()
        for group in groups:
            await _raise_if_cancelled()
            await asyncio.gather(*[run_single_step(step, ctx) for step in group])
            await _raise_if_cancelled()
    except asyncio.CancelledError:
        await _emit_cancelled_stage()
        raise
    except Exception as exc:
        # Required step failed; stop further execution but return partial artifacts.
        aborted_by_required_error = True
        await emit_event(
            {
                "type": "pipeline_stage",
                "stage": "executing",
                "status": "error",
                "message": "Executor aborted by required step failure",
                "error": str(exc)[:300],
                "duration_ms": int((time.perf_counter() - execution_started_at) * 1000),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )

    if not aborted_by_required_error:
        await emit_event(
            {
                "type": "pipeline_stage",
                "stage": "executing",
                "status": "done",
                "message": "Executor completed",
                "duration_ms": int((time.perf_counter() - execution_started_at) * 1000),
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
        )

    artifacts["task_results"] = aggregate_task_results(steps, artifacts)
    return artifacts, exec_events


__all__ = [
    "execute_plan",
    "group_steps_by_parallel_group",
    "step_cache_key",
    "run_single_step",
    "StepContext",
    "aggregate_task_results",
    "build_invoker_maps",
    "new_artifacts",
    "step_task_ids",
]

# -*- coding: utf-8 -*-
"""
WP2-Task5: 依赖 DAG 执行器（ORC-04 / D3）。

与旧 execute_plan 的区别：
- 调度按 `depends_on` 就绪即跑，而非 parallel_group 连续块串行排队；
- 必需 step 失败只跳过其传递闭包内的后继（status_reason=upstream_failed），
  不相干分支继续执行；
- 全部 step 的 depends_on 为空时，从 parallel_group 推导隐式依赖
  （第 N 组每个 step 依赖第 N-1 组全部 step），行为与旧执行器等价。

单步语义（缓存/事件/心跳/错误记录）复用 executor.run_single_step，
返回值结构与旧 execute_plan 完全一致。
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections import defaultdict
from typing import Any, Callable, Mapping, MutableMapping

from backend.graph.cancellation import get_cancel_event
from backend.graph.context_bus import digest_agent_output, render_bus
from backend.graph.event_bus import emit_event
from backend.graph.executor import (
    StepContext,
    aggregate_task_results,
    build_invoker_maps,
    group_steps_by_parallel_group,
    new_artifacts,
    run_single_step,
    step_task_ids,
)
from backend.graph.failure import FAILURE_STRATEGY_VERSION
from backend.graph.planning.delegation import DELEGATION_CATALOG, LIMITS

logger = logging.getLogger(__name__)


def _cache_key_inputs_without_private(inputs: dict[str, Any]) -> dict[str, Any]:
    """cache key 排除 __ 前缀键（__context_digest 随前序结果变化，进 key 会永远 miss）。

    注意：__escalation_stage/__force_run 等键在旧执行器中历史上参与 cache key，
    该过滤仅 dag_executor 启用（WP2-T7 spec 明确约束）。
    """
    return {k: v for k, v in inputs.items() if not str(k).startswith("__")}


def _implicit_deps_from_groups(steps: list[dict[str, Any]]) -> dict[str, set[str]]:
    """旧 parallel_group 语义 → 隐式依赖：第 N 组每个 step 依赖第 N-1 组全部 step id。"""
    deps: dict[str, set[str]] = {}
    prev_ids: list[str] = []
    for group in group_steps_by_parallel_group(steps):
        ids = [str(s.get("id") or "") for s in group if isinstance(s, dict)]
        for sid in ids:
            deps[sid] = set(prev_ids)
        prev_ids = ids
    return deps


async def _record_skipped(step: dict[str, Any], ctx: StepContext, *, reason: str) -> None:
    """把上游失败导致的跳过写入 step_results 并发 step_done(skipped=True)，事件字段与旧契约一致。"""
    step_id = str(step.get("id") or "")
    kind = step.get("kind") or ""
    name = step.get("name") or ""
    parallel_group = step.get("parallel_group") if isinstance(step.get("parallel_group"), str) else None
    task_ids = step_task_ids(step)
    task_id = task_ids[0] if task_ids else None
    ctx.artifacts["step_results"][step_id] = {
        "cached": False,
        "output": {"skipped": True, "reason": reason},
        "duration_ms": 0,
        "status_reason": reason,
        "parallel_group": parallel_group,
        "task_id": task_id,
        "task_ids": task_ids,
    }
    ctx.exec_events.append(
        {
            "event": "executor.step_finished",
            "step_id": step_id,
            "cached": False,
            "duration_ms": 0,
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
            "reason": reason,
            "duration_ms": 0,
            "status_reason": reason,
            "parallel_group": parallel_group,
            "task_id": task_id,
            "task_ids": task_ids,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )


async def _schedule(steps: list[dict[str, Any]], ctx: StepContext) -> None:
    by_id: dict[str, dict[str, Any]] = {str(s.get("id") or ""): s for s in steps if isinstance(s, dict)}
    deps: dict[str, set[str]] = {
        sid: set(map(str, s.get("depends_on") or [])) for sid, s in by_id.items()
    }
    if not any(deps.values()):
        deps = _implicit_deps_from_groups(list(by_id.values()))
    # 未知依赖 id 视为已满足，避免 plan 笔误造成死锁（记 debug 留痕）
    known = set(by_id)
    for sid, ups in deps.items():
        unknown = ups - known
        if unknown:
            logger.debug("[DagExecutor] step %s has unknown depends_on ids: %s", sid, sorted(unknown))
            deps[sid] = ups & known

    dependents: dict[str, set[str]] = defaultdict(set)
    for sid, ups in deps.items():
        for up in ups:
            dependents[up].add(sid)

    done: set[str] = set()
    failed: set[str] = set()
    running: dict[asyncio.Task, str] = {}
    dynamic_steps = 0

    def _delegation_enabled() -> bool:
        return str(os.getenv("FINSIGHT_AGENT_DELEGATION", "off")).strip().lower() in {
            "1", "true", "yes", "on",
        }

    def _trace_delegation(payload: dict[str, Any]) -> None:
        rows = ctx.artifacts.setdefault("delegation_trace", [])
        if isinstance(rows, list):
            rows.append(payload)

    def _ready() -> list[str]:
        in_flight = set(running.values())
        return [
            sid
            for sid in by_id
            if sid not in done and sid not in failed and sid not in in_flight and deps[sid] <= done
        ]

    async def _mark_skipped_closure(root: str) -> None:
        stack = [root]
        while stack:
            cur = stack.pop()
            for nxt in dependents.get(cur, ()):  # 传递闭包
                if nxt in failed or nxt in done:
                    continue
                failed.add(nxt)
                await _record_skipped(by_id[nxt], ctx, reason="upstream_failed")
                stack.append(nxt)

    def _scope_ids(step: dict[str, Any]) -> list[str]:
        """黑板作用域；无业务 task 的 step 使用内部全局作用域。"""
        return step_task_ids(step) or ["__global__"]

    def _scoped_bus(scope_id: str) -> dict[str, str]:
        assert ctx.context_bus is not None
        existing = ctx.context_bus.get(scope_id)
        if isinstance(existing, dict):
            return existing
        scoped: dict[str, str] = {}
        ctx.context_bus[scope_id] = scoped
        return scoped

    def _step_for_launch(sid: str) -> dict[str, Any]:
        """agent step 且黑板启用时，注入前序摘要（不改原 plan step）。"""
        step = by_id[sid]
        if ctx.context_bus is None or str(step.get("kind") or "") != "agent":
            return step
        inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
        scoped_findings: dict[str, str] = {}
        for scope_id in _scope_ids(step):
            scoped_findings.update(_scoped_bus(scope_id))
        digest = render_bus(scoped_findings, exclude=str(step.get("name") or ""))
        return {**step, "inputs": {**inputs, "__context_digest": digest}}

    def _write_bus_after_success(sid: str) -> None:
        step = by_id[sid]
        if ctx.context_bus is None:
            return
        result = ctx.artifacts["step_results"].get(sid)
        output = result.get("output") if isinstance(result, dict) else None
        kind = str(step.get("kind") or "")
        inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
        if kind == "agent":
            bus_key = str(step.get("name") or "")
            digest = digest_agent_output(bus_key, output)
        elif kind == "tool" and inputs.get("__delegated") is True:
            bus_key = f"delegated:{step.get('name') or 'tool'}"
            if isinstance(output, dict):
                digest = digest_agent_output(bus_key, output)
                if not digest:
                    digest = f"{bus_key}: {str(output)[:240]}"
            else:
                digest = f"{bus_key}: {str(output or '')[:240]}" if output else ""
        else:
            return
        if digest:
            for scope_id in _scope_ids(step):
                _scoped_bus(scope_id)[bus_key] = digest

    def _insert_delegation_after_success(sid: str) -> None:
        nonlocal dynamic_steps
        if not _delegation_enabled() or dynamic_steps >= LIMITS["max_dynamic_steps_per_run"]:
            return
        step = by_id[sid]
        if str(step.get("kind") or "") != "agent":
            return
        result = ctx.artifacts["step_results"].get(sid)
        output = result.get("output") if isinstance(result, dict) else None
        requests = output.get("requests") if isinstance(output, dict) and isinstance(output.get("requests"), list) else []
        if not requests:
            return
        request = requests[0] if isinstance(requests[0], dict) else {}
        evidence = str(request.get("evidence") or "").strip()
        builder = DELEGATION_CATALOG.get(evidence)
        if builder is None:
            _trace_delegation({"requesting_step_id": sid, "evidence": evidence, "status": "ignored_not_whitelisted"})
            return
        template = builder(step, request)
        safe_evidence = re.sub(r"[^a-z0-9_]+", "_", evidence.lower()).strip("_") or "evidence"
        dynamic_id = f"delegated_{sid}_{safe_evidence}"
        if dynamic_id in by_id:
            return
        task_ids = step_task_ids(step)
        bus_scope_ids = task_ids or ["__global__"]
        delegated_inputs = template.get("inputs") if isinstance(template.get("inputs"), dict) else {}
        dynamic_step = {
            "id": dynamic_id,
            "kind": str(template.get("kind") or "tool"),
            "name": str(template.get("name") or ""),
            "inputs": {**delegated_inputs, "__delegated": True, "__requesting_agent": step.get("name")},
            "depends_on": [sid],
            "task_ids": task_ids,
            "optional": True,
        }
        if task_ids:
            dynamic_step["task_id"] = task_ids[0]
        by_id[dynamic_id] = dynamic_step
        ctx.steps.append(dynamic_step)
        deps[dynamic_id] = {sid}
        dependents[sid].add(dynamic_id)
        for downstream_id, downstream in by_id.items():
            if downstream_id in {sid, dynamic_id} or downstream_id in done or downstream_id in failed:
                continue
            if downstream_id in running.values():
                continue
            if str(downstream.get("kind") or "") not in {"agent", "llm"}:
                continue
            if not set(_scope_ids(downstream)).intersection(bus_scope_ids):
                continue
            deps.setdefault(downstream_id, set()).add(dynamic_id)
            dependents[dynamic_id].add(downstream_id)
        dynamic_steps += 1
        _trace_delegation({
            "requesting_step_id": sid,
            "dynamic_step_id": dynamic_id,
            "evidence": evidence,
            "status": "scheduled",
            "task_ids": task_ids,
        })

    try:
        while len(done) + len(failed) < len(by_id):
            for sid in _ready():
                task = asyncio.create_task(run_single_step(_step_for_launch(sid), ctx))
                running[task] = sid
            if not running:
                # 环：剩余节点计入 errors(reason="dependency_cycle")
                for sid in by_id:
                    if sid in done or sid in failed:
                        continue
                    failed.add(sid)
                    step = by_id[sid]
                    ctx.artifacts["errors"].append(
                        {
                            "schema_version": FAILURE_STRATEGY_VERSION,
                            "step_id": sid,
                            "kind": step.get("kind") or "",
                            "name": step.get("name") or "",
                            "error": "dependency_cycle",
                            "error_type": "DependencyCycleError",
                            "optional": bool(step.get("optional")),
                            "task_id": (step_task_ids(step) or [None])[0],
                            "task_ids": step_task_ids(step),
                            "retryable": False,
                            "retry_attempts": 0,
                        }
                    )
                    await _record_skipped(step, ctx, reason="dependency_cycle")
                break
            finished, _ = await asyncio.wait(set(running), return_when=asyncio.FIRST_COMPLETED)
            plan_order = {sid: index for index, sid in enumerate(by_id)}
            for task in sorted(finished, key=lambda item: plan_order[running[item]]):
                sid = running.pop(task)
                step = by_id[sid]
                if task.cancelled():
                    raise asyncio.CancelledError()
                exc = task.exception()
                if exc is None:
                    done.add(sid)
                    _write_bus_after_success(sid)
                    _insert_delegation_after_success(sid)
                elif isinstance(exc, asyncio.CancelledError):
                    raise exc
                else:
                    # run_single_step 已记录 errors/step_error 事件；此处只做闭包跳过
                    failed.add(sid)
                    await _mark_skipped_closure(sid)
    except asyncio.CancelledError:
        for task in running:
            task.cancel()
        if running:
            await asyncio.gather(*running, return_exceptions=True)
        raise


async def execute_plan_dag(
    plan_ir: dict[str, Any],
    *,
    tool_invokers: Mapping[str, Callable[[dict[str, Any]], Any]] | None = None,
    agent_invokers: Mapping[str, Callable[[dict[str, Any]], Any]] | None = None,
    dry_run: bool = True,
    cache: MutableMapping[str, Any] | None = None,
    cancel_event: asyncio.Event | None = None,
    context_bus: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """就绪即跑 DAG 调度。返回值结构与旧 execute_plan 完全一致（artifacts + exec_events）。"""
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
        cache_key_inputs=_cache_key_inputs_without_private,
        context_bus=context_bus,
    )

    try:
        await _raise_if_cancelled()
        await _schedule(steps, ctx)
    except asyncio.CancelledError:
        await _emit_cancelled_stage()
        raise

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


__all__ = ["execute_plan_dag"]

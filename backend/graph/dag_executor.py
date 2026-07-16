# -*- coding: utf-8 -*-
"""
WP2-Task5: 依赖 DAG 执行器（ORC-04 / D3）。

调度语义：
- 按 `depends_on` 就绪即跑；
- 必需 step 失败只跳过其传递闭包内的后继（status_reason=upstream_failed），
  不相干分支继续执行；
- 全部 step 的 depends_on 为空时，从 parallel_group 推导隐式依赖
  （第 N 组每个 step 依赖第 N-1 组全部 step）。

单步语义（缓存/事件/心跳/错误记录）复用 executor.run_single_step，
返回 artifacts 与 exec_events。
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Callable, Mapping, MutableMapping

from backend.graph.cancellation import get_cancel_event
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

logger = logging.getLogger(__name__)


def _cache_key_inputs_without_private(inputs: dict[str, Any]) -> dict[str, Any]:
    """cache key 排除仅控制执行行为的私有输入。"""
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

    try:
        while len(done) + len(failed) < len(by_id):
            for sid in _ready():
                task = asyncio.create_task(run_single_step(by_id[sid], ctx))
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
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """就绪即跑 DAG 调度，返回 artifacts 与 exec_events。"""
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

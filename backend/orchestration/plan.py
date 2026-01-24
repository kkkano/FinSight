# -*- coding: utf-8 -*-
"""
PlanIR + Executor
用于将报告生成流程显式化（计划模板 + 执行状态机 + trace）。
"""

from __future__ import annotations

from functools import partial
import asyncio
import time
import uuid
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable, Awaitable
from backend.orchestration.budget import BudgetExceededError, BudgetManager


def _now_iso() -> str:
    return datetime.now().isoformat()


@dataclass
class PlanStep:
    step_id: str
    title: str
    step_type: str  # agent/forum
    agent_name: Optional[str] = None
    depends_on: List[str] = field(default_factory=list)
    timeout_seconds: Optional[int] = 30
    max_retries: int = 1
    status: str = "pending"
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    duration_ms: Optional[int] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_id": self.step_id,
            "title": self.title,
            "step_type": self.step_type,
            "agent_name": self.agent_name,
            "depends_on": list(self.depends_on),
            "timeout_seconds": self.timeout_seconds,
            "max_retries": self.max_retries,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": self.duration_ms,
            "error": self.error,
        }


@dataclass
class PlanIR:
    plan_id: str
    query: str
    ticker: str
    steps: List[PlanStep]
    created_at: str = field(default_factory=_now_iso)
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "query": self.query,
            "ticker": self.ticker,
            "created_at": self.created_at,
            "steps": [step.to_dict() for step in self.steps],
            "meta": dict(self.meta) if isinstance(self.meta, dict) else {},
        }


class PlanBuilder:
    AGENT_ORDER = ["price", "news", "technical", "fundamental", "macro", "deep_search"]

    @classmethod
    def _get_timeouts(cls) -> Dict[str, Optional[int]]:
        # Default fallback (if config fails or missing)
        timeouts = {
            "price": None,
            "news": None,
            "technical": None,
            "fundamental": None,
            "macro": None,
            "deep_search": None,
            "forum": None,
        }
        
        try:
            # backend/orchestration/plan.py -> backend/orchestration -> backend -> root
            root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            config_path = os.path.join(root_dir, "user_config.json")
            if os.path.exists(config_path):
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    user_timeouts = data.get("agent_timeouts", {})
                    if user_timeouts:
                        timeouts.update(user_timeouts)
        except Exception:
            pass
            
        return timeouts

    @classmethod
    def build_report_plan(cls, query: str, ticker: str, agent_names: List[str]) -> PlanIR:
        timeouts = cls._get_timeouts()
        steps: List[PlanStep] = []
        for agent_name in cls.AGENT_ORDER:
            if agent_name not in agent_names:
                continue
            depends_on: List[str] = []
            if agent_name in ("technical", "fundamental") and "price" in agent_names:
                depends_on.append("collect_price")
            steps.append(
                PlanStep(
                    step_id=f"collect_{agent_name}",
                    title=f"Collect {agent_name} signals",
                    step_type="agent",
                    agent_name=agent_name,
                    timeout_seconds=timeouts.get(agent_name, None),
                    depends_on=depends_on,
                )
            )

        if steps:
            steps.append(
                PlanStep(
                    step_id="synthesize_forum",
                    title="Synthesize forum consensus",
                    step_type="forum",
                    depends_on=[step.step_id for step in steps],
                    timeout_seconds=timeouts.get("forum", None),
                )
            )

        return PlanIR(
            plan_id=f"plan_{uuid.uuid4().hex[:8]}",
            query=query,
            ticker=ticker,
            steps=steps,
        )


class PlanExecutor:
    def __init__(self, agents: Dict[str, Any], forum: Any, budget: Optional[BudgetManager] = None):
        self.agents = agents
        self.forum = forum
        self.budget = budget

    def _consume_round(self, label: str) -> None:
        if not self.budget:
            return
        self.budget.consume_round(label)

    def _emit_event(
        self,
        on_event: Optional[Callable[[Dict[str, Any]], None]],
        trace: List[Dict[str, Any]],
        step: PlanStep,
        event_type: str,
        details: Optional[Dict[str, Any]] = None
    ) -> None:
        # 1. Add to internal trace
        record = {
            "step_id": step.step_id,
            "agent": step.agent_name,
            "event": event_type,
            "status": step.status,
            "timestamp": _now_iso(),
            "details": details or {}
        }
        trace.append(record)
        
        # 2. Emit to external listener
        if on_event:
            try:
                if asyncio.iscoroutinefunction(on_event):
                    # We can't await here easily if this is a sync method called from async context without awaiting,
                    # but caller should usually pass a sync wrapper or we assume sync for simplicity.
                    # Or we just schedule it? No, keep it simple.
                    pass 
                on_event(record)
            except Exception:
                pass

    def _build_peer_context(self, agent_outputs: Dict[str, Any]) -> str:
        if not agent_outputs:
            return ""
        parts = []
        for name, output in agent_outputs.items():
            summary = getattr(output, "summary", "") if output else ""
            if not summary:
                continue
            parts.append(f"{name}: {summary[:300]}")
        return "\n".join(parts)

    def _emit_agent_event(self, parent_on_event: Callable, step: PlanStep, event_data: Dict[str, Any]):
        """Callback to pass to agents to report their internal events"""
        if not parent_on_event:
            return
        
        # event_data format expected: {"event": "type", "details": {...}, "timestamp": ...}
        # We wrap it to match PlanExecutor trace event format
        record = {
            "step_id": step.step_id,
            "agent": step.agent_name,
            "event": event_data.get("event", "agent_internal"),
            "status": step.status,
            "timestamp": event_data.get("timestamp", _now_iso()),
            "details": event_data.get("details", {})
        }
        try:
            parent_on_event(record)
        except Exception:
            pass

    async def _run_agent_step(
        self,
        step: PlanStep,
        query: str,
        ticker: str,
        trace: List[Dict[str, Any]],
        peer_context: Optional[str] = None,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Any:
        agent = self.agents.get(step.agent_name)
        if agent is None:
            step.status = "failed"
            step.error = f"agent_not_found:{step.agent_name}"
            self._emit_event(on_event, trace, step, "step_error", {"error": step.error})
            raise RuntimeError(step.error)

        step.status = "running"
        step.started_at = _now_iso()
        self._emit_event(on_event, trace, step, "step_start")
        start_time = time.perf_counter()

        attempt = 0
        query_payload = query
        if peer_context:
            query_payload = f"{query}\n\n[Peer signals]\n{peer_context}"

        # Prepare callback bridge
        agent_callback = partial(self._emit_agent_event, on_event, step) if on_event else None

        try:
            while True:
                try:
                    self._consume_round(f"agent:{step.agent_name}")
                    
                    # Call agent with on_event if supported, otherwise fallback
                    try:
                        research_coro = agent.research(query_payload, ticker, on_event=agent_callback)
                    except TypeError:
                        # Fallback for agents that don't support on_event yet
                        research_coro = agent.research(query_payload, ticker)

                    result = await asyncio.wait_for(
                        research_coro,
                        timeout=step.timeout_seconds,
                    )
                    step.status = "completed"
                    return result
                except BudgetExceededError as exc:
                    step.status = "failed"
                    step.error = str(exc)
                    raise
                except asyncio.TimeoutError as exc:
                    step.error = f"timeout:{step.timeout_seconds}s"
                except Exception as exc:  # pragma: no cover - defensive
                    step.error = str(exc)

                attempt += 1
                if attempt > step.max_retries:
                    step.status = "failed"
                    raise RuntimeError(step.error)

                self._emit_event(on_event, trace, step, "step_retry", {"attempt": attempt, "error": step.error})
                await asyncio.sleep(0.6 * attempt)
        finally:
            step.finished_at = _now_iso()
            step.duration_ms = int((time.perf_counter() - start_time) * 1000)
            if step.status == "completed":
                self._emit_event(on_event, trace, step, "step_done")
            else:
                self._emit_event(on_event, trace, step, "step_error", {"error": step.error})

    async def _run_forum_step(
        self,
        step: PlanStep,
        agent_outputs: Dict[str, Any],
        user_profile: Optional[Any],
        trace: List[Dict[str, Any]],
        context_summary: Optional[str] = None,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Any:
        import logging
        logger = logging.getLogger(__name__)
        logger.info("[PlanExecutor._run_forum_step] Entered, agent_outputs count: %d", len(agent_outputs) if agent_outputs else 0)
        
        try:
            self._consume_round("forum")
        except BudgetExceededError as exc:
            step.status = "failed"
            step.error = str(exc)
            self._emit_event(on_event, trace, step, "step_error", {"error": str(exc)})
            raise

        step.status = "running"
        step.started_at = _now_iso()
        self._emit_event(on_event, trace, step, "step_start")
        start_time = time.perf_counter()

        try:
            if not agent_outputs:
                step.status = "skipped"
                step.error = "no_agent_outputs"
                logger.warning("[PlanExecutor._run_forum_step] No agent outputs, skipping forum step")
                return None
            
            logger.info("[PlanExecutor._run_forum_step] Calling forum.synthesize with timeout=%s", step.timeout_seconds)
            result = await asyncio.wait_for(
                self.forum.synthesize(
                    agent_outputs,
                    user_profile=user_profile,
                    context_summary=context_summary,
                ),
                timeout=step.timeout_seconds,
            )
            logger.info("[PlanExecutor._run_forum_step] forum.synthesize completed, result type: %s", type(result).__name__ if result else "None")
            step.status = "completed"
            return result
        except asyncio.TimeoutError as exc:
            step.status = "failed"
            step.error = f"timeout:{step.timeout_seconds}s"
            logger.error("[PlanExecutor._run_forum_step] Timeout after %s seconds", step.timeout_seconds)
            raise RuntimeError(step.error) from exc
        except Exception as exc:  # pragma: no cover - defensive
            import traceback
            step.status = "failed"
            step.error = str(exc)
            logger.error("[PlanExecutor._run_forum_step] Exception: %s: %s", type(exc).__name__, str(exc))
            logger.error("[PlanExecutor._run_forum_step] Traceback:\n%s", traceback.format_exc())
            raise
        finally:
            step.finished_at = _now_iso()
            step.duration_ms = int((time.perf_counter() - start_time) * 1000)
            if step.status == "completed":
                self._emit_event(on_event, trace, step, "step_done")
            else:
                self._emit_event(on_event, trace, step, "step_error", {"error": step.error})


    async def execute(
        self,
        plan: PlanIR,
        query: str,
        ticker: str,
        user_profile: Optional[Any] = None,
        context_summary: Optional[str] = None,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> Dict[str, Any]:
        trace: List[Dict[str, Any]] = []
        agent_outputs: Dict[str, Any] = {}
        errors: List[str] = []

        agent_steps = [step for step in plan.steps if step.step_type == "agent"]
        forum_steps = [step for step in plan.steps if step.step_type == "forum"]

        pending = {step.step_id: step for step in agent_steps}
        running: Dict[str, asyncio.Task] = {}
        completed: set[str] = set()
        failed: set[str] = set()

        while pending or running:
            ready_steps = []
            for step_id, step in list(pending.items()):
                if any(dep in failed for dep in step.depends_on):
                    step.status = "skipped"
                    step.error = "dependency_failed"
                    self._emit_event(on_event, trace, step, "step_skipped", {"reason": "dependency_failed"})
                    if step.agent_name:
                        errors.append(f"{step.agent_name}:dependency_failed")
                    failed.add(step_id)
                    pending.pop(step_id, None)
                    continue
                if all(dep in completed for dep in step.depends_on):
                    ready_steps.append(step)
                    pending.pop(step_id, None)

            peer_context = self._build_peer_context(agent_outputs)
            for step in ready_steps:
                running[step.step_id] = asyncio.create_task(
                    self._run_agent_step(step, query, ticker, trace, peer_context=peer_context, on_event=on_event)
                )

            if not running:
                break

            done, _ = await asyncio.wait(running.values(), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                step_id = None
                for key, running_task in running.items():
                    if running_task is task:
                        step_id = key
                        break
                if step_id is None:
                    continue
                step = next(s for s in agent_steps if s.step_id == step_id)
                try:
                    result = task.result()
                    if step.agent_name:
                        agent_outputs[step.agent_name] = result
                    completed.add(step_id)
                except Exception as exc:
                    if step.agent_name:
                        errors.append(f"{step.agent_name}:{exc}")
                    else:
                        errors.append(str(exc))
                    failed.add(step_id)
                running.pop(step_id, None)

        forum_result = None
        for step in forum_steps:
            try:
                forum_result = await self._run_forum_step(
                    step,
                    agent_outputs,
                    user_profile,
                    trace,
                    context_summary=context_summary,
                    on_event=on_event,
                )
            except Exception as exc:
                import logging
                import traceback
                logger = logging.getLogger(__name__)
                logger.error("[PlanExecutor] Forum step failed!")
                logger.error("[PlanExecutor] Exception type: %s", type(exc).__name__)
                logger.error("[PlanExecutor] Exception message: %s", str(exc))
                logger.error("[PlanExecutor] Full traceback:\n%s", traceback.format_exc())
                errors.append(str(exc))

        return {
            "plan": plan.to_dict(),
            "trace": trace,
            "agent_outputs": agent_outputs,
            "forum_output": forum_result,
            "errors": errors,
        }

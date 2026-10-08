"""研究、预测和监控共享的运行预算；线程中的工具继承同一取消状态。"""
from __future__ import annotations

import asyncio
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import logging
from threading import Event, Lock
from time import monotonic
from typing import Any, Callable, Iterator
from uuid import uuid4

from backend.services.llm_usage import (
    TokenUsageAccumulator, reset_token_accumulator, set_token_accumulator,
)
from backend.utils.env import env_float

logger = logging.getLogger(__name__)


class RunDeadlineExceeded(TimeoutError):
    pass


class RunCancelledError(RuntimeError):
    pass


def run_budget_seconds(entry: str) -> float:
    defaults = {"chat": 180.0, "investment_report": 300.0, "prediction": 180.0, "monitor": 15.0}
    key = "LANGGRAPH_EXECUTION_TIMEOUT_REPORT_SECONDS" if entry == "investment_report" else {
        "chat": "LANGGRAPH_EXECUTION_TIMEOUT_SECONDS", "prediction": "PREDICTION_RUN_TIMEOUT_SECONDS",
        "monitor": "MONITOR_COMMENT_TIMEOUT_SECONDS",
    }.get(entry, "LANGGRAPH_EXECUTION_TIMEOUT_SECONDS")
    return max(1.0, env_float(key, defaults.get(entry, 180.0)))


@dataclass
class RunContext:
    owner: str
    entry: str
    deadline: float
    run_id: str = field(default_factory=lambda: str(uuid4()))
    selected_model: str | None = None
    usage: TokenUsageAccumulator = field(init=False)
    cancelled: Event = field(default_factory=Event)
    status: str = "running"
    attempts: list[dict[str, Any]] = field(default_factory=list)
    quota_checker: Callable[[str], None] | None = None
    started_monotonic: float = field(default_factory=monotonic)
    deadline_timer: asyncio.Timeout | None = field(default=None, repr=False)
    completed_steps: dict[str, tuple[dict[str, Any], dict[str, Any]]] = field(default_factory=dict)
    compiled_state: dict[str, Any] | None = None
    _step_lock: Lock = field(default_factory=Lock, repr=False)
    _archive_lock: Lock = field(default_factory=Lock, repr=False)

    def __post_init__(self) -> None:
        self.owner = str(self.owner or "public").strip() or "public"
        self.usage = TokenUsageAccumulator(user_id=self.owner)

    @classmethod
    def create(cls, *, owner: str, entry: str, run_id: str | None = None,
               budget_seconds: float | None = None) -> "RunContext":
        from backend.services.model_selection import current_model
        chosen = current_model()
        return cls(owner=owner, entry=entry, run_id=run_id or str(uuid4()),
                   deadline=monotonic() + (budget_seconds if budget_seconds is not None else run_budget_seconds(entry)),
                   selected_model=chosen.model if chosen else None)

    @property
    def remaining_seconds(self) -> float:
        if self.status != "running":
            return 0.0
        return max(0.0, self.deadline - monotonic())

    def guard(self) -> None:
        if self.cancelled.is_set() or self.status == "cancelled":
            raise RunCancelledError("run_cancelled")
        if self.status != "running" or self.remaining_seconds <= 0:
            raise RunDeadlineExceeded("run_deadline_exceeded")

    def timeout(self, requested: float) -> float:
        self.guard()
        return min(float(requested), self.remaining_seconds)

    def select_entry(self, entry: str) -> None:
        """语义编译确定报告模式后，使用原始起点调整额度，不重新计时。"""
        if self.entry not in {"chat", "brief", "investment_report"} or entry not in {"chat", "brief", "investment_report"}:
            return
        normalized = "investment_report" if entry == "investment_report" else "chat"
        if normalized == self.entry:
            return
        self.guard()
        self.entry = normalized
        self.deadline = self.started_monotonic + run_budget_seconds(normalized)
        if self.deadline_timer is not None:
            self.deadline_timer.reschedule(asyncio.get_running_loop().time() + self.remaining_seconds)

    def check_quota(self) -> None:
        self.guard()
        from backend.services.llm_usage_store import check_user_quota
        if self.quota_checker is not None:
            self.quota_checker(self.owner)
        else:
            # 尚未归档的本轮消耗也属于账户额度。
            check_user_quota(self.owner, pending_cost_usd=self.usage.summary()["total_cost_usd"])

    def finish(self, status: str) -> None:
        self.status = status
        if status in {"cancelled", "timed_out"}:
            self.cancelled.set()

    def record_step(self, step: dict[str, Any], result: dict[str, Any]) -> None:
        with self._step_lock:
            self.completed_steps[str(step["id"])] = (dict(step), dict(result))

    def completed_step_snapshot(self) -> dict[str, tuple[dict[str, Any], dict[str, Any]]]:
        with self._step_lock:
            return dict(self.completed_steps)

    async def archive_usage(self) -> None:
        if not self.usage.call_count:
            return
        from backend.services.agent_run_archive import get_agent_run_archive
        def persist() -> None:
            # 取消后的晚到用量和终态归档可以并发；锁内取快照，旧写入不能覆盖新增用量。
            with self._archive_lock:
                get_agent_run_archive().archive_usage_summary(run_id=self.run_id, user_id=self.owner,
                                                            summary=self.usage.summary(), status=self.status)
        try:
            await asyncio.to_thread(persist)
        except Exception:
            logger.exception("运行用量归档失败 run_id=%s", self.run_id)


_CURRENT: ContextVar[RunContext | None] = ContextVar("finsight_run_context", default=None)


def current_run_context() -> RunContext | None:
    return _CURRENT.get()


@contextmanager
def run_context_scope(context: RunContext) -> Iterator[RunContext]:
    token = _CURRENT.set(context)
    usage_token = set_token_accumulator(context.usage)
    try:
        yield context
    finally:
        reset_token_accumulator(usage_token)
        _CURRENT.reset(token)


def remaining_timeout(requested: float) -> float:
    context = current_run_context()
    return context.timeout(requested) if context is not None else float(requested)

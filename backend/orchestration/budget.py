# -*- coding: utf-8 -*-
"""
Budget management for tool calls, rounds, and time limits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional
import os
import time


class BudgetExceededError(RuntimeError):
    pass


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except Exception:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except Exception:
        return default


@dataclass
class BudgetManager:
    max_tool_calls: Optional[int] = None
    max_rounds: Optional[int] = None
    max_seconds: Optional[float] = None
    tool_calls: int = 0
    rounds: int = 0
    started_at: float = field(default_factory=time.monotonic)
    events: list[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_env(cls) -> "BudgetManager":
        max_tool_calls = _env_int("BUDGET_MAX_TOOL_CALLS", 50)  # 增加以支持 deep_search 多次搜索
        max_rounds = _env_int("BUDGET_MAX_ROUNDS", 12)
        max_seconds = _env_float("BUDGET_MAX_SECONDS", 600.0)  # 10分钟，支持复杂报告生成
        return cls(
            max_tool_calls=max_tool_calls if max_tool_calls > 0 else None,
            max_rounds=max_rounds if max_rounds > 0 else None,
            max_seconds=max_seconds if max_seconds > 0 else None,
        )

    def _elapsed_seconds(self) -> float:
        return time.monotonic() - self.started_at

    def check_time(self, label: str = "time") -> None:
        if self.max_seconds is None:
            return
        elapsed = self._elapsed_seconds()
        if elapsed > self.max_seconds:
            self.events.append({"type": "time_exceeded", "label": label, "elapsed": elapsed})
            raise BudgetExceededError(f"time_budget_exceeded:{elapsed:.2f}s>{self.max_seconds:.2f}s")

    def consume_tool_call(self, name: str) -> None:
        self.tool_calls += 1
        self.events.append({"type": "tool_call", "name": name, "count": self.tool_calls})
        if self.max_tool_calls is not None and self.tool_calls > self.max_tool_calls:
            raise BudgetExceededError(f"tool_call_budget_exceeded:{self.tool_calls}>{self.max_tool_calls}")
        self.check_time(label=f"tool:{name}")

    def consume_round(self, label: str) -> None:
        self.rounds += 1
        self.events.append({"type": "round", "label": label, "count": self.rounds})
        if self.max_rounds is not None and self.rounds > self.max_rounds:
            raise BudgetExceededError(f"round_budget_exceeded:{self.rounds}>{self.max_rounds}")
        self.check_time(label=f"round:{label}")

    def snapshot(self) -> Dict[str, Any]:
        return {
            "max_tool_calls": self.max_tool_calls,
            "max_rounds": self.max_rounds,
            "max_seconds": self.max_seconds,
            "tool_calls": self.tool_calls,
            "rounds": self.rounds,
            "elapsed_seconds": round(self._elapsed_seconds(), 4),
            "events": list(self.events),
        }


class BudgetedTools:
    def __init__(self, tools_module: Any, budget: BudgetManager):
        self._tools = tools_module
        self._budget = budget

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._tools, name)
        if callable(attr):
            def wrapper(*args, **kwargs):
                self._budget.consume_tool_call(name)
                return attr(*args, **kwargs)
            wrapper.__name__ = getattr(attr, "__name__", name)
            wrapper.__doc__ = getattr(attr, "__doc__", None)
            return wrapper
        return attr


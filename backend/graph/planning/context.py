# -*- coding: utf-8 -*-
"""PlanContext：原 planner_stub 巨型闭包捕获集的显式化（WP3 Task2，零行为变更）。

字段即原函数内 41 个闭包读取的全部自由变量；rule_based_planner 主体对这些名字的
读写全部经由 ctx，保证与原闭包 cell 语义一致（含中途重绑定）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class PlanContext:
    query: str = ""
    query_lower: str = ""
    output_mode: str = "brief"
    subject: dict = field(default_factory=dict)
    tickers: list = field(default_factory=list)
    primary_ticker: str = ""
    market: str = ""
    policy: dict = field(default_factory=dict)
    allowed_tools: Any = None
    allowed_agents: Any = None
    news_disallowed: bool = False
    requires_links: bool = False
    is_deep_financial_report: bool = False
    ready_tasks: list = field(default_factory=list)
    ready_tasks_by_id: dict = field(default_factory=dict)
    ready_task_id_set: set = field(default_factory=set)
    request_frames: list = field(default_factory=list)
    steps: list = field(default_factory=list)
    step_id: int = 0
    step_index: dict = field(default_factory=dict)


class StepFactory:
    """spec 契约接口：对 ctx 的 tool/agent step 追加的轻封装。

    内部搬运代码仍直接调用 steps._append_tool_step/_append_agent_step；
    本类供后续新调用方使用（一个实现两个入口，不复制逻辑）。
    """

    def __init__(self, ctx: PlanContext):
        self._ctx = ctx

    def tool_step(self, name: str, inputs: dict, *, why: str = "", optional: bool = True,
                  parallel_group: str | None = None, task_ids: list[str] | None = None) -> None:
        from backend.graph.planning.steps import _append_tool_step
        _append_tool_step(self._ctx, name, inputs, why=why, optional=optional,
                          parallel_group=parallel_group, task_ids=task_ids)

    def agent_step(self, name: str, inputs: dict, *, why: str = "", optional: bool = True,
                   parallel_group: str | None = None, task_ids: list[str] | None = None) -> None:
        from backend.graph.planning.steps import _append_agent_step
        _append_agent_step(self._ctx, name, inputs, why=why, optional=optional,
                           parallel_group=parallel_group, task_ids=task_ids)

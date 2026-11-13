# -*- coding: utf-8 -*-
"""RenderVarsCtx：原 _stub_render_vars 闭包捕获集的显式化（WP3 Task4）。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RenderVarsCtx:
    subject: dict = field(default_factory=dict)
    subject_type: str = "unknown"
    query: str = ""
    operation: str = "qa"
    output_mode: str = "brief"
    selection_payload: list = field(default_factory=list)
    selection_summary: str = ""
    artifacts: dict = field(default_factory=dict)
    step_results: Any = None
    plan_ir: dict = field(default_factory=dict)
    steps: Any = None
    step_index: dict = field(default_factory=dict)
    base_risks: str = ""
    tickers: list = field(default_factory=list)
    label_by_ticker: dict = field(default_factory=dict)
    news_summary: str = ""
    report_hint: str = ""
    parsed: Any = None
    _COMPARABLE_PAIRS: Any = None

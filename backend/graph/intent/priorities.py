# -*- coding: utf-8 -*-
"""任务优先级与置信度具名常量（WP2 D7 / ORC-09、ORC-10）。

数值与 understand_request 现状逐一对应，禁止调值——本模块只是给魔法数字名字。
"""
from __future__ import annotations

PRIORITY_WORKFLOW_ACTION = 8        # request_frame 中的显式流程动作
PRIORITY_UI_SELECTION = 10          # UI 选中项驱动的任务
PRIORITY_PRIMARY_COMPARE = 20       # 多标的对比主任务
PRIORITY_PER_TICKER_EVIDENCE = 24   # contract 逐标的取证任务
PRIORITY_PRIMARY_TASK = 25          # 单标的主任务
PRIORITY_COMPARE_SUBTASK = 26       # 对比子任务（价格/新闻补充）
PRIORITY_MACRO = 30                 # 宏观任务
PRIORITY_THEME = 35                 # 主题/行业任务
PRIORITY_PORTFOLIO = 40             # 持仓任务
PRIORITY_WEAK_FALLBACK = 80         # 弱兜底任务

CONFIDENCE_WITH_TASKS = 0.78        # understanding.confidence（有任务）
CONFIDENCE_NO_TASKS = 0.42          # understanding.confidence（无任务）

__all__ = [name for name in dir() if name.startswith(("PRIORITY_", "CONFIDENCE_"))]

# -*- coding: utf-8 -*-
"""Chat 渲染注册表包（WP3 Task1 拆分自 nodes/chat_renderer.py）。"""
from backend.graph.renderers.registry import render_chat_markdown, render_task_groups, render_task_sections
from backend.graph.renderers.research_report import render_research_report

__all__ = ["render_chat_markdown", "render_research_report", "render_task_groups", "render_task_sections"]

# -*- coding: utf-8 -*-
"""WP2-Task10: 多问题 query 的回答按任务分节渲染（ORC-11 / D8）。"""
from backend.graph.nodes.chat_renderer import render_task_sections


def test_two_subject_tasks_render_two_sections():
    state = {
        "understanding": {"tasks": [
            {"id": "t1", "subject_label": "AAPL, MSFT", "subject_type": "company",
             "operation": {"name": "compare"}, "priority": 20},
            {"id": "t2", "subject_label": "美联储议息", "subject_type": "macro",
             "operation": {"name": "macro_brief"}, "priority": 30},
        ]},
        "artifacts": {"task_results": {
            "t1": {"task_id": "t1", "step_ids": ["s1"], "results": {"s1": {"output": {"summary": "估值对比…"}}}, "errors": []},
            "t2": {"task_id": "t2", "step_ids": ["s2"], "results": {"s2": {"output": {"summary": "下次 FOMC…"}}}, "errors": []},
        }},
        "query": "对比 AAPL 和 MSFT 的估值，另外美联储下次议息是什么时候",
    }
    md = render_task_sections(state)
    assert md is not None
    first = md.index("AAPL, MSFT")
    second = md.index("美联储议息")
    assert first < second                      # priority 顺序
    assert md.count("\n## ") >= 2 or md.startswith("## ")


def test_single_task_returns_none():
    state = {"understanding": {"tasks": [{"id": "t1", "subject_label": "AAPL", "operation": {"name": "price"}, "priority": 25}]},
             "artifacts": {"task_results": {}}}
    assert render_task_sections(state) is None

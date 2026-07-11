# -*- coding: utf-8 -*-
"""WP2-Task10: 多问题 query 的回答按任务分节渲染（ORC-11 / D8）。"""
from backend.graph.execution.evidence_pipeline import normalize_execution_evidence
from backend.graph.renderers import render_task_sections


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


def test_task_sections_use_only_evidence_assigned_to_each_task():
    tasks = [
        {
            "id": "t1",
            "subject_label": "Apple",
            "subject_type": "company",
            "tickers": ["AAPL"],
            "operation": {"name": "qa"},
            "priority": 10,
        },
        {
            "id": "t2",
            "subject_label": "Microsoft",
            "subject_type": "company",
            "tickers": ["MSFT"],
            "operation": {"name": "qa"},
            "priority": 20,
        },
    ]
    step_results = {
        "s1": {"output": {"ok": "aapl"}},
        "s2": {"output": {"ok": "msft"}},
    }
    state = {
        "query": "分别看 Apple 和 Microsoft",
        "understanding": {"tasks": tasks},
        "plan_ir": {
            "steps": [
                {"id": "s1", "kind": "tool", "name": "fixture", "task_ids": ["t1"]},
                {"id": "s2", "kind": "tool", "name": "fixture", "task_ids": ["t2"]},
            ]
        },
        "artifacts": {
            "step_results": step_results,
            "task_results": {
                "t1": {"task_id": "t1", "step_ids": ["s1"], "results": {"s1": step_results["s1"]}, "errors": []},
                "t2": {"task_id": "t2", "step_ids": ["s2"], "results": {"s2": step_results["s2"]}, "errors": []},
            },
            "evidence_pool": [
                {"title": "AAPL MSFT B_TASK_ONLY", "url": "https://example.com/global-b", "source": "fixture"}
            ],
            "evidence_by_task": {
                "t1": [{"title": "AAPL A_TASK_ONLY", "url": "https://example.com/a", "source": "fixture"}],
                "t2": [{"title": "MSFT B_TASK_ONLY", "url": "https://example.com/b", "source": "fixture"}],
            },
        },
    }

    markdown = render_task_sections(state)

    assert markdown is not None
    apple_section = markdown.split("## Microsoft", 1)[0]
    assert "A_TASK_ONLY" in apple_section
    assert "B_TASK_ONLY" not in apple_section


def _empty_evidence_multitask_state() -> dict:
    tasks = [
        {
            "id": "t1",
            "subject_label": "Apple",
            "subject_type": "company",
            "tickers": ["AAPL"],
            "operation": {"name": "qa"},
            "priority": 10,
        },
        {
            "id": "t2",
            "subject_label": "Microsoft",
            "subject_type": "company",
            "tickers": ["MSFT"],
            "operation": {"name": "qa"},
            "priority": 20,
        },
    ]
    step_results = {
        "s1": {"output": {"ok": "aapl"}},
        "s2": {"output": {"ok": "msft"}},
    }
    return {
        "query": "分别看 Apple 和 Microsoft",
        "understanding": {"tasks": tasks},
        "plan_ir": {
            "steps": [
                {"id": "s1", "kind": "tool", "name": "fixture", "task_ids": ["t1"]},
                {"id": "s2", "kind": "tool", "name": "fixture", "task_ids": ["t2"]},
            ]
        },
        "artifacts": {
            "step_results": step_results,
            "task_results": {
                "t1": {"task_id": "t1", "step_ids": ["s1"], "results": {"s1": step_results["s1"]}},
                "t2": {"task_id": "t2", "step_ids": ["s2"], "results": {"s2": step_results["s2"]}},
            },
            "evidence_pool": [],
            "evidence_by_task": {"t1": [], "t2": []},
        },
    }


def test_task_sections_do_not_reuse_global_default_draft():
    state = _empty_evidence_multitask_state()
    state["artifacts"].update(
        {
            "draft_markdown": "MSFT_ONLY_GLOBAL",
            "evidence_ledger": {"claims": [{"claim": "MSFT_ONLY_GLOBAL"}]},
            "rag_context": [{"content": "MSFT_ONLY_GLOBAL"}],
        }
    )

    markdown = render_task_sections(state)

    assert markdown is not None
    apple_section = markdown.split("## Microsoft", 1)[0]
    assert "MSFT_ONLY_GLOBAL" not in apple_section


def test_task_sections_do_not_reuse_global_synthesis_render_vars():
    state = _empty_evidence_multitask_state()
    state["artifacts"]["render_vars"] = {"conclusion": "MSFT_ONLY_GLOBAL"}

    markdown = render_task_sections(state)

    assert markdown is not None
    apple_section = markdown.split("## Microsoft", 1)[0]
    assert "MSFT_ONLY_GLOBAL" not in apple_section


def test_selection_evidence_is_assigned_by_task_identity_before_section_rendering():
    state = _empty_evidence_multitask_state()
    apple_url = "https://example.com/apple-selection"
    microsoft_url = "https://example.com/microsoft-selection"
    tasks = state["understanding"]["tasks"]
    tasks[0].update(
        {
            "subject_type": "news_item",
            "selection_ids": ["selection-apple"],
            "selection_types": ["news"],
        }
    )
    tasks[1].update(
        {
            "subject_type": "news_item",
            "selection_ids": [],
            "selection_types": ["news"],
            "operation": {"name": "qa", "params": {"url": microsoft_url}},
        }
    )
    state["tasks"] = tasks
    state["subject"] = {
        "subject_type": "news_set",
        "tickers": [],
        "selection_ids": ["selection-apple", "selection-microsoft"],
        "selection_types": ["news", "news"],
        "selection_payload": [
            {
                "id": "selection-apple",
                "type": "news",
                "title": "APPLE_SELECTION_ONLY",
                "url": apple_url,
                "source": "fixture",
            },
            {
                "id": "selection-microsoft",
                "type": "news",
                "title": "MICROSOFT_SELECTION_ONLY",
                "url": microsoft_url,
                "source": "fixture",
            },
        ],
    }

    normalize_execution_evidence(
        state=state,
        plan_ir=state["plan_ir"],
        artifacts=state["artifacts"],
    )
    markdown = render_task_sections(state)

    assert [
        item["id"]
        for item in state["artifacts"]["evidence_by_task"]["t1"]
        if str(item.get("id") or "").startswith("selection-")
    ] == [
        "selection-apple"
    ]
    assert [
        item["id"]
        for item in state["artifacts"]["evidence_by_task"]["t2"]
        if str(item.get("id") or "").startswith("selection-")
    ] == [
        "selection-microsoft"
    ]
    assert markdown is not None
    apple_section, microsoft_section = markdown.split("## Microsoft", 1)
    assert "APPLE_SELECTION_ONLY" in apple_section
    assert "MICROSOFT_SELECTION_ONLY" not in apple_section
    assert "MICROSOFT_SELECTION_ONLY" in microsoft_section
    assert "APPLE_SELECTION_ONLY" not in microsoft_section

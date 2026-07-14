# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio

from backend.graph.nodes.render_node import render_node
from backend.graph.nodes.synthesize import synthesize
from backend.graph.renderers.registry import render_task_groups


def _task(task_id: str, order: int, operation: str, title: str) -> dict:
    return {
        "id": task_id,
        "title": title,
        "subject_label": title,
        "subject_type": "company",
        "tickers": ["AAPL"],
        "operation": {"name": operation},
        "priority": 20 + order,
        "order_index": order,
        "request_frame_id": f"frame-{task_id}",
        "render_kind": "single",
        "render_group_id": f"frame-{task_id}",
    }


def test_chat_pipeline_builds_all_four_outcome_states_and_render_coverage(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "stub")
    ready = [
        _task("price", 0, "price", "价格"),
        _task("technical", 1, "technical", "技术面"),
        _task("partial", 2, "price", "补充行情"),
    ]
    blocked = [{
        **_task("blocked", 3, "investment_opinion", "需要补充分析标的"),
        "tickers": [],
        "subject_label": "未指定分析对象",
        "error_code": "task_missing_subject",
    }]
    state = {
        "query": "给我价格、技术面和观点",
        "output_mode": "chat",
        "operation": {"name": "qa"},
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "tasks": ready,
        "blocked_tasks": blocked,
        "understanding": {"tasks": ready, "blocked_tasks": blocked},
        "plan_ir": {
            "tasks": [{"id": item["id"], "required_evidence": ["price_snapshot"]} for item in ready],
            "steps": [
                {"id": "s-price", "name": "get_stock_price", "kind": "tool", "task_ids": ["price"], "inputs": {"required_evidence": ["price_snapshot"]}},
                {"id": "s-tech", "name": "technical_agent", "kind": "agent", "task_ids": ["technical"], "inputs": {"required_evidence": ["price_snapshot"]}},
                {"id": "s-partial-a", "name": "get_stock_price", "kind": "tool", "task_ids": ["partial"], "inputs": {"required_evidence": ["price_snapshot"]}},
                {"id": "s-partial-b", "name": "get_history", "kind": "tool", "task_ids": ["partial"]},
            ],
        },
        "artifacts": {
            "step_results": {
                "s-price": {"output": {"ticker": "AAPL", "price": 200.0, "currency": "USD"}},
                "s-partial-a": {"output": {"ticker": "AAPL", "price": 200.0}},
            },
            "evidence_by_task": {
                "price": [{"source_id": "e-price", "task_ids": ["price"], "kind": "price_snapshot", "text": "AAPL 200", "title": "行情", "url": "https://example.com/price"}],
                "partial": [{"source_id": "e-partial", "task_ids": ["partial"], "kind": "price_snapshot", "text": "AAPL 200"}],
            },
            "evidence_pool": [{"title": "行情", "url": "https://example.com/price", "source": "fixture"}],
        },
        "trace": {},
    }

    synthesized = asyncio.run(synthesize(state))
    outcomes = synthesized["artifacts"]["task_outcomes"]
    assert [item["status"] for item in outcomes] == ["answered", "unavailable", "partial", "blocked"]
    assert synthesized["trace"]["task_coverage"]["complete"] is True

    rendered = render_node({
        **state,
        "artifacts": synthesized["artifacts"],
        "trace": synthesized["trace"],
    })
    markdown = rendered["artifacts"]["draft_markdown"]
    assert rendered["trace"]["rendered_task_ids"] == ["price", "technical", "partial", "blocked"]
    for suffix in ("已回答", "暂不可用", "部分完成", "需要补充"):
        assert suffix in markdown
    assert markdown.count("来源：") == 1


def _outcome(task_id: str, order: int, *, group: str, kind: str, operation: str, title: str) -> dict:
    return {
        "task_id": task_id,
        "title": title,
        "priority": 20 + order,
        "order_index": order,
        "operation": operation,
        "subject_label": title,
        "tickers": [title] if operation == "compare" else [],
        "request_frame_id": group,
        "render_kind": kind,
        "render_group_id": group,
        "intent_status": "ready",
        "required_step_ids": [f"s-{task_id}"],
        "required_evidence": [],
        "error_codes": [],
        "status": "answered",
        "successful_step_ids": [f"s-{task_id}"],
        "evidence_ids": [f"e-{task_id}"],
        "missing_evidence": [],
    }


def test_group_renderer_keeps_compare_and_macro_slices_separate(monkeypatch):
    import backend.graph.renderers.registry as registry

    seen_task_ids: list[list[str]] = []

    def capture_renderer(group_state, _ctx):
        ids = [str(item.get("id")) for item in group_state.get("tasks", [])]
        seen_task_ids.append(ids)
        outputs = (group_state.get("artifacts") or {}).get("step_results") or {}
        marker = "MACRO_ONLY" if "s-macro" in outputs else "COMPARE_ONLY"
        return f"{marker}:{','.join(ids)}"

    monkeypatch.setattr(registry, "RENDERERS", [("capture", capture_renderer)])
    outcomes = [
        _outcome("nvda", 0, group="compare", kind="compare", operation="compare", title="NVDA"),
        _outcome("amd", 1, group="compare", kind="compare", operation="compare", title="AMD"),
        _outcome("macro", 2, group="macro", kind="single", operation="macro_brief", title="利率影响机制"),
    ]
    tasks = [
        {"id": row["task_id"], "title": row["title"], "subject_label": row["title"], "tickers": row["tickers"], "operation": {"name": row["operation"]}}
        for row in outcomes
    ]
    state = {
        "query": "比较 NVDA 和 AMD，并说明利率影响",
        "output_mode": "chat",
        "tasks": tasks,
        "understanding": {"tasks": tasks, "blocked_tasks": []},
        "plan_ir": {"steps": [
            {"id": "s-nvda", "name": "get_performance_comparison", "task_ids": ["nvda", "amd"]},
            {"id": "s-amd", "name": "get_company_info", "task_ids": ["amd"]},
            {"id": "s-macro", "name": "macro_agent", "task_ids": ["macro"]},
        ]},
        "artifacts": {
            "task_outcomes": outcomes,
            "task_structural_block_reasons": [],
            "step_results": {
                "s-nvda": {"output": "Performance Comparison:\nNVDA +10%\nAMD +5%"},
                "s-amd": {"output": {"name": "AMD"}},
                "s-macro": {"output": {"summary": "MACRO_ONLY"}},
            },
            "evidence_by_task": {"nvda": [], "amd": [], "macro": []},
        },
    }
    rendered = render_task_groups(state)
    assert rendered is not None
    markdown, rendered_ids, ok = rendered
    assert ok is True
    assert rendered_ids == ["nvda", "amd", "macro"]
    assert seen_task_ids == [["nvda", "amd"], ["macro"]]
    compare_section, macro_section = markdown.split("## 利率影响机制", 1)
    assert "MACRO_ONLY" not in compare_section
    assert "COMPARE_ONLY" in compare_section
    assert "MACRO_ONLY" in macro_section


def test_duplicate_render_identity_fails_closed():
    duplicate = _outcome("same", 0, group="g1", kind="single", operation="price", title="价格")
    state = {
        "artifacts": {
            "task_outcomes": [duplicate, {**duplicate, "order_index": 1, "render_group_id": "g2"}],
            "task_structural_block_reasons": [],
        }
    }
    rendered = render_task_groups(state)
    assert rendered is not None
    markdown, rendered_ids, ok = rendered
    assert ok is False
    assert rendered_ids == ["same", "same"]
    assert "内部任务渲染检查未通过" in markdown

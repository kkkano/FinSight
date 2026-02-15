# -*- coding: utf-8 -*-
import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_clarify_node_interrupts_when_subject_unknown():
    from backend.graph import GraphRunner

    runner = GraphRunner.create()
    result = _run(runner.ainvoke(thread_id="t-clarify-unknown", query="分析影响", ui_context={}))

    trace = result.get("trace") or {}
    spans = trace.get("spans") or []
    nodes = [s.get("node") for s in spans]

    assert nodes == [
        "build_initial_state",
        "trim_history",
        "summarize_history",
        "normalize_ui_context",
        "decide_output_mode",
        "chat_respond",
        "resolve_subject",
        "clarify",
    ]
    assert (result.get("clarify") or {}).get("needed") is True

    markdown = ((result.get("artifacts") or {}).get("draft_markdown")) or ""
    assert isinstance(markdown, str) and markdown.strip()


def test_clarify_node_allows_continue_when_subject_known():
    from backend.graph import GraphRunner

    runner = GraphRunner.create()
    # "股价分析" contains unambiguous Tier-2 keyword "股价",
    # so active_symbol binding is safe and subject resolves to company.
    result = _run(runner.ainvoke(thread_id="t-clarify-company", query="股价分析", ui_context={"active_symbol": "AAPL"}))

    assert (result.get("clarify") or {}).get("needed") is False

    trace = result.get("trace") or {}
    spans = trace.get("spans") or []
    nodes = [s.get("node") for s in spans]
    assert "policy_gate" in nodes


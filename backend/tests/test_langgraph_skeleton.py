# -*- coding: utf-8 -*-
import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_langgraph_runner_import_and_invoke():
    from backend.graph import GraphRunner

    runner = GraphRunner.create()
    result = _run(runner.ainvoke(thread_id="t-basic", query="分析 AAPL", ui_context={"active_symbol": "AAPL"}))

    assert isinstance(result, dict)
    assert "artifacts" in result
    assert "draft_markdown" in result["artifacts"]
    assert "policy" in result

    trace = result.get("trace") or {}
    spans = trace.get("spans") or []
    assert [s.get("node") for s in spans] == [
        "build_initial_state",
        "trim_history",
        "summarize_history",
        "normalize_ui_context",
        "decide_output_mode",
        "chat_respond",
        "resolve_subject",
        "clarify",
        "parse_operation",
        "policy_gate",
        "planner",
        "execute_plan",
        "synthesize",
        "render",
    ]


def test_resolve_subject_selection_priority_and_dedupe():
    from backend.graph import GraphRunner

    runner = GraphRunner.create()
    ui_context = {
        "active_symbol": "AAPL",
        "selections": [
            {"type": "news", "id": "n1", "title": "t1"},
            {"type": "news", "id": "n1", "title": "t1-dup"},
        ],
    }
    result = _run(runner.ainvoke(thread_id="t-sel", query="分析影响", ui_context=ui_context))

    subject = result.get("subject") or {}
    assert subject.get("subject_type") == "news_item"
    assert subject.get("selection_ids") == ["n1"]


def test_resolve_subject_filing_and_doc_selection_types():
    from backend.graph import GraphRunner

    runner = GraphRunner.create()

    filing = _run(
        runner.ainvoke(
            thread_id="t-filing",
            query="总结要点",
            ui_context={"selections": [{"type": "filing", "id": "f1", "title": "10-K"}]},
        )
    )
    assert (filing.get("subject") or {}).get("subject_type") == "filing"

    doc = _run(
        runner.ainvoke(
            thread_id="t-doc",
            query="总结要点",
            ui_context={"selections": [{"type": "doc", "id": "d1", "title": "research"}]},
        )
    )
    assert (doc.get("subject") or {}).get("subject_type") == "research_doc"

    # Legacy: report -> doc
    legacy = _run(
        runner.ainvoke(
            thread_id="t-legacy-report",
            query="总结要点",
            ui_context={"selections": [{"type": "report", "id": "r1", "title": "legacy"}]},
        )
    )
    subject = legacy.get("subject") or {}
    assert subject.get("subject_type") == "research_doc"
    assert subject.get("selection_types") == ["doc"]


def test_resolve_subject_active_symbol_fallback():
    from backend.graph import GraphRunner

    runner = GraphRunner.create()
    result = _run(runner.ainvoke(thread_id="t-symbol", query="分析苹果", ui_context={"active_symbol": "aapl"}))

    subject = result.get("subject") or {}
    assert subject.get("subject_type") == "company"
    assert subject.get("tickers") == ["AAPL"]


def test_resolve_subject_query_ticker_overrides_active_symbol():
    from backend.graph import GraphRunner

    runner = GraphRunner.create()
    # active_symbol can be stale UI state; query ticker should win.
    result = _run(
        runner.ainvoke(thread_id="t-override", query="NVDA 最新股价和技术面分析", ui_context={"active_symbol": "GOOGL"})
    )

    subject = result.get("subject") or {}
    assert subject.get("subject_type") == "company"
    assert subject.get("tickers") == ["NVDA"]


def test_decide_output_mode_ui_override_and_safe_default():
    from backend.graph import GraphRunner

    runner = GraphRunner.create()

    # UI override wins
    result = _run(
        runner.ainvoke(
            thread_id="t-mode",
            query="分析影响",
            ui_context={"active_symbol": "AAPL"},
            output_mode="investment_report",
        )
    )
    assert result.get("output_mode") == "investment_report"

    # Generic "分析" should NOT imply investment_report
    result2 = _run(runner.ainvoke(thread_id="t-mode2", query="分析一下", ui_context={}))
    assert result2.get("output_mode") == "brief"

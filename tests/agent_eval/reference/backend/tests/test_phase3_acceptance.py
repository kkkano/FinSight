# -*- coding: utf-8 -*-
import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_phase3_news_selection_analyze_does_not_default_to_all_tools():
    from backend.graph import GraphRunner

    runner = GraphRunner.create()
    ui_context = {"selections": [{"type": "news", "id": "n1", "title": "t"}]}
    result = _run(runner.ainvoke(thread_id="t-n1", query="分析影响", ui_context=ui_context))

    plan = result.get("plan_ir") or {}
    names = [s.get("name") for s in (plan.get("steps") or [])]
    # In Phase 3, the key requirement is "minimal by default".
    assert "get_stock_price" not in names
    assert "analyze_historical_drawdowns" not in names
    assert "get_company_info" not in names


def test_phase3_investment_report_mode_can_expand_with_why():
    from backend.graph import GraphRunner

    runner = GraphRunner.create()
    result = _run(
        runner.ainvoke(
            thread_id="t-r1",
            # Use a query with unambiguous financial intent ("股价") so that
            # Tier 2 keyword detection binds active_symbol without needing LLM.
            query="分析AAPL股价，生成投资报告",
            ui_context={"active_symbol": "AAPL"},
        )
    )

    assert result.get("output_mode") == "investment_report"
    plan = result.get("plan_ir") or {}
    steps = plan.get("steps") or []
    assert any(s.get("name") == "get_stock_price" for s in steps)
    assert all((s.get("why") or "").strip() for s in steps)


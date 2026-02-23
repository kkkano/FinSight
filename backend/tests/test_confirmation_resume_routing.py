# -*- coding: utf-8 -*-
import asyncio


def _run(coro):
    return asyncio.run(coro)


async def _resume_and_collect_final_state(runner, *, thread_id: str, resume_value: str):
    final_state = {}
    async for event in runner.resume(thread_id=thread_id, resume_value=resume_value):
        if event.get("event") == "on_chain_end":
            output = (event.get("data") or {}).get("output")
            if isinstance(output, dict):
                final_state = output
    return final_state


def test_confirmation_resume_adjust_replans_once(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "stub")

    from backend.graph import GraphRunner

    thread_id = "t-confirm-adjust"
    runner = GraphRunner.create()

    initial = _run(
        runner.ainvoke(
            thread_id=thread_id,
            query="Generate AAPL investment report",
            ui_context={"active_symbol": "AAPL"},
            output_mode="investment_report",
            confirmation_mode="required",
        )
    )
    assert initial.get("__interrupt__"), "first pass should be interrupted by confirmation gate"

    final = _run(
        _resume_and_collect_final_state(
            runner,
            thread_id=thread_id,
            resume_value="Adjust parameters: focus on fundamentals",
        )
    )

    assert "[User adjustment] focus on fundamentals" in str(final.get("query") or "")
    spans = [s.get("node") for s in ((final.get("trace") or {}).get("spans") or [])]
    assert spans.count("planner") >= 2, "adjust flow should route back to planner"


def test_confirmation_resume_confirm_executes_without_replanning(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "stub")

    from backend.graph import GraphRunner

    thread_id = "t-confirm-continue"
    runner = GraphRunner.create()

    initial = _run(
        runner.ainvoke(
            thread_id=thread_id,
            query="Generate TSLA investment report",
            ui_context={"active_symbol": "TSLA"},
            output_mode="investment_report",
            confirmation_mode="required",
        )
    )
    assert initial.get("__interrupt__"), "first pass should be interrupted by confirmation gate"

    final = _run(
        _resume_and_collect_final_state(
            runner,
            thread_id=thread_id,
            resume_value="Confirm execute",
        )
    )

    assert "[User adjustment]" not in str(final.get("query") or "")
    spans = [s.get("node") for s in ((final.get("trace") or {}).get("spans") or [])]
    assert spans.count("planner") == 1, "confirm flow should continue directly without replanning"

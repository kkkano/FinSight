# -*- coding: utf-8 -*-
import asyncio
import importlib


def _run(coro):
    return asyncio.run(coro)


async def _fake_synthesize(state):
    artifacts = dict(state.get("artifacts") or {})
    artifacts["draft_markdown"] = "request-frame graph smoke completed"
    return {"artifacts": artifacts, "trace": state.get("trace") or {}}


def _primary_frame(result: dict) -> dict:
    frame = result.get("request_frame")
    if isinstance(frame, dict) and frame:
        return frame
    understanding = result.get("understanding") if isinstance(result.get("understanding"), dict) else {}
    frame = understanding.get("request_frame") if isinstance(understanding, dict) else None
    return frame if isinstance(frame, dict) else {}


def test_graph_runner_forces_research_when_router_direct_conflicts_with_request_frame(monkeypatch):
    runner_mod = importlib.import_module("backend.graph.runner")
    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")
    router_mod = importlib.import_module("backend.graph.nodes.conversation_router")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == ["AAPL", "MSFT"]
        assert selection_ids == []
        return router_mod.ConversationDecision(
            execution_route="direct_answer",
            context_binding=router_mod.ContextBinding(source="none", confidence=0.0),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.72,
            needs_tools=False,
            reason="router attempted direct answer despite risk evidence obligation",
        )

    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "stub")
    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "false")
    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)
    monkeypatch.setattr(runner_mod, "synthesize", _fake_synthesize)

    result = _run(
        runner_mod.GraphRunner.create().ainvoke(
            thread_id="request-frame-graph-smoke-risk-compare",
            query="Compare AAPL and MSFT risk",
            ui_context={"market": "US"},
            output_mode="chat",
        )
    )

    frame = _primary_frame(result)
    steps = (result.get("plan_ir") or {}).get("steps") or []
    step_names = {step.get("name") for step in steps}
    nodes = [span.get("node") for span in (result.get("trace") or {}).get("spans") or []]

    assert (result.get("understanding") or {}).get("route") == "research"
    assert frame.get("relation") == "compare"
    assert frame.get("evidence_obligations") == ["price_snapshot", "risk_profile"]
    assert (frame.get("render_contract") or {}).get("shape") == "compare"
    assert {"policy_gate", "planner", "execute_plan", "synthesize", "render"}.issubset(set(nodes))
    assert {"get_stock_price", "analyze_historical_drawdowns", "get_factor_exposure"}.issubset(step_names)


def test_graph_runner_preserves_no_news_direct_answer_without_research(monkeypatch):
    runner_mod = importlib.import_module("backend.graph.runner")
    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == []
        assert selection_ids == []
        return None

    async def fake_reply(_state, _decision):
        return "Semiconductors can sell off together when investors de-risk the whole group."

    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "stub")
    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "false")
    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)
    monkeypatch.setattr(understand_mod, "generate_contextual_reply", fake_reply)

    result = _run(
        runner_mod.GraphRunner.create().ainvoke(
            thread_id="request-frame-graph-smoke-no-news",
            query="Do not look up news. Just tell me why semiconductors can sell off together.",
            ui_context={"market": "US"},
            output_mode="chat",
        )
    )

    frame = _primary_frame(result)
    nodes = [span.get("node") for span in (result.get("trace") or {}).get("spans") or []]

    assert (result.get("understanding") or {}).get("route") == "direct"
    assert frame.get("lane") == "answer"
    assert frame.get("evidence_obligations") == []
    assert "policy_gate" not in nodes
    assert not result.get("plan_ir")

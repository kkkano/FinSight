# -*- coding: utf-8 -*-
import asyncio

from backend.graph.nodes.planner_stub import planner_stub
from backend.graph.nodes.policy_gate import policy_gate


def test_backtest_request_frame_is_action_not_technical():
    from backend.graph.request_frame import compile_request_frame

    frame = compile_request_frame(
        query="backtest MACD strategy on AAPL",
        tickers=["AAPL"],
        output_mode="chat",
    )

    assert frame["lane"] == "action"
    assert frame["workflow_action"]["name"] == "backtest"
    assert frame["workflow_action"]["slots"]["ticker"] == "AAPL"
    assert frame["workflow_action"]["slots"]["strategy"] == "macd"
    assert frame["required_results"] == ["backtest_result"]
    assert frame["evidence_obligations"] == []
    assert frame["legacy_operation"]["name"] == "backtest"


def test_macd_analysis_request_frame_stays_technical_research():
    from backend.graph.request_frame import compile_request_frame

    frame = compile_request_frame(
        query="AAPL MACD technical analysis",
        tickers=["AAPL"],
        output_mode="chat",
    )

    assert frame["lane"] == "research"
    assert frame.get("workflow_action") is None
    assert "technical_snapshot" in frame["evidence_obligations"]
    assert frame["legacy_operation"]["name"] == "technical"


def test_backtest_definition_request_frame_stays_answer():
    from backend.graph.request_frame import compile_request_frame

    frame = compile_request_frame(
        query="what is backtesting?",
        tickers=[],
        output_mode="chat",
    )

    assert frame["lane"] == "answer"
    assert frame.get("workflow_action") is None
    assert frame["required_results"] == []
    assert frame["legacy_operation"]["name"] == "qa"


def test_understand_request_projects_backtest_action_before_technical_fast_path(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    state = {
        "query": "backtest MACD strategy on AAPL",
        "ui_context": {},
        "output_mode": "chat",
    }
    understanding = asyncio.run(understand_request(state))

    frame = understanding.get("request_frame") or {}
    tasks = understanding.get("tasks") or []
    task_ops = [(task.get("operation") or {}).get("name") for task in tasks]

    assert frame.get("lane") == "action"
    assert (frame.get("workflow_action") or {}).get("name") == "backtest"
    assert task_ops == ["backtest"]

    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    step_names = [step.get("name") for step in steps]

    assert "run_strategy_backtest" in step_names
    assert "technical_agent" not in step_names

    backtest_step = next(step for step in steps if step.get("name") == "run_strategy_backtest")
    assert (backtest_step.get("inputs") or {}).get("strategy") == "macd"

    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}
    assert coverage.get("status") == "ok"
    assert coverage.get("fulfilled_results") == ["backtest_result"]
    assert coverage.get("missing_results") == []


def test_coverage_validator_flags_missing_workflow_result():
    from backend.graph.coverage_validator import validate_plan_coverage
    from backend.graph.request_frame import compile_request_frame

    frame = compile_request_frame(
        query="backtest MACD strategy on AAPL",
        tickers=["AAPL"],
        output_mode="chat",
    )

    missing = validate_plan_coverage(request_frame=frame, plan_ir={"steps": []})
    assert missing["status"] == "missing"
    assert missing["missing_results"] == ["backtest_result"]

    covered = validate_plan_coverage(
        request_frame=frame,
        plan_ir={"steps": [{"kind": "tool", "name": "run_strategy_backtest", "inputs": {}}]},
    )
    assert covered["status"] == "ok"
    assert covered["fulfilled_results"] == ["backtest_result"]


def test_request_frame_for_valuation_compare_carries_evidence_contract(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    state = {
        "query": "NVDA and AMD which valuation is more reasonable",
        "ui_context": {},
        "output_mode": "chat",
    }
    understanding = asyncio.run(understand_request(state))
    frame = understanding.get("request_frame") or {}

    assert frame.get("lane") == "research"
    assert frame.get("relation") == "rank"
    assert (frame.get("subject") or {}).get("tickers") == ["NVDA", "AMD"]
    assert frame.get("evidence_obligations") == [
        "price_snapshot",
        "company_profile",
        "earnings_estimates",
    ]

    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}

    assert coverage.get("status") == "ok"
    assert coverage.get("fulfilled_evidence") == [
        "price_snapshot",
        "company_profile",
        "earnings_estimates",
    ]
    assert coverage.get("missing_evidence") == []


def test_request_frame_for_external_entity_impact_carries_risk_and_news(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    state = {
        "query": "Research whether TSLA could be affected by SpaceX",
        "ui_context": {},
        "output_mode": "chat",
    }
    understanding = asyncio.run(understand_request(state))
    frame = understanding.get("request_frame") or {}

    assert frame.get("lane") == "research"
    assert frame.get("relation") == "impact"
    assert (frame.get("subject") or {}).get("tickers") == ["TSLA"]
    assert frame.get("evidence_obligations") == [
        "price_snapshot",
        "news_context",
        "risk_profile",
    ]

    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}

    assert coverage.get("status") == "ok"
    assert coverage.get("missing_evidence") == []


def test_macro_mechanism_question_stays_answer_lane_without_evidence(monkeypatch):
    import importlib

    from backend.graph.request_frame import compile_request_frame

    frame = compile_request_frame(
        query="why do high valuation stocks dislike higher rates?",
        tickers=[],
        output_mode="chat",
    )

    assert frame.get("lane") == "answer"
    assert frame.get("relation") == "none"
    assert frame.get("evidence_obligations") == []
    assert (frame.get("intent_contract") or {}).get("facets") == []

    state = {
        "query": "why do high valuation stocks dislike higher rates?",
        "operation": {"name": "qa", "confidence": 0.0, "params": {}},
        "output_mode": "chat",
        "subject": {
            "subject_type": "macro",
            "tickers": [],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [],
        "request_frame": frame,
        "request_frames": [frame],
    }
    policy_out = policy_gate(state)
    plan_out = planner_stub({**state, **policy_out})
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}

    assert steps == []
    assert coverage.get("status") == "ok"
    assert coverage.get("missing_evidence") == []

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_generate_contextual_reply(_state, _decision):
        return "Higher rates reduce the present value of long-duration earnings."

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")
    monkeypatch.setattr(understand_mod, "generate_contextual_reply", fake_generate_contextual_reply)

    result = asyncio.run(
        understand_mod.understand_request(
            {
                "query": "why do high valuation stocks dislike higher rates?",
                "output_mode": "chat",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    assert (result.get("understanding") or {}).get("route") == "direct"
    assert result.get("tasks") == []
    assert (result.get("clarify") or {}).get("needed") is False
    assert ((result.get("request_frame") or {}).get("evidence_obligations") or []) == []


def test_current_macro_question_still_requires_macro_context(monkeypatch):
    from backend.graph.request_frame import compile_request_frame
    from backend.graph.nodes.understand_request import understand_request

    frame = compile_request_frame(
        query="How could this week's FOMC decision affect the Nasdaq?",
        tickers=[],
        output_mode="chat",
    )

    assert frame.get("lane") == "research"
    assert frame.get("evidence_obligations") == ["macro_context"]
    assert (frame.get("intent_contract") or {}).get("facets") == ["macro"]

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")
    understanding = asyncio.run(
        understand_request(
            {
                "query": "How could this week's FOMC decision affect the Nasdaq?",
                "output_mode": "chat",
                "ui_context": {},
                "trace": {},
            }
        )
    )

    assert (understanding.get("understanding") or {}).get("route") == "research"
    assert (understanding.get("request_frame") or {}).get("evidence_obligations") == ["macro_context"]


def test_chinese_mixed_ticker_valuation_compare_keeps_research_contract(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    state = {
        "query": "NVDA \u548c AMD \u54ea\u4e2a\u4f30\u503c\u66f4\u5408\u7406",
        "ui_context": {},
        "output_mode": "chat",
        "trace": {},
    }
    understanding = asyncio.run(understand_request(state))
    frame = understanding.get("request_frame") or {}

    assert (understanding.get("understanding") or {}).get("route") == "research"
    assert frame.get("relation") == "rank"
    assert (frame.get("subject") or {}).get("tickers") == ["NVDA", "AMD"]
    assert frame.get("evidence_obligations") == [
        "price_snapshot",
        "company_profile",
        "earnings_estimates",
    ]

    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    step_names = [step.get("name") for step in steps]
    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}

    assert step_names == [
        "get_stock_price",
        "get_company_info",
        "get_earnings_estimates",
        "get_stock_price",
        "get_company_info",
        "get_earnings_estimates",
    ]
    assert coverage.get("status") == "ok"
    assert coverage.get("missing_evidence") == []


def test_plain_compare_request_frame_full_path_plans_performance_comparison(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    state = {
        "query": "AAPL vs MSFT",
        "ui_context": {"market": "US"},
        "output_mode": "chat",
        "trace": {},
    }
    understanding = asyncio.run(understand_request(state))
    frame = understanding.get("request_frame") or {}

    assert frame.get("evidence_obligations") == ["performance_comparison"]

    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    step_names = {step.get("name") for step in steps}
    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}

    assert "get_performance_comparison" in step_names
    assert coverage.get("status") == "ok"
    assert coverage.get("fulfilled_evidence") == ["performance_comparison"]
    assert coverage.get("missing_evidence") == []


def test_router_hints_compile_to_independent_request_frames(monkeypatch):
    import importlib

    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert set(tickers) == {"AAPL", "MSFT"}
        assert selection_ids == []
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="AAPL, MSFT, Fed rates"),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.9,
            needs_tools=True,
            reason="router emitted atomized frames",
            task_hints=(
                {"subject_type": "company", "subject_label": "AAPL", "tickers": ["AAPL"], "operation": "price", "params": {}},
                {"subject_type": "company", "subject_label": "MSFT", "tickers": ["MSFT"], "operation": "fetch", "params": {"topic": "news"}},
                {"subject_type": "macro", "subject_label": "Fed rates", "tickers": [], "operation": "macro_brief", "params": {}},
            ),
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    state = {
        "query": "Check AAPL price, MSFT news, then explain Fed rate impact",
        "ui_context": {},
        "output_mode": "chat",
        "trace": {},
    }
    understanding = asyncio.run(understand_mod.understand_request(state))

    frames = understanding.get("request_frames") or []
    assert [frame.get("frame_id") for frame in frames] == [
        "router_hint_1",
        "router_hint_2",
        "router_hint_3",
    ]
    assert [(frame.get("subject") or {}).get("tickers") for frame in frames] == [
        ["AAPL"],
        ["MSFT"],
        [],
    ]
    assert [frame.get("evidence_obligations") for frame in frames] == [
        ["price_snapshot"],
        ["news_context"],
        ["macro_context"],
    ]

    assert understanding.get("request_frame") == frames[0]


def test_router_direct_cannot_swallow_request_frame_evidence(monkeypatch):
    import importlib

    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == ["AAPL", "MSFT"]
        assert selection_ids == []
        return ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(source="none", confidence=0.0),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.72,
            needs_tools=False,
            reason="router thought this was explainable without tools",
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    state = {
        "query": "Compare AAPL and MSFT risk",
        "ui_context": {"market": "US"},
        "output_mode": "chat",
        "trace": {},
    }
    understanding = asyncio.run(understand_mod.understand_request(state))
    frame = understanding.get("request_frame") or {}

    assert (understanding.get("understanding") or {}).get("route") == "research"
    assert frame.get("relation") == "compare"
    assert frame.get("evidence_obligations") == ["price_snapshot", "risk_profile"]
    assert (frame.get("render_contract") or {}).get("shape") == "compare"

    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    step_names = {step.get("name") for step in steps}
    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}

    assert {"get_stock_price", "analyze_historical_drawdowns", "get_factor_exposure"}.issubset(step_names)
    assert coverage.get("status") == "ok"
    assert coverage.get("missing_evidence") == []


def test_router_direct_no_news_compare_risk_still_requires_research(monkeypatch):
    import importlib

    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == ["AAPL", "MSFT"]
        assert selection_ids == []
        return ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(source="none", confidence=0.0),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.72,
            needs_tools=False,
            reason="router over-applied no-news direct answer preference",
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    state = {
        "query": "Do not look up news; compare AAPL and MSFT risk",
        "ui_context": {"market": "US"},
        "output_mode": "chat",
        "trace": {},
    }
    understanding = asyncio.run(understand_mod.understand_request(state))
    frame = understanding.get("request_frame") or {}

    assert (understanding.get("understanding") or {}).get("route") == "research"
    assert frame.get("relation") == "compare"
    assert frame.get("evidence_obligations") == ["price_snapshot", "risk_profile"]

    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    step_names = {step.get("name") for step in steps}
    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}

    assert {"get_stock_price", "analyze_historical_drawdowns", "get_factor_exposure"}.issubset(step_names)
    assert "get_company_news" not in step_names
    assert coverage.get("status") == "ok"
    assert coverage.get("missing_evidence") == []


def test_deterministic_request_frames_split_compound_query_without_router(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    state = {
        "query": "Check AAPL price, MSFT news, then explain Fed rate impact",
        "ui_context": {},
        "output_mode": "chat",
    }
    understanding = asyncio.run(understand_request(state))

    frames = understanding.get("request_frames") or []
    assert [frame.get("frame_id") for frame in frames] == [
        "query_frame_1",
        "query_frame_2",
        "query_frame_3",
    ]
    assert [(frame.get("subject") or {}).get("tickers") for frame in frames] == [
        ["AAPL"],
        ["MSFT"],
        [],
    ]
    assert [frame.get("evidence_obligations") for frame in frames] == [
        ["price_snapshot"],
        ["news_context"],
        ["macro_context"],
    ]


def test_policy_uses_request_frame_evidence_when_legacy_operation_is_coarse():
    frame = {
        "frame_id": "frame_policy",
        "lane": "research",
        "subject": {"type": "company", "tickers": ["AAPL"]},
        "evidence_obligations": ["technical_snapshot", "risk_profile"],
        "required_results": [],
        "legacy_operation": {"name": "qa", "confidence": 0.5, "params": {}},
    }
    state = {
        "query": "AAPL technical and risk context",
        "operation": {"name": "qa", "confidence": 0.5, "params": {}},
        "output_mode": "chat",
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "request_frame": frame,
        "request_frames": [frame],
    }

    policy_out = policy_gate(state)
    policy = policy_out.get("policy") or {}

    assert policy.get("required_evidence") == ["technical_snapshot", "risk_profile"]
    assert {"get_technical_snapshot", "analyze_historical_drawdowns", "get_factor_exposure"}.issubset(
        set(policy.get("allowed_tools") or [])
    )
    assert {"technical_agent", "risk_agent"}.issubset(set(policy.get("allowed_agents") or []))
    assert (policy.get("agent_selection") or {}).get("reason") == "request_frame_required_evidence"


def test_policy_uses_request_frame_action_result_when_legacy_operation_is_coarse():
    frame = {
        "frame_id": "frame_backtest",
        "lane": "action",
        "subject": {"type": "company", "tickers": ["AAPL"]},
        "evidence_obligations": [],
        "required_results": ["backtest_result"],
        "workflow_action": {
            "name": "backtest",
            "slots": {"ticker": "AAPL", "strategy": "macd"},
            "required_results": ["backtest_result"],
        },
        "legacy_operation": {"name": "backtest", "confidence": 0.9, "params": {"strategy": "macd"}},
    }
    state = {
        "query": "run this action",
        "operation": {"name": "qa", "confidence": 0.5, "params": {}},
        "output_mode": "chat",
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "request_frame": frame,
        "request_frames": [frame],
    }

    policy = (policy_gate(state).get("policy") or {})

    assert "run_strategy_backtest" in set(policy.get("allowed_tools") or [])
    assert "backtest_result" in policy.get("required_results", [])


def test_planner_uses_request_frame_evidence_without_legacy_tasks():
    frame = {
        "frame_id": "frame_plan_evidence",
        "lane": "research",
        "subject": {"type": "company", "tickers": ["AAPL"]},
        "evidence_obligations": ["technical_snapshot", "risk_profile"],
        "required_results": [],
        "legacy_operation": {"name": "qa", "confidence": 0.5, "params": {}},
    }
    state = {
        "query": "AAPL technical and risk context",
        "operation": {"name": "qa", "confidence": 0.5, "params": {}},
        "output_mode": "chat",
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [],
        "request_frame": frame,
        "request_frames": [frame],
    }

    policy_out = policy_gate(state)
    plan_out = planner_stub({**state, **policy_out})
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    step_names = {step.get("name") for step in steps}
    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}

    assert {"get_technical_snapshot", "analyze_historical_drawdowns", "get_factor_exposure"}.issubset(step_names)
    assert coverage.get("status") == "ok"
    assert coverage.get("fulfilled_evidence") == ["technical_snapshot", "risk_profile"]
    assert coverage.get("missing_evidence") == []


def test_planner_uses_request_frame_performance_comparison_without_legacy_tasks():
    frame = {
        "frame_id": "frame_compare",
        "lane": "research",
        "relation": "compare",
        "subject": {"type": "company", "tickers": ["AAPL", "MSFT"]},
        "evidence_obligations": ["performance_comparison"],
        "required_results": [],
        "legacy_operation": {"name": "compare", "confidence": 0.86, "params": {}},
    }
    state = {
        "query": "AAPL vs MSFT",
        "operation": {"name": "compare", "confidence": 0.86, "params": {}},
        "output_mode": "chat",
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL", "MSFT"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [],
        "ui_context": {"market": "US"},
        "request_frame": frame,
        "request_frames": [frame],
    }

    policy_out = policy_gate(state)
    plan_out = planner_stub({**state, **policy_out})
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    comparison_step = next((step for step in steps if step.get("name") == "get_performance_comparison"), None)
    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}

    assert comparison_step is not None
    assert (comparison_step.get("inputs") or {}).get("tickers") == {"AAPL": "AAPL", "MSFT": "MSFT"}
    assert coverage.get("status") == "ok"
    assert coverage.get("fulfilled_evidence") == ["performance_comparison"]
    assert coverage.get("missing_evidence") == []


def test_planner_uses_request_frame_holdings_evidence_without_legacy_tasks(monkeypatch):
    monkeypatch.setenv("SEC_HOLDINGS_ENABLED", "true")
    frame = {
        "frame_id": "frame_plan_holdings",
        "lane": "research",
        "subject": {"type": "company", "tickers": ["AAPL"]},
        "evidence_obligations": ["holdings_ownership"],
        "required_results": [],
        "legacy_operation": {"name": "qa", "confidence": 0.5, "params": {}},
    }
    state = {
        "query": "Research AAPL institutional holdings",
        "operation": {"name": "qa", "confidence": 0.5, "params": {}},
        "output_mode": "chat",
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [],
        "ui_context": {"market": "US"},
        "request_frame": frame,
        "request_frames": [frame],
    }

    policy_out = policy_gate(state)
    plan_out = planner_stub({**state, **policy_out})
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    step_names = {step.get("name") for step in steps}
    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}

    assert "get_institution_holdings_by_ticker" in step_names
    assert "get_insider_transactions" in step_names
    assert coverage.get("status") == "ok"
    assert coverage.get("fulfilled_evidence") == ["holdings_ownership"]
    assert coverage.get("missing_evidence") == []


def test_planner_uses_request_frame_action_without_legacy_tasks():
    frame = {
        "frame_id": "frame_plan_backtest",
        "lane": "action",
        "subject": {"type": "company", "tickers": ["AAPL"]},
        "evidence_obligations": [],
        "required_results": ["backtest_result"],
        "workflow_action": {
            "name": "backtest",
            "slots": {"ticker": "AAPL", "strategy": "macd"},
            "required_results": ["backtest_result"],
        },
        "legacy_operation": {"name": "backtest", "confidence": 0.9, "params": {"strategy": "macd"}},
    }
    state = {
        "query": "run this action",
        "operation": {"name": "qa", "confidence": 0.5, "params": {}},
        "output_mode": "chat",
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [],
        "request_frame": frame,
        "request_frames": [frame],
    }

    policy_out = policy_gate(state)
    plan_out = planner_stub({**state, **policy_out})
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    backtest_step = next((step for step in steps if step.get("name") == "run_strategy_backtest"), None)
    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}

    assert backtest_step is not None
    assert (backtest_step.get("inputs") or {}).get("strategy") == "macd"
    assert coverage.get("status") == "ok"
    assert coverage.get("fulfilled_results") == ["backtest_result"]
    assert coverage.get("missing_results") == []


def test_planner_validates_all_request_frames_without_legacy_tasks():
    frames = [
        {
            "frame_id": "query_frame_1",
            "lane": "research",
            "subject": {"type": "company", "tickers": ["AAPL"]},
            "evidence_obligations": ["price_snapshot"],
            "required_results": [],
            "legacy_operation": {"name": "price", "confidence": 0.8, "params": {}},
        },
        {
            "frame_id": "query_frame_2",
            "lane": "research",
            "subject": {"type": "company", "tickers": ["MSFT"]},
            "evidence_obligations": ["news_context"],
            "required_results": [],
            "legacy_operation": {"name": "fetch", "confidence": 0.8, "params": {"topic": "news"}},
        },
        {
            "frame_id": "query_frame_3",
            "lane": "research",
            "subject": {"type": "macro", "tickers": []},
            "evidence_obligations": ["macro_context"],
            "required_results": [],
            "legacy_operation": {"name": "macro_brief", "confidence": 0.8, "params": {}},
        },
    ]
    state = {
        "query": "Check AAPL price, MSFT news, then explain Fed rate impact",
        "operation": {"name": "qa", "confidence": 0.5, "params": {}},
        "output_mode": "chat",
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL", "MSFT"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [],
        "request_frame": frames[0],
        "request_frames": frames,
    }

    policy_out = policy_gate(state)
    plan_out = planner_stub({**state, **policy_out})
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    step_names = {step.get("name") for step in steps}
    coverage = (plan_out.get("trace") or {}).get("coverage_validator") or {}

    assert {"get_stock_price", "get_company_news", "get_official_macro_releases"}.issubset(step_names)
    assert coverage.get("status") == "ok"
    assert coverage.get("fulfilled_evidence") == ["price_snapshot", "news_context", "macro_context"]
    assert coverage.get("missing_evidence") == []
    assert [item.get("frame_id") for item in coverage.get("frame_results", [])] == [
        "query_frame_1",
        "query_frame_2",
        "query_frame_3",
    ]


def test_intent_contract_mode_off_does_not_emit_authoritative_frames(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")
    monkeypatch.setenv("FINSIGHT_INTENT_CONTRACT_MODE", "off")

    state = {
        "query": "Research whether TSLA could be affected by SpaceX",
        "ui_context": {},
        "output_mode": "chat",
        "trace": {},
    }
    result = asyncio.run(understand_request(state))
    understanding = result.get("understanding") or {}
    trace = result.get("trace") or {}

    assert "request_frame" not in result
    assert "request_frames" not in result
    assert "intent_contract" not in result
    assert "intent_contracts" not in result
    assert "request_frame" not in understanding
    assert "request_frame_shadow" not in trace


def test_intent_contract_mode_shadow_records_only_trace_shadow(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")
    monkeypatch.setenv("FINSIGHT_INTENT_CONTRACT_MODE", "shadow")

    state = {
        "query": "Research whether TSLA could be affected by SpaceX",
        "ui_context": {},
        "output_mode": "chat",
        "trace": {},
    }
    result = asyncio.run(understand_request(state))
    understanding = result.get("understanding") or {}
    trace = result.get("trace") or {}

    assert "request_frame" not in result
    assert "request_frames" not in result
    assert "intent_contract" not in result
    assert "request_frame" not in understanding
    assert isinstance(trace.get("request_frame_shadow"), dict)
    assert "request_frame" not in trace

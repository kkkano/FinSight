# -*- coding: utf-8 -*-
import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_planner_ab_variant_is_deterministic_and_present_in_runtime(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "stub")
    monkeypatch.setenv("LANGGRAPH_PLANNER_AB_ENABLED", "true")
    monkeypatch.setenv("LANGGRAPH_PLANNER_AB_SPLIT", "50")
    monkeypatch.setenv("LANGGRAPH_PLANNER_AB_SALT", "unit-test-salt")

    from backend.graph.nodes.planner import planner

    state = {
        "thread_id": "tenant:user:thread-fixed",
        "query": "analyze impact",
        "output_mode": "brief",
        "operation": {"name": "analyze_impact", "confidence": 0.7, "params": {}},
        "subject": {"subject_type": "unknown", "selection_payload": []},
        "policy": {"budget": {"max_rounds": 3, "max_tools": 4}, "allowed_tools": ["search"]},
        "trace": {},
    }

    out1 = _run(planner(state))
    out2 = _run(planner(state))

    runtime1 = (out1.get("trace") or {}).get("planner_runtime") or {}
    runtime2 = (out2.get("trace") or {}).get("planner_runtime") or {}

    assert runtime1.get("variant") in {"A", "B"}
    assert runtime1.get("variant") == runtime2.get("variant")


def test_planner_runtime_contains_variant_when_llm_init_fails(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "llm")
    monkeypatch.setenv("LANGGRAPH_PLANNER_AB_ENABLED", "true")
    monkeypatch.setenv("LANGGRAPH_PLANNER_AB_SPLIT", "50")
    monkeypatch.setenv("LANGGRAPH_PLANNER_AB_SALT", "unit-test-salt-2")

    import backend.llm_config as llm_config

    def _boom(*_args, **_kwargs):
        raise ValueError("no api key")

    monkeypatch.setattr(llm_config, "create_llm", _boom)

    from backend.graph.nodes.planner import planner

    state = {
        "thread_id": "tenant:user:thread-fallback",
        "query": "analyze impact",
        "output_mode": "brief",
        "operation": {"name": "analyze_impact", "confidence": 0.7, "params": {}},
        "subject": {"subject_type": "unknown", "selection_payload": []},
        "policy": {"budget": {"max_rounds": 3, "max_tools": 4}, "allowed_tools": ["search"]},
        "trace": {},
    }

    out = _run(planner(state))
    runtime = (out.get("trace") or {}).get("planner_runtime") or {}
    assert runtime.get("fallback") is True
    assert runtime.get("variant") in {"A", "B"}


def test_planner_llm_mode_retries_on_invalid_json_then_recovers(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "llm")

    class _Resp:
        def __init__(self, content):
            self.content = content

    class _FakeLLM:
        def __init__(self):
            self.calls = 0

        async def ainvoke(self, _messages):
            self.calls += 1
            if self.calls == 1:
                return _Resp(
                    "{ goal: 'demo', output_mode: 'brief', subject: {'subject_type':'company','tickers':['AAPL']},"
                    " steps: [], budget: {'max_rounds': 3, 'max_tools': 2}, synthesis: {'style':'concise','sections': []}, }"
                )
            return _Resp(
                """
                {
                  "goal": "demo",
                  "subject": {"subject_type": "company", "tickers": ["AAPL"]},
                  "output_mode": "brief",
                  "steps": [],
                  "budget": {"max_rounds": 3, "max_tools": 2},
                  "synthesis": {"style": "concise", "sections": []}
                }
                """
            )

    import backend.llm_config as llm_config

    fake = _FakeLLM()
    monkeypatch.setattr(llm_config, "create_llm", lambda *args, **kwargs: fake)

    from backend.graph.nodes.planner import planner

    state = {
        "query": "Analyze AAPL",
        "output_mode": "brief",
        "operation": {"name": "qa", "confidence": 0.7, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["AAPL"], "selection_payload": []},
        "policy": {"budget": {"max_rounds": 3, "max_tools": 2}, "allowed_tools": ["search"], "allowed_agents": []},
        "trace": {},
    }

    out = _run(planner(state))
    runtime = (out.get("trace") or {}).get("planner_runtime") or {}

    assert runtime.get("mode") == "llm"
    assert runtime.get("fallback") is False
    parse_info = runtime.get("json_parse") or {}
    assert parse_info.get("json_retry_used") is True
    assert fake.calls >= 2


def test_planner_llm_mode_records_json_error_context_when_retry_still_invalid(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "llm")

    class _Resp:
        def __init__(self, content):
            self.content = content

    class _AlwaysInvalidLLM:
        async def ainvoke(self, _messages):
            return _Resp("{ goal: 'demo', steps: [ }")

    import backend.llm_config as llm_config

    monkeypatch.setattr(llm_config, "create_llm", lambda *args, **kwargs: _AlwaysInvalidLLM())

    from backend.graph.nodes.planner import planner

    state = {
        "query": "Analyze AAPL",
        "output_mode": "brief",
        "operation": {"name": "qa", "confidence": 0.7, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["AAPL"], "selection_payload": []},
        "policy": {"budget": {"max_rounds": 3, "max_tools": 2}, "allowed_tools": ["search"], "allowed_agents": []},
        "trace": {},
    }

    out = _run(planner(state))
    runtime = (out.get("trace") or {}).get("planner_runtime") or {}
    assert runtime.get("fallback") is True

    json_error = runtime.get("json_parse_error") or {}
    assert json_error.get("json_retry_used") is True
    assert isinstance(json_error.get("first_attempt"), dict)
    assert isinstance(json_error.get("second_attempt"), dict)

    failures = (out.get("trace") or {}).get("failures") or []
    assert failures and isinstance(failures, list)
    metadata = (failures[-1] or {}).get("metadata") or {}
    assert isinstance(metadata.get("json_parse_error"), dict)


def test_planner_llm_mode_falls_back_when_llm_unavailable(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "llm")

    import backend.llm_config as llm_config

    def _boom(*_args, **_kwargs):
        raise ValueError("no api key")

    monkeypatch.setattr(llm_config, "create_llm", _boom)

    from backend.graph.nodes.planner import planner

    state = {
        "query": "analyze impact",
        "output_mode": "brief",
        "operation": {"name": "analyze_impact", "confidence": 0.7, "params": {}},
        "subject": {"subject_type": "unknown", "selection_payload": []},
        "policy": {"budget": {"max_rounds": 3, "max_tools": 4}, "allowed_tools": ["search"]},
        "trace": {},
    }

    out = _run(planner(state))
    assert isinstance(out.get("plan_ir"), dict)
    runtime = (out.get("trace") or {}).get("planner_runtime") or {}
    assert runtime.get("mode") == "llm"
    assert runtime.get("fallback") is True


def test_planner_llm_mode_enforces_state_output_mode_and_allowlist(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "llm")

    class _Resp:
        def __init__(self, content):
            self.content = content

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return _Resp(
                """
                ```json
                {
                  "goal": "demo",
                  "subject": {"subject_type": "company", "tickers": ["AAPL"]},
                  "output_mode": "investment_report",
                  "steps": [
                    {"id":"sX","kind":"tool","name":"search","inputs":{"query":"AAPL news"},"why":"ok","optional":true},
                    {"id":"sY","kind":"tool","name":"get_stock_price","inputs":{"ticker":"AAPL"},"why":"no","optional":true}
                  ],
                  "budget": {"max_rounds": 9, "max_tools": 99},
                  "synthesis": {"style": "concise", "sections": []}
                }
                ```
                """
            )

    import backend.llm_config as llm_config

    monkeypatch.setattr(llm_config, "create_llm", lambda *args, **kwargs: _FakeLLM())

    from backend.graph.nodes.planner import planner

    selection_payload = [{"type": "news", "id": "n1", "title": "t", "snippet": "s"}]
    state = {
        "query": "analyze impact",
        "output_mode": "brief",
        "operation": {"name": "analyze_impact", "confidence": 0.7, "params": {}},
        "subject": {"subject_type": "news_item", "selection_payload": selection_payload},
        "policy": {"budget": {"max_rounds": 3, "max_tools": 1}, "allowed_tools": ["search"], "allowed_agents": []},
        "trace": {},
    }

    out = _run(planner(state))
    runtime = (out.get("trace") or {}).get("planner_runtime") or {}
    assert runtime.get("mode") == "llm"
    assert runtime.get("fallback") is False

    plan = out.get("plan_ir") or {}
    assert plan.get("output_mode") == "brief", "planner must not self-upgrade output_mode"
    assert (plan.get("budget") or {}).get("max_tools") == 1, "budget must be enforced from policy"

    steps = plan.get("steps") or []
    assert steps and steps[0].get("name") == "summarize_selection"
    assert all(s.get("name") in ("summarize_selection", "search") for s in steps)
    assert len([s for s in steps if s.get("kind") in ("tool", "agent")]) <= 1


def test_planner_llm_mode_sanitizes_extra_fields_and_avoids_validation_errors(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "llm")

    class _Resp:
        def __init__(self, content):
            self.content = content

    class _FakeLLM:
        async def ainvoke(self, _messages):
            # Intentionally include extra fields and a malformed synthesis object.
            return _Resp(
                """
                {
                  "goal": "compare",
                  "subject": {"subject_type": "company", "tickers": ["AAPL", "MSFT"], "extra": "x"},
                  "output_mode": "investment_report",
                  "steps": [
                    {"id":"s1","kind":"tool","name":"get_performance_comparison","inputs":{"tickers":["AAPL","MSFT"]},"why":"x","optional":false,"extra":"bad"}
                  ],
                  "budget": {"max_rounds": 99, "max_tools": 99, "extra": "bad"},
                  "synthesis": {"kind":"llm","name":"investment_compare","style":"concise","sections":["a"],"extra":"bad"},
                  "top_extra": "bad"
                }
                """
            )

    import backend.llm_config as llm_config

    monkeypatch.setattr(llm_config, "create_llm", lambda *args, **kwargs: _FakeLLM())

    from backend.graph.nodes.planner import planner

    state = {
        "query": "compare AAPL and MSFT",
        "output_mode": "brief",
        "operation": {"name": "compare", "confidence": 0.9, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["AAPL", "MSFT"], "selection_payload": []},
        "policy": {
            "budget": {"max_rounds": 3, "max_tools": 2},
            "allowed_tools": ["get_performance_comparison", "search"],
            "allowed_agents": [],
        },
        "trace": {},
    }

    out = _run(planner(state))
    runtime = (out.get("trace") or {}).get("planner_runtime") or {}
    assert runtime.get("mode") == "llm"
    assert runtime.get("fallback") is False

    plan = out.get("plan_ir") or {}
    assert plan.get("output_mode") == "brief"
    assert set((plan.get("synthesis") or {}).keys()) == {"style", "sections"}

    steps = plan.get("steps") or []
    assert any(s.get("name") == "get_performance_comparison" for s in steps)
    assert all("extra" not in s for s in steps), "planner should strip unknown step fields"


def test_planner_llm_mode_investment_report_enforces_scored_agent_subset(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "llm")
    monkeypatch.setenv("LANGGRAPH_REPORT_MAX_AGENTS", "4")
    monkeypatch.setenv("LANGGRAPH_REPORT_MIN_AGENTS", "2")

    class _Resp:
        def __init__(self, content):
            self.content = content

    class _FakeLLM:
        async def ainvoke(self, _messages):
            # Intentionally omit agent steps; enforcement should add score-selected agents.
            return _Resp(
                """
                {
                  "goal": "demo",
                  "subject": {"subject_type": "company", "tickers": ["AAPL"]},
                  "output_mode": "investment_report",
                  "steps": [
                    {"id":"s1","kind":"tool","name":"search","inputs":{"query":"AAPL news"},"why":"ok","optional":true}
                  ],
                  "budget": {"max_rounds": 9, "max_tools": 99},
                  "synthesis": {"style": "concise", "sections": []}
                }
                """
            )

    import backend.llm_config as llm_config

    monkeypatch.setattr(llm_config, "create_llm", lambda *args, **kwargs: _FakeLLM())

    from backend.graph.nodes.planner import planner

    state = {
        "query": "Detailed investment report for AAPL",
        "output_mode": "investment_report",
        "operation": {"name": "generate_report", "confidence": 0.9, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["AAPL"], "selection_payload": []},
        "policy": {
            "budget": {"max_rounds": 6, "max_tools": 8},
            "allowed_tools": ["search"],
            "allowed_agents": [
                "price_agent",
                "news_agent",
                "fundamental_agent",
                "technical_agent",
                "macro_agent",
                "deep_search_agent",
            ],
        },
        "trace": {},
    }

    out = _run(planner(state))
    runtime = (out.get("trace") or {}).get("planner_runtime") or {}
    assert runtime.get("mode") == "llm"
    assert runtime.get("fallback") is False

    plan = out.get("plan_ir") or {}
    steps = plan.get("steps") or []
    step_ids = [s.get("id") for s in steps]
    assert len(step_ids) == len(set(step_ids)), "planner must emit unique step ids to avoid step_results overwrites"

    agent_steps = [s for s in (plan.get("steps") or []) if s.get("kind") == "agent"]
    names = {s.get("name") for s in agent_steps}
    assert {"price_agent", "news_agent", "fundamental_agent"}.issubset(names)
    assert "deep_search_agent" not in names
    assert len(names) <= 4

    for step in agent_steps:
        inputs = step.get("inputs") or {}
        assert inputs.get("query") == state["query"]
        assert inputs.get("ticker") == "AAPL"


def test_planner_dashboard_forced_agents_skip_second_pass_recapping(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "llm")
    monkeypatch.setenv("LANGGRAPH_REPORT_MAX_AGENTS", "4")
    monkeypatch.setenv("LANGGRAPH_REPORT_MIN_AGENTS", "2")

    class _Resp:
        def __init__(self, content):
            self.content = content

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return _Resp(
                """
                {
                  "goal": "demo",
                  "subject": {"subject_type": "company", "tickers": ["AAPL"]},
                  "output_mode": "investment_report",
                  "steps": [],
                  "budget": {"max_rounds": 6, "max_tools": 8},
                  "synthesis": {"style": "concise", "sections": []}
                }
                """
            )

    import backend.llm_config as llm_config

    monkeypatch.setattr(llm_config, "create_llm", lambda *args, **kwargs: _FakeLLM())

    from backend.graph.nodes.planner import planner

    state = {
        "query": "Dashboard one-click report for AAPL",
        "output_mode": "investment_report",
        "operation": {"name": "generate_report", "confidence": 0.95, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["AAPL"], "selection_payload": []},
        "ui_context": {"source": "dashboard_research_tab"},
        "policy": {
            "budget": {"max_rounds": 6, "max_tools": 8},
            "allowed_tools": ["search"],
            "allowed_agents": [
                "price_agent",
                "news_agent",
                "fundamental_agent",
                "technical_agent",
                "macro_agent",
                "risk_agent",
            ],
            "agent_selection": {
                "selected": [
                    "price_agent",
                    "news_agent",
                    "fundamental_agent",
                    "technical_agent",
                    "macro_agent",
                    "risk_agent",
                ],
                "required": [
                    "price_agent",
                    "news_agent",
                    "fundamental_agent",
                    "technical_agent",
                    "macro_agent",
                    "risk_agent",
                ],
                "forced_by_dashboard": True,
            },
        },
        "trace": {},
    }

    out = _run(planner(state))
    plan = out.get("plan_ir") or {}
    agent_steps = [s for s in (plan.get("steps") or []) if s.get("kind") == "agent"]
    names = [s.get("name") for s in agent_steps]

    assert names == [
        "price_agent",
        "news_agent",
        "fundamental_agent",
        "technical_agent",
        "macro_agent",
        "risk_agent",
    ]


def test_planner_force_all_agents_skips_report_recapping(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "llm")
    monkeypatch.setenv("LANGGRAPH_REPORT_MAX_AGENTS", "2")
    monkeypatch.setenv("LANGGRAPH_REPORT_MIN_AGENTS", "1")

    class _Resp:
        def __init__(self, content):
            self.content = content

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return _Resp(
                """
                {
                  "goal": "demo",
                  "subject": {"subject_type": "company", "tickers": ["AAPL"]},
                  "output_mode": "investment_report",
                  "steps": [],
                  "budget": {"max_rounds": 10, "max_tools": 12},
                  "synthesis": {"style": "concise", "sections": []}
                }
                """
            )

    import backend.llm_config as llm_config

    monkeypatch.setattr(llm_config, "create_llm", lambda *args, **kwargs: _FakeLLM())

    from backend.graph.nodes.planner import planner

    full_agents = [
        "price_agent",
        "news_agent",
        "fundamental_agent",
        "technical_agent",
        "macro_agent",
        "risk_agent",
        "deep_search_agent",
    ]
    state = {
        "query": "Generate investment report for AAPL",
        "output_mode": "investment_report",
        "operation": {"name": "generate_report", "confidence": 0.95, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["AAPL"], "selection_payload": []},
        "policy": {
            "budget": {"max_rounds": 10, "max_tools": 12},
            "allowed_tools": ["search"],
            "allowed_agents": full_agents,
            "force_all_agents": True,
            "agent_selection": {
                "selected": full_agents,
                "required": full_agents,
                "force_all_agents": True,
            },
        },
        "trace": {},
    }

    out = _run(planner(state))
    plan = out.get("plan_ir") or {}
    agent_steps = [s for s in (plan.get("steps") or []) if s.get("kind") == "agent"]
    names = [s.get("name") for s in agent_steps]

    assert names == full_agents


def test_planner_investment_report_budget_prioritizes_selected_agents_over_tools(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "llm")
    monkeypatch.setenv("LANGGRAPH_REPORT_MAX_AGENTS", "4")
    monkeypatch.setenv("LANGGRAPH_REPORT_MIN_AGENTS", "2")

    class _Resp:
        def __init__(self, content):
            self.content = content

    class _FakeLLM:
        async def ainvoke(self, _messages):
            # Create a plan that would exceed max_tools unless we drop tools or agents.
            return _Resp(
                """
                {
                  "goal": "demo",
                  "subject": {"subject_type": "company", "tickers": ["TSLA"]},
                  "output_mode": "investment_report",
                  "steps": [
                    {"id":"s1","kind":"tool","name":"search","inputs":{"query":"TSLA news"},"why":"ok"},
                    {"id":"s2","kind":"tool","name":"get_company_news","inputs":{"ticker":"TSLA","limit":5},"why":"ok"},
                    {"id":"s3","kind":"tool","name":"get_current_datetime","inputs":{},"why":"ok"},
                    {"id":"s4","kind":"tool","name":"get_company_info","inputs":{"ticker":"TSLA"},"why":"ok"}
                  ],
                  "budget": {"max_rounds": 9, "max_tools": 99},
                  "synthesis": {"style": "concise", "sections": []}
                }
                """
            )

    import backend.llm_config as llm_config

    monkeypatch.setattr(llm_config, "create_llm", lambda *args, **kwargs: _FakeLLM())

    from backend.graph.nodes.planner import planner

    state = {
        "query": "Deep research on TSLA and generate an investment report",
        "output_mode": "investment_report",
        "operation": {"name": "generate_report", "confidence": 0.9, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["TSLA"], "selection_payload": []},
        "policy": {
            "budget": {"max_rounds": 6, "max_tools": 8},
            "allowed_tools": ["search", "get_company_news", "get_current_datetime", "get_company_info"],
            "allowed_agents": [
                "price_agent",
                "news_agent",
                "fundamental_agent",
                "technical_agent",
                "macro_agent",
                "deep_search_agent",
            ],
        },
        "trace": {},
    }

    out = _run(planner(state))
    plan = out.get("plan_ir") or {}
    steps = plan.get("steps") or []

    # Ensure score-selected baseline agents are preserved under max_tools cap.
    agent_steps = [s for s in steps if s.get("kind") == "agent"]
    names = {s.get("name") for s in agent_steps}
    assert "deep_search_agent" in names
    assert {"price_agent", "news_agent", "fundamental_agent"}.issubset(names)
    assert len(names) <= 4

    step_ids = [s.get("id") for s in steps]
    assert len(step_ids) == len(set(step_ids))

    # Budget applies to tool+agent steps; selected baseline agents are kept first.
    tool_agent_steps = [s for s in steps if s.get("kind") in ("tool", "agent")]
    assert len(tool_agent_steps) <= 8


def test_planner_report_adds_progressive_escalation_inputs_for_high_cost_agents(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_PLANNER_MODE", "llm")

    class _Resp:
        def __init__(self, content):
            self.content = content

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return _Resp(
                """
                {
                  "goal": "read filing",
                  "subject": {"subject_type": "filing", "tickers": ["AAPL"]},
                  "output_mode": "investment_report",
                  "steps": [
                    {"id":"s1","kind":"tool","name":"search","inputs":{"query":"AAPL filing key points"},"why":"ok"}
                  ],
                  "budget": {"max_rounds": 4, "max_tools": 6},
                  "synthesis": {"style": "concise", "sections": []}
                }
                """
            )

    import backend.llm_config as llm_config

    monkeypatch.setattr(llm_config, "create_llm", lambda *args, **kwargs: _FakeLLM())

    from backend.graph.nodes.planner import planner

    state = {
        "query": "Read filing and deep analysis",
        "output_mode": "investment_report",
        "operation": {"name": "generate_report", "confidence": 0.9, "params": {}},
        "subject": {"subject_type": "filing", "tickers": ["AAPL"], "selection_payload": []},
        "policy": {
            "budget": {"max_rounds": 4, "max_tools": 6},
            "allowed_tools": ["search"],
            "allowed_agents": ["deep_search_agent", "fundamental_agent", "macro_agent"],
            "agent_selection": {"required": ["deep_search_agent", "fundamental_agent"]},
        },
        "trace": {},
    }

    out = _run(planner(state))
    plan = out.get("plan_ir") or {}
    steps = plan.get("steps") or []
    deep_steps = [s for s in steps if s.get("kind") == "agent" and s.get("name") == "deep_search_agent"]
    assert deep_steps, "filing report should include deep_search_agent"
    deep_inputs = deep_steps[0].get("inputs") or {}
    assert deep_inputs.get("__escalation_stage") == "high_cost"
    assert "__run_if_min_confidence" in deep_inputs
    assert deep_inputs.get("__force_run") is True

    runtime = (out.get("trace") or {}).get("planner_runtime") or {}
    assertions = runtime.get("budget_assertions") or {}
    assert "estimated_cost_units" in assertions
    assert "estimated_latency_ms" in assertions
    assert "cost_within_budget" in assertions
    assert "latency_within_budget" in assertions


def test_is_deep_hint_respects_analysis_depth_context():
    from backend.graph.nodes.planner import _is_deep_hint

    neutral_query = "Assess AAPL trend and valuation"
    assert _is_deep_hint(
        neutral_query,
        {"ui_context": {"analysis_depth": "deep_research"}},
    )
    assert not _is_deep_hint(
        neutral_query,
        {"ui_context": {"analysis_depth": "report"}},
    )

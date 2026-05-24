# -*- coding: utf-8 -*-
from backend.graph.nodes.planner import _enforce_policy
from backend.graph.nodes.planner_stub import planner_stub
from backend.graph.nodes.policy_gate import policy_gate


def _run_policy_and_planner(query: str, operation_name: str, tickers: list[str]) -> tuple[dict, dict]:
    state = {
        "query": query,
        "operation": {"name": operation_name, "confidence": 0.9, "params": {}},
        "output_mode": "brief",
        "subject": {
            "subject_type": "company",
            "tickers": tickers,
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
    }
    policy_out = policy_gate(state)
    state = {**state, **policy_out}
    plan_out = planner_stub(state)
    return policy_out, plan_out


def test_old_query_price_path_keeps_stock_price_step():
    policy_out, plan_out = _run_policy_and_planner("AAPL price", "price", ["AAPL"])
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_stock_price" in tools
    assert "get_stock_price" in step_names


def test_old_query_technical_path_keeps_technical_snapshot_step():
    policy_out, plan_out = _run_policy_and_planner("AAPL technical analysis", "technical", ["AAPL"])
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_technical_snapshot" in tools
    assert "get_technical_snapshot" in step_names


def test_technical_chat_path_runs_technical_agent_for_indicator_query():
    state = {
        "query": "NVDA technical analysis with RSI, MACD, support and resistance",
        "operation": {"name": "technical", "confidence": 0.9, "params": {}},
        "output_mode": "chat",
        "subject": {
            "subject_type": "company",
            "tickers": ["NVDA"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "subject_label": "NVDA",
                "tickers": ["NVDA"],
                "operation": {"name": "technical", "confidence": 0.9, "params": {}},
                "status": "ready",
            }
        ],
    }
    policy_out = policy_gate(state)
    state = {**state, **policy_out}
    plan_out = planner_stub(state)

    agents = set(((policy_out.get("policy") or {}).get("allowed_agents") or []))
    step_agents = [
        s.get("name")
        for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])
        if s.get("kind") == "agent"
    ]
    assert "technical_agent" in agents
    assert "technical_agent" in step_agents


def test_investment_opinion_chat_path_runs_core_agents_and_evidence_steps():
    state = {
        "query": "INTC 最近走势如何 看好么",
        "operation": {"name": "investment_opinion", "confidence": 0.86, "params": {}},
        "output_mode": "chat",
        "subject": {
            "subject_type": "company",
            "tickers": ["INTC"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "subject_label": "INTC",
                "tickers": ["INTC"],
                "operation": {"name": "investment_opinion", "confidence": 0.86, "params": {}},
                "status": "ready",
            }
        ],
    }
    policy_out = policy_gate(state)
    state = {**state, **policy_out}
    plan_out = planner_stub(state)

    agents = set(((policy_out.get("policy") or {}).get("allowed_agents") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    step_agents = [
        s.get("name")
        for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])
        if s.get("kind") == "agent"
    ]

    assert {"technical_agent", "fundamental_agent", "risk_agent"}.issubset(agents)
    assert "get_stock_price" in step_names
    assert "get_technical_snapshot" in step_names
    assert "get_company_news" in step_names
    assert "get_company_info" in step_names
    assert "technical_agent" in step_agents
    assert "fundamental_agent" in step_agents
    assert "risk_agent" in step_agents


def test_investment_opinion_query_matrix_routes_to_rich_chat_chain(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    positive_cases = [
        ("INTC 最近走势如何 看好么", "INTC"),
        ("NVDA 走势怎么看", "NVDA"),
        ("AAPL 值得买吗", "AAPL"),
        ("TSLA 后市怎么操作", "TSLA"),
        ("MSFT 短中期风险机会怎么看", "MSFT"),
        ("Should I buy AMD shares here?", "AMD"),
        ("What is your bullish or bearish view on NVDA?", "NVDA"),
        ("META 可以加仓吗", "META"),
    ]

    for query, ticker in positive_cases:
        state = {"query": query, "ui_context": {}, "output_mode": "chat"}
        import asyncio

        understanding = asyncio.run(understand_request(state))
        assert (understanding.get("operation") or {}).get("name") == "investment_opinion", query
        assert (understanding.get("subject") or {}).get("tickers") == [ticker], query

        policy_out = policy_gate({**state, **understanding})
        plan_out = planner_stub({**state, **understanding, **policy_out})
        agents = set(((policy_out.get("policy") or {}).get("allowed_agents") or []))
        step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
        step_agents = {
            s.get("name")
            for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])
            if s.get("kind") == "agent"
        }

        assert {"technical_agent", "fundamental_agent", "risk_agent"}.issubset(agents), query
        assert {"get_stock_price", "get_technical_snapshot", "get_company_news", "get_company_info"}.issubset(set(step_names)), query
        assert {"technical_agent", "fundamental_agent", "risk_agent"}.issubset(step_agents), query


def test_valuation_compare_uses_intent_contract_and_per_ticker_evidence(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    state = {"query": "NVDA 和 AMD 哪个估值更合理", "ui_context": {}, "output_mode": "chat"}
    import asyncio

    understanding = asyncio.run(understand_request(state))
    contract = understanding.get("intent_contract") or {}

    assert contract.get("facets") == ["valuation"]
    assert contract.get("per_ticker_required") is True
    assert (contract.get("render_intent") or {}).get("shape") == "compare"
    assert contract.get("required_evidence") == [
        "price_snapshot",
        "company_profile",
        "earnings_estimates",
    ]

    tasks = understanding.get("tasks") or []
    compare_tasks = [task for task in tasks if (task.get("operation") or {}).get("name") == "compare"]
    evidence_tasks = [task for task in tasks if (task.get("operation") or {}).get("name") == "investment_opinion"]
    assert len(compare_tasks) == 1
    assert (compare_tasks[0].get("operation") or {}).get("params", {}).get("synthesis_only") is True
    assert [task.get("tickers") for task in evidence_tasks] == [["NVDA"], ["AMD"]]
    assert all((task.get("operation") or {}).get("params", {}).get("evidence_focus") == "valuation" for task in evidence_tasks)

    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    agents = set(((policy_out.get("policy") or {}).get("allowed_agents") or []))
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    step_names = [step.get("name") for step in steps]
    agent_steps = [step for step in steps if step.get("kind") == "agent"]

    assert agents == set()
    assert "get_performance_comparison" not in step_names
    assert {"get_stock_price", "get_company_info", "get_earnings_estimates"}.issubset(set(step_names))
    assert "get_technical_snapshot" not in step_names
    assert agent_steps == []


def test_risk_evidence_planner_uses_positions_inputs(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    state = {
        "query": "Compare GOOGL and MSFT today: news, price change, and risk in one sentence each.",
        "ui_context": {},
        "output_mode": "chat",
    }
    import asyncio

    understanding = asyncio.run(understand_request(state))
    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    portfolio_risk_steps = [
        step
        for step in steps
        if step.get("name") in {"get_factor_exposure", "run_portfolio_stress_test"}
    ]

    assert portfolio_risk_steps
    assert all("positions" in (step.get("inputs") or {}) for step in portfolio_risk_steps)
    assert not any("ticker" in (step.get("inputs") or {}) for step in portfolio_risk_steps)


def test_valuation_compare_chat_ticker_limit_is_env_configurable(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")
    monkeypatch.setenv("FINSIGHT_CHAT_MULTI_TICKER_RESEARCH_LIMIT", "2")

    state = {"query": "NVDA AMD TSM MSFT 哪个估值更合理", "ui_context": {}, "output_mode": "chat"}
    import asyncio

    understanding = asyncio.run(understand_request(state))
    contract = understanding.get("intent_contract") or {}
    evidence_tasks = [
        task
        for task in (understanding.get("tasks") or [])
        if (task.get("operation") or {}).get("name") == "investment_opinion"
    ]

    assert contract.get("primary_tickers") == ["NVDA", "AMD"]
    assert contract.get("omitted_tickers") == ["TSM", "MSFT"]
    assert [task.get("tickers") for task in evidence_tasks] == [["NVDA"], ["AMD"]]


def test_external_entity_impact_contract_runs_news_and_risk_evidence(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    state = {"query": "研究一下特斯拉会不会被SpaceX影响", "ui_context": {}, "output_mode": "chat"}
    import asyncio

    understanding = asyncio.run(understand_request(state))
    contract = understanding.get("intent_contract") or {}
    task = (understanding.get("tasks") or [])[0]

    assert contract.get("facets") == ["external_entity_impact"]
    assert contract.get("budget_profile") == "external_entity_impact_light"
    assert (task.get("operation") or {}).get("name") == "analyze_impact"
    assert (task.get("operation") or {}).get("params", {}).get("required_evidence") == [
        "price_snapshot",
        "news_context",
        "risk_profile",
    ]

    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    agents = set(((policy_out.get("policy") or {}).get("allowed_agents") or []))
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    step_names = [step.get("name") for step in steps]
    step_agents = {step.get("name") for step in steps if step.get("kind") == "agent"}

    assert {"news_agent", "risk_agent"}.issubset(agents)
    assert {"get_stock_price", "get_company_news", "get_authoritative_media_news"}.issubset(set(step_names))
    assert {"analyze_historical_drawdowns", "get_factor_exposure", "run_portfolio_stress_test"}.issubset(set(step_names))
    assert not {"news_agent", "risk_agent"}.intersection(step_agents)
    assert step_names


def test_router_compare_hints_are_recompiled_to_valuation_contract(monkeypatch):
    import asyncio
    import importlib

    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert set(tickers) == {"NVDA", "AMD"}
        assert selection_ids == []
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="NVDA, AMD"),
            relation="compare",
            domain_intent="analysis",
            confidence=0.9,
            needs_tools=True,
            reason="router emitted coarse compare hints",
            task_hints=(
                {"subject_type": "company", "subject_label": "NVDA", "tickers": ["NVDA"], "operation": "compare", "params": {}},
                {"subject_type": "company", "subject_label": "AMD", "tickers": ["AMD"], "operation": "compare", "params": {}},
            ),
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    state = {"query": "NVDA 和 AMD 哪个估值更合理", "ui_context": {}, "output_mode": "chat", "trace": {}}
    understanding = asyncio.run(understand_mod.understand_request(state))
    contract = understanding.get("intent_contract") or {}
    tasks = understanding.get("tasks") or []

    assert contract.get("facets") == ["valuation"]
    assert contract.get("per_ticker_required") is True
    assert [task.get("reason") for task in tasks] == [
        "intent_contract_synthesis_compare",
        "intent_contract_per_ticker_evidence",
        "intent_contract_per_ticker_evidence",
    ]

    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    step_names = [step.get("name") for step in steps]

    assert steps
    assert "get_performance_comparison" not in step_names
    assert "fundamental_agent" not in step_names


def test_router_hint_operations_do_not_pollute_frame_contracts(monkeypatch):
    import asyncio
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
            reason="router task operation is only a weak signal",
            task_hints=(
                {"subject_type": "company", "subject_label": "AAPL", "tickers": ["AAPL"], "operation": "macro_brief", "params": {}},
                {"subject_type": "company", "subject_label": "MSFT", "tickers": ["MSFT"], "operation": "macro_brief", "params": {}},
                {"subject_type": "macro", "subject_label": "Fed rates", "tickers": [], "operation": "analyze_impact", "params": {}},
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
    tasks = understanding.get("tasks") or []
    task_ops = [(task.get("operation") or {}).get("name") for task in tasks]

    assert task_ops == ["price", "fetch", "macro_brief"]
    assert all(op != "compare" for op in task_ops)

    contracts = understanding.get("intent_contracts") or []
    by_frame = {contract.get("frame_id"): contract for contract in contracts}
    assert by_frame["router_hint_1"].get("required_evidence") == ["price_snapshot"]
    assert by_frame["router_hint_2"].get("required_evidence") == ["news_context"]
    assert by_frame["router_hint_3"].get("required_evidence") == ["macro_context"]

    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    step_names = [step.get("name") for step in ((plan_out.get("plan_ir") or {}).get("steps") or [])]

    assert "get_performance_comparison" not in step_names
    assert "get_stock_price" in step_names
    assert "get_company_news" in step_names
    assert "get_official_macro_releases" in step_names


def test_router_hint_uses_company_alias_frame_for_external_impact_contract(monkeypatch):
    import asyncio
    import importlib

    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    query = "\u5fae\u8f6f AI \u5bf9\u5e02\u503c\u6709\u4ec0\u4e48\u5f71\u54cd"

    async def fake_route(_state, *, tickers, selection_ids):
        assert set(tickers) == {"MSFT"}
        assert selection_ids == []
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="MSFT"),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.9,
            needs_tools=True,
            reason="router emitted coarse qa hint for company alias query",
            task_hints=(
                {"subject_type": "company", "subject_label": "MSFT", "tickers": ["MSFT"], "operation": "qa", "params": {}},
            ),
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    state = {"query": query, "ui_context": {}, "output_mode": "chat", "trace": {}}
    understanding = asyncio.run(understand_mod.understand_request(state))
    contract = understanding.get("intent_contract") or {}
    task = (understanding.get("tasks") or [])[0]

    assert contract.get("facets") == ["external_entity_impact"]
    assert contract.get("budget_profile") == "external_entity_impact_light"
    assert (task.get("operation") or {}).get("name") == "analyze_impact"
    assert (task.get("operation") or {}).get("params", {}).get("required_evidence") == [
        "price_snapshot",
        "news_context",
        "risk_profile",
    ]

    policy_out = policy_gate({**state, **understanding})
    plan_out = planner_stub({**state, **understanding, **policy_out})
    step_names = [step.get("name") for step in ((plan_out.get("plan_ir") or {}).get("steps") or [])]

    assert "get_stock_price" in step_names
    assert "get_company_news" in step_names
    assert "get_authoritative_media_news" in step_names
    assert "news_agent" not in step_names
    assert "risk_agent" not in step_names


def test_earnings_performance_query_routes_to_fundamental_chain(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    cases = [
        ("英伟达最新季度财报表现如何", "NVDA"),
        ("NVDA latest quarterly earnings performance", "NVDA"),
        ("AAPL 最新财报怎么样", "AAPL"),
        ("MSFT revenue EPS margin 这个季度如何", "MSFT"),
    ]

    for query, ticker in cases:
        state = {"query": query, "ui_context": {}, "output_mode": "chat"}
        import asyncio

        understanding = asyncio.run(understand_request(state))
        assert (understanding.get("operation") or {}).get("name") == "earnings_performance", query
        assert (understanding.get("subject") or {}).get("tickers") == [ticker], query

        policy_out = policy_gate({**state, **understanding})
        plan_out = planner_stub({**state, **understanding, **policy_out})
        agents = set(((policy_out.get("policy") or {}).get("allowed_agents") or []))
        step_names = {
            s.get("name")
            for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])
        }
        step_agents = {
            s.get("name")
            for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])
            if s.get("kind") == "agent"
        }

        assert {"fundamental_agent", "news_agent"}.issubset(agents), query
        assert {
            "get_company_info",
            "get_sec_company_facts_quarterly",
            "get_earnings_estimates",
            "get_eps_revisions",
            "get_company_news",
        }.issubset(step_names), query
        assert "fundamental_agent" in step_agents, query
        assert "get_stock_price" not in step_names, query


def test_earnings_price_impact_query_routes_to_composite_chain(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    cases = [
        ("请问英伟达这个季度财报对股价的影响", "NVDA"),
        ("NVDA earnings impact on stock price", "NVDA"),
        ("AAPL 财报出来后对走势是利好还是利空", "AAPL"),
    ]

    for query, ticker in cases:
        state = {"query": query, "ui_context": {}, "output_mode": "chat"}
        import asyncio

        understanding = asyncio.run(understand_request(state))
        assert (understanding.get("operation") or {}).get("name") == "earnings_impact", query
        assert (understanding.get("subject") or {}).get("tickers") == [ticker], query

        policy_out = policy_gate({**state, **understanding})
        plan_out = planner_stub({**state, **understanding, **policy_out})
        agents = set(((policy_out.get("policy") or {}).get("allowed_agents") or []))
        step_names = {
            s.get("name")
            for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])
        }
        step_agents = {
            s.get("name")
            for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])
            if s.get("kind") == "agent"
        }

        assert {"fundamental_agent", "news_agent", "risk_agent"}.issubset(agents), query
        assert {
            "get_stock_price",
            "get_company_info",
            "get_sec_company_facts_quarterly",
            "get_earnings_estimates",
            "get_eps_revisions",
            "get_company_news",
        }.issubset(step_names), query
        assert {"fundamental_agent", "news_agent", "risk_agent"}.issubset(step_agents), query


def test_earnings_price_impact_agents_run_in_one_serial_block():
    from backend.graph.executor import group_steps_by_parallel_group

    state = {
        "query": "请问英伟达这个季度财报对股价的影响",
        "operation": {"name": "earnings_impact", "confidence": 0.86, "params": {}},
        "output_mode": "chat",
        "subject": {
            "subject_type": "company",
            "tickers": ["NVDA"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "subject_label": "NVDA",
                "tickers": ["NVDA"],
                "operation": {"name": "earnings_impact", "confidence": 0.86, "params": {}},
                "status": "ready",
            }
        ],
    }

    policy_out = policy_gate(state)
    plan_out = planner_stub({**state, **policy_out})
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    serial_groups = group_steps_by_parallel_group(steps)
    agent_groups = [
        {step.get("name") for step in group if step.get("kind") == "agent"}
        for group in serial_groups
        if any(step.get("kind") == "agent" for step in group)
    ]

    assert agent_groups == [{"fundamental_agent", "news_agent", "risk_agent"}]


def test_earnings_price_impact_query_expands_tools_even_if_upstream_says_price():
    state = {
        "query": "请问英伟达这个季度财报对股价的影响",
        "operation": {"name": "price", "confidence": 0.9, "params": {}},
        "output_mode": "chat",
        "subject": {
            "subject_type": "company",
            "tickers": ["NVDA"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "subject_label": "NVDA",
                "tickers": ["NVDA"],
                "operation": {"name": "price", "confidence": 0.9, "params": {}},
                "status": "ready",
            }
        ],
    }

    policy_out = policy_gate(state)
    state = {**state, **policy_out}
    plan_out = planner_stub(state)

    agents = set(((policy_out.get("policy") or {}).get("allowed_agents") or []))
    step_names = {
        s.get("name")
        for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])
    }
    step_agents = {
        s.get("name")
        for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])
        if s.get("kind") == "agent"
    }

    assert {"fundamental_agent", "news_agent", "risk_agent"}.issubset(agents)
    assert {
        "get_stock_price",
        "get_sec_company_facts_quarterly",
        "get_earnings_estimates",
        "get_eps_revisions",
        "get_company_news",
    }.issubset(step_names)
    assert {"fundamental_agent", "news_agent", "risk_agent"}.issubset(step_agents)


def test_non_opinion_queries_keep_narrow_tool_chains(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    cases = [
        ("AAPL 最新新闻有哪些", "fetch", {"get_company_news"}, {"technical_agent", "fundamental_agent", "risk_agent"}),
        ("NVDA 当前价格是多少", "price", {"get_stock_price"}, {"technical_agent", "fundamental_agent", "risk_agent", "news_agent"}),
        ("美联储利率路径对科技股估值有什么影响", "analyze_impact", {"get_official_macro_releases"}, {"technical_agent", "fundamental_agent", "risk_agent"}),
    ]

    for query, expected_op, required_tools, disallowed_agents in cases:
        state = {"query": query, "ui_context": {}, "output_mode": "chat"}
        import asyncio

        understanding = asyncio.run(understand_request(state))
        assert (understanding.get("operation") or {}).get("name") == expected_op, query
        policy_out = policy_gate({**state, **understanding})
        plan_out = planner_stub({**state, **understanding, **policy_out})
        agents = set(((policy_out.get("policy") or {}).get("allowed_agents") or []))
        step_names = {s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])}
        step_agents = {
            s.get("name")
            for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])
            if s.get("kind") == "agent"
        }

        assert required_tools.issubset(step_names), query
        assert disallowed_agents.isdisjoint(agents), query
        assert disallowed_agents.isdisjoint(step_agents), query


def test_old_query_compare_path_keeps_comparison_step():
    policy_out, plan_out = _run_policy_and_planner("AAPL vs MSFT", "compare", ["AAPL", "MSFT"])
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_performance_comparison" in tools
    assert "get_performance_comparison" in step_names


def test_old_query_fetch_path_keeps_company_news_step():
    policy_out, plan_out = _run_policy_and_planner("latest AAPL news", "fetch", ["AAPL"])
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_company_news" in tools
    assert "get_company_news" in step_names


def test_new_query_fundamental_tools_are_allowlisted():
    policy_out, plan_out = _run_policy_and_planner("AAPL EPS revisions and earnings estimates", "qa", ["AAPL"])
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_earnings_estimates" in tools
    assert "get_eps_revisions" in tools
    assert "get_earnings_estimates" in step_names
    assert "get_eps_revisions" in step_names


def test_new_query_options_tool_is_allowlisted():
    policy_out, plan_out = _run_policy_and_planner("AAPL option IV PCR skew", "technical", ["AAPL"])
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_option_chain_metrics" in tools
    assert "get_option_chain_metrics" in step_names


def test_new_query_risk_tools_are_allowlisted():
    policy_out, plan_out = _run_policy_and_planner("AAPL factor exposure and stress test", "qa", ["AAPL"])
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_factor_exposure" in tools
    assert "run_portfolio_stress_test" in tools
    assert "get_factor_exposure" in step_names
    assert "run_portfolio_stress_test" in step_names


def test_new_query_news_tools_are_allowlisted():
    policy_out, plan_out = _run_policy_and_planner(
        "AAPL earnings/dividend calendar and source reliability",
        "qa",
        ["AAPL"],
    )
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_event_calendar" in tools
    assert "score_news_source_reliability" in tools
    assert "get_event_calendar" in step_names
    assert "score_news_source_reliability" in step_names


def test_manifest_market_filter_cn_excludes_us_only_tools():
    state = {
        "query": "AAPL earnings estimates",
        "operation": {"name": "qa", "confidence": 0.9, "params": {}},
        "output_mode": "brief",
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "ui_context": {"market": "CN"},
    }
    policy_out = policy_gate(state)
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    assert "get_earnings_estimates" not in tools
    assert "get_eps_revisions" not in tools


def test_new_query_sec_tools_are_allowlisted():
    policy_out, plan_out = _run_policy_and_planner(
        "AAPL latest sec filings and item 1a risk factors",
        "qa",
        ["AAPL"],
    )
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_sec_filings" in tools
    assert "get_sec_company_facts_quarterly" in tools
    assert "get_sec_risk_factors" in tools
    assert "get_sec_filings" in step_names
    assert "get_sec_risk_factors" in step_names


def test_new_query_sec_tools_blocked_under_cn_market():
    state = {
        "query": "AAPL sec filing history",
        "operation": {"name": "qa", "confidence": 0.9, "params": {}},
        "output_mode": "brief",
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "ui_context": {"market": "CN"},
    }
    policy_out = policy_gate(state)
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    assert "get_sec_filings" not in tools
    assert "get_sec_material_events" not in tools
    assert "get_sec_risk_factors" not in tools


def test_dashboard_report_path_keeps_core_six_agents_in_stub_plan():
    state = {
        "query": "生成 AAPL 一键综合研报",
        "operation": {"name": "generate_report", "confidence": 0.95, "params": {}},
        "output_mode": "investment_report",
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "ui_context": {"source": "dashboard_research_tab"},
    }
    policy_out = policy_gate(state)
    state = {**state, **policy_out}
    plan_out = planner_stub(state)

    allowed_agents = (policy_out.get("policy") or {}).get("allowed_agents") or []
    step_agents = [
        s.get("name")
        for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])
        if s.get("kind") == "agent"
    ]

    assert allowed_agents == [
        "price_agent",
        "news_agent",
        "fundamental_agent",
        "technical_agent",
        "macro_agent",
        "risk_agent",
    ]
    assert step_agents == [
        "price_agent",
        "news_agent",
        "fundamental_agent",
        "technical_agent",
        "macro_agent",
        "risk_agent",
    ]


def test_investment_report_us_auto_adds_sec_steps():
    state = {
        "query": "Generate AAPL investment report with filing evidence",
        "operation": {"name": "generate_report", "confidence": 0.95, "params": {}},
        "output_mode": "investment_report",
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "ui_context": {"market": "US"},
    }
    policy_out = policy_gate(state)
    state = {**state, **policy_out}
    plan_out = planner_stub(state)

    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_sec_filings" in tools
    assert "get_sec_company_facts_quarterly" in tools
    assert "get_sec_material_events" in tools
    assert "get_authoritative_media_news" in tools
    assert "get_earnings_call_transcripts" in tools
    assert "get_sec_filings" in step_names
    assert "get_sec_company_facts_quarterly" in step_names
    assert "get_sec_material_events" in step_names
    assert "get_authoritative_media_news" in step_names
    assert "get_earnings_call_transcripts" in step_names


def test_investment_report_understanding_task_path_keeps_filings_transcripts_and_agents():
    state = {
        "query": "Generate INTC deep report with filing document longform, 10-K, 10-Q, transcript and authoritative media evidence",
        "operation": {"name": "analyze_impact", "confidence": 0.78, "params": {}},
        "output_mode": "investment_report",
        "subject": {
            "subject_type": "company",
            "tickers": ["INTC"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "subject_label": "INTC",
                "tickers": ["INTC"],
                "operation": {"name": "analyze_impact", "confidence": 0.78, "params": {}},
                "status": "ready",
            }
        ],
        "ui_context": {"market": "US"},
    }
    policy_out = policy_gate(state)
    state = {**state, **policy_out}
    plan_out = planner_stub(state)

    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    step_agents = [
        s.get("name")
        for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])
        if s.get("kind") == "agent"
    ]
    assert "get_sec_filings" in step_names
    assert "get_sec_company_facts_quarterly" in step_names
    assert "get_authoritative_media_news" in step_names
    assert "get_earnings_call_transcripts" in step_names
    assert "fundamental_agent" in step_agents
    assert "technical_agent" in step_agents
    assert "deep_search_agent" in step_agents


def test_chinese_primary_report_with_peer_context_runs_deep_search_on_primary_ticker_only():
    query = (
        "请给我一份 INTC 英特尔深度投资报告，覆盖最新财报、Arrow Lake、"
        "NVIDIA/AMD/TSMC 竞争、分析师评级、估值和未来6-12个月风险机会。"
    )
    state = {
        "query": query,
        "operation": {
            "name": "analyze_impact",
            "confidence": 0.78,
            "params": {
                "peer_tickers": ["AMD", "TSM", "NVDA"],
                "comparison_context": "covered_as_competitive_context",
            },
        },
        "output_mode": "investment_report",
        "subject": {
            "subject_type": "company",
            "tickers": ["INTC"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "subject_label": "INTC",
                "tickers": ["INTC"],
                "operation": {
                    "name": "analyze_impact",
                    "confidence": 0.78,
                    "params": {
                        "peer_tickers": ["AMD", "TSM", "NVDA"],
                        "comparison_context": "covered_as_competitive_context",
                    },
                },
                "status": "ready",
            }
        ],
        "ui_context": {"market": "US"},
    }
    policy_out = policy_gate(state)
    state = {**state, **policy_out}
    plan_out = planner_stub(state)

    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    step_names = [s.get("name") for s in steps]
    agent_inputs = {
        s.get("name"): s.get("inputs") or {}
        for s in steps
        if s.get("kind") == "agent"
    }
    tool_tickers = [
        (s.get("inputs") or {}).get("ticker")
        for s in steps
        if s.get("kind") == "tool" and (s.get("inputs") or {}).get("ticker")
    ]

    assert "get_sec_filings" in step_names
    assert "get_earnings_call_transcripts" in step_names
    assert "deep_search_agent" in agent_inputs
    assert agent_inputs["deep_search_agent"]["ticker"] == "INTC"
    assert "Arrow Lake" in agent_inputs["deep_search_agent"]["query"]
    assert set(tool_tickers) == {"INTC"}


def test_investment_report_non_us_market_does_not_add_sec_steps():
    state = {
        "query": "Generate 600519 investment report with filing evidence",
        "operation": {"name": "generate_report", "confidence": 0.95, "params": {}},
        "output_mode": "investment_report",
        "subject": {
            "subject_type": "company",
            "tickers": ["600519.SS"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "ui_context": {"market": "CN"},
    }
    policy_out = policy_gate(state)
    state = {**state, **policy_out}
    plan_out = planner_stub(state)

    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    step_names = [s.get("name") for s in ((plan_out.get("plan_ir") or {}).get("steps") or [])]
    assert "get_sec_filings" not in tools
    assert "get_sec_material_events" not in tools
    assert "get_local_market_filings" in tools
    assert "get_sec_filings" not in step_names
    assert "get_sec_material_events" not in step_names
    assert "get_local_market_filings" in step_names


def test_policy_infers_cn_market_from_ticker_suffix_when_ui_context_absent():
    state = {
        "query": "Generate 600519.SS deep investment report",
        "operation": {"name": "generate_report", "confidence": 0.95, "params": {}},
        "output_mode": "investment_report",
        "subject": {
            "subject_type": "company",
            "tickers": ["600519.SS"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
    }
    policy_out = policy_gate(state)
    tools = set(((policy_out.get("policy") or {}).get("allowed_tools") or []))
    assert "get_local_market_filings" in tools
    assert "get_sec_filings" not in tools


def test_planner_enforce_policy_keeps_authoritative_and_transcript_tools_under_report_budget():
    state = {
        "query": "Generate AAPL deep report with filing transcript and authoritative media evidence",
        "operation": {"name": "generate_report", "confidence": 0.95, "params": {}},
        "output_mode": "investment_report",
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "ui_context": {"market": "US"},
    }
    policy_out = policy_gate(state)
    state = {**state, **policy_out}
    # Force a constrained budget to reproduce the historical clipping issue.
    state["policy"]["budget"] = {"max_rounds": 6, "max_tools": 8}
    state["policy"]["allowed_agents"] = [
        "price_agent",
        "news_agent",
        "fundamental_agent",
        "technical_agent",
        "macro_agent",
        "deep_search_agent",
    ]

    plan_payload = {"summary": "test", "steps": []}
    final_plan, _ = _enforce_policy(plan_payload, state)
    step_names = [s.get("name") for s in (final_plan.get("steps") or []) if isinstance(s, dict)]

    assert "get_authoritative_media_news" in step_names
    assert "get_earnings_call_transcripts" in step_names

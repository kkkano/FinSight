# -*- coding: utf-8 -*-
import asyncio


def _run(coro):
    return asyncio.run(coro)


def _ops_by_ticker(result: dict) -> set[tuple[tuple[str, ...], str]]:
    rows: set[tuple[tuple[str, ...], str]] = set()
    for task in result.get("tasks") or []:
        rows.add((tuple(task.get("tickers") or []), (task.get("operation") or {}).get("name")))
    return rows


def test_multiticker_valuation_rank_expands_per_ticker_evidence_tasks(monkeypatch):
    from backend.graph.nodes.planner_stub import planner_stub
    from backend.graph.nodes.policy_gate import policy_gate
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    state = {"query": "NVDA 和 AMD 哪个估值更合理", "ui_context": {}, "output_mode": "chat"}
    understanding = _run(understand_request(state))

    v2 = understanding.get("understanding_v2") or {}
    assert v2.get("schema_version") == "understanding.v2"
    facet_names = {facet.get("name") for facet in v2.get("facets") or []}
    assert facet_names >= {"valuation", "fundamental"}
    assert "risk" not in facet_names
    assert (v2.get("evidence_requirements") or [])[0].get("profile") == "valuation_compare_light"
    assert any(
        relation.get("type") in {"compare", "rank"}
        and set(relation.get("subject_ids") or []) >= {"subj_nvda", "subj_amd"}
        and "valuation" in (relation.get("facet_refs") or [])
        for relation in v2.get("relations") or []
    )

    ops = _ops_by_ticker(understanding)
    assert (("NVDA", "AMD"), "compare") in ops
    assert (("NVDA",), "investment_opinion") in ops
    assert (("AMD",), "investment_opinion") in ops
    compare_tasks = [
        task for task in understanding.get("tasks") or []
        if (task.get("operation") or {}).get("name") == "compare"
    ]
    evidence_tasks = [
        task for task in understanding.get("tasks") or []
        if (task.get("operation") or {}).get("name") == "investment_opinion"
    ]
    compare_params = ((compare_tasks[0].get("operation") or {}).get("params") or {})
    assert compare_params.get("synthesis_only") is True
    assert compare_params.get("comparison_data_profile") == "valuation_compare_light"
    assert all(
        ((task.get("operation") or {}).get("params") or {}).get("evidence_focus") == "valuation"
        for task in evidence_tasks
    )

    policy_out = policy_gate({**state, **understanding})
    gated = {**state, **understanding, **policy_out}
    plan = planner_stub(gated)["plan_ir"]
    agents = set((policy_out.get("policy") or {}).get("allowed_agents") or [])
    step_names = [step.get("name") for step in plan.get("steps") or []]
    agent_steps = [step.get("name") for step in plan.get("steps") or [] if step.get("kind") == "agent"]
    assert agents == set()
    assert "get_performance_comparison" not in step_names
    assert {"get_company_info", "get_earnings_estimates"}.issubset(set(step_names))
    assert "get_technical_snapshot" not in step_names
    assert "get_company_news" not in step_names
    assert "risk_agent" not in step_names
    assert agent_steps == []


def test_multiticker_technical_rank_expands_per_ticker_technical_tasks(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    result = _run(
        understand_request(
            {
                "query": "GOOGL 和 MSFT 哪个技术面更强",
                "ui_context": {},
                "output_mode": "chat",
            }
        )
    )

    v2 = result.get("understanding_v2") or {}
    assert {facet.get("name") for facet in v2.get("facets") or []} >= {"technical", "price"}
    assert any((relation.get("type") or "") == "rank" for relation in v2.get("relations") or [])

    ops = _ops_by_ticker(result)
    assert (("GOOGL", "MSFT"), "compare") in ops
    assert (("GOOGL",), "technical") in ops
    assert (("MSFT",), "technical") in ops


def test_policy_and_planner_can_read_v2_when_legacy_tasks_are_absent(monkeypatch):
    from backend.graph.nodes.planner_stub import planner_stub
    from backend.graph.nodes.policy_gate import policy_gate
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")

    state = {"query": "NVDA 和 AMD 哪个估值更合理", "ui_context": {}, "output_mode": "chat"}
    understanding = _run(understand_request(state))
    v2_only_state = {
        **state,
        "subject": understanding["subject"],
        "operation": understanding["operation"],
        "reply_contract": understanding["reply_contract"],
        "understanding_v2": understanding["understanding_v2"],
        "tasks": None,
    }

    policy = policy_gate(v2_only_state)["policy"]
    plan = planner_stub({**v2_only_state, "policy": policy})["plan_ir"]

    assert set(policy.get("allowed_agents") or []) == set()
    step_names = [step.get("name") for step in plan.get("steps") or []]
    assert "get_performance_comparison" not in step_names
    assert {"get_stock_price", "get_company_info", "get_earnings_estimates"}.issubset(
        set(step_names)
    )
    assert "fundamental_agent" not in step_names
    assert "get_technical_snapshot" not in step_names
    assert "get_company_news" not in step_names
    assert "risk_agent" not in step_names


def test_valuation_compare_chat_ticker_limit_is_env_configurable(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")
    monkeypatch.setenv("FINSIGHT_CHAT_MULTI_TICKER_RESEARCH_LIMIT", "2")

    result = _run(
        understand_request(
            {
                "query": "NVDA AMD TSM MSFT which valuation is more reasonable",
                "ui_context": {},
                "output_mode": "chat",
            }
        )
    )

    v2 = result.get("understanding_v2") or {}
    assert (v2.get("scope") or {}).get("primary_tickers") == ["NVDA", "AMD"]
    assert (v2.get("scope") or {}).get("omitted_tickers") == ["TSM", "MSFT"]

    compare_tasks = [
        task for task in result.get("tasks") or []
        if (task.get("operation") or {}).get("name") == "compare"
    ]
    evidence_tasks = [
        task for task in result.get("tasks") or []
        if (task.get("operation") or {}).get("name") == "investment_opinion"
    ]
    assert [task.get("tickers") for task in compare_tasks] == [["NVDA", "AMD"]]
    assert [task.get("tickers") for task in evidence_tasks] == [["NVDA"], ["AMD"]]
    params = ((compare_tasks[0].get("operation") or {}).get("params") or {})
    assert params.get("research_ticker_limit") == 2
    assert params.get("omitted_tickers") == ["TSM", "MSFT"]


def test_understanding_v2_can_be_disabled(monkeypatch):
    from backend.graph.nodes.understand_request import understand_request

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "false")
    monkeypatch.setenv("FINSIGHT_UNDERSTANDING_V2_MODE", "off")

    result = _run(
        understand_request(
            {
                "query": "NVDA 和 AMD 哪个估值更合理",
                "ui_context": {},
                "output_mode": "chat",
            }
        )
    )

    assert result.get("understanding_v2") == {}
    assert "v2" not in (result.get("understanding") or {})

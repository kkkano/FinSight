# -*- coding: utf-8 -*-
"""understanding_v2 影子路径契约测试。

WP2-T4 已把 FINSIGHT_UNDERSTANDING_V2_MODE 默认冻结为 off；
本文件测的是 shadow 模式下的产出契约，因此各测试显式开启 shadow。
默认 off 行为由 test_understanding_v2_can_be_disabled 守护。
"""
import asyncio


def _run(coro):
    return asyncio.run(coro)


def _enable_v2_shadow(monkeypatch):
    monkeypatch.setenv("FINSIGHT_UNDERSTANDING_V2_MODE", "shadow")


def _ops_by_ticker(result: dict) -> set[tuple[tuple[str, ...], str]]:
    rows: set[tuple[tuple[str, ...], str]] = set()
    for task in result.get("tasks") or []:
        rows.add((tuple(task.get("tickers") or []), (task.get("operation") or {}).get("name")))
    return rows


def test_multiticker_valuation_rank_uses_one_contract_with_per_ticker_evidence(monkeypatch):
    from backend.graph.planning.rule_planner import rule_based_planner as planner_stub
    from backend.graph.nodes.policy_gate import policy_gate
    from backend.graph.nodes.route_request import route_request

    _enable_v2_shadow(monkeypatch)

    state = {"query": "NVDA 和 AMD 哪个估值更合理", "ui_context": {}, "output_mode": "chat"}
    understanding = _run(route_request(state))

    v2 = understanding.get("understanding_v2") or {}
    assert v2.get("schema_version") == "understanding.v2"
    facet_names = {facet.get("name") for facet in v2.get("facets") or []}
    assert facet_names == {"valuation"}
    assert "risk" not in facet_names
    assert (v2.get("evidence_requirements") or [])[0].get("profile") == "semantic_requirements"
    assert any(
        relation.get("type") in {"compare", "rank"}
        and set(relation.get("subject_ids") or []) >= {"subj_nvda", "subj_amd"}
        and "valuation" in (relation.get("facet_refs") or [])
        for relation in v2.get("relations") or []
    )

    ops = _ops_by_ticker(understanding)
    assert (("NVDA", "AMD"), "compare") in ops
    assert len(ops) == 1
    compare_tasks = [
        task for task in understanding.get("tasks") or []
        if (task.get("operation") or {}).get("name") == "compare"
    ]
    compare_params = ((compare_tasks[0].get("operation") or {}).get("params") or {})
    assert compare_params.get("synthesis_only") is True
    assert compare_params.get("data_profile") == "research_synthesis"
    assert v2['tasks'][0]['answer_requirements'] == understanding['tasks'][0]['answer_requirements']

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
    assert {step['inputs']['ticker'] for step in plan['steps'] if step['name'] == 'get_company_info'} == {'NVDA', 'AMD'}


def test_multiticker_technical_rank_keeps_original_contract_in_v2(monkeypatch):
    from backend.graph.nodes.route_request import route_request

    _enable_v2_shadow(monkeypatch)

    result = _run(
        route_request(
            {
                "query": "GOOGL 和 MSFT 哪个技术面更强",
                "ui_context": {},
                "output_mode": "chat",
            }
        )
    )

    v2 = result.get("understanding_v2") or {}
    assert {facet.get("name") for facet in v2.get("facets") or []} == {"technical"}
    assert any((relation.get("type") or "") == "rank" for relation in v2.get("relations") or [])

    ops = _ops_by_ticker(result)
    assert (("GOOGL", "MSFT"), "compare") in ops
    assert len(ops) == 1
    assert v2['tasks'][0]['answer_requirements'] == result['tasks'][0]['answer_requirements']


def test_policy_and_planner_can_read_v2_when_legacy_tasks_are_absent(monkeypatch):
    from backend.graph.planning.rule_planner import rule_based_planner as planner_stub
    from backend.graph.nodes.policy_gate import policy_gate
    from backend.graph.nodes.route_request import route_request

    _enable_v2_shadow(monkeypatch)

    state = {"query": "NVDA 和 AMD 哪个估值更合理", "ui_context": {}, "output_mode": "chat"}
    understanding = _run(route_request(state))
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


def test_execution_ticker_limit_cannot_remove_requested_subjects_from_denominator(monkeypatch):
    from backend.graph.nodes.route_request import route_request

    _enable_v2_shadow(monkeypatch)
    monkeypatch.setenv("FINSIGHT_CHAT_MULTI_TICKER_RESEARCH_LIMIT", "2")

    result = _run(
        route_request(
            {
                "query": "NVDA AMD TSM MSFT which valuation is more reasonable",
                "ui_context": {},
                "output_mode": "chat",
            }
        )
    )

    v2 = result.get("understanding_v2") or {}
    assert (v2.get("scope") or {}).get("primary_tickers") == ["NVDA", "AMD", "TSM", "MSFT"]
    assert (v2.get("scope") or {}).get("omitted_tickers") == []
    assert (v2.get("scope") or {}).get('max_chat_research_tickers') == 2

    compare_tasks = [
        task for task in result.get("tasks") or []
        if (task.get("operation") or {}).get("name") == "compare"
    ]
    evidence_tasks = [
        task for task in result.get("tasks") or []
        if (task.get("operation") or {}).get("name") == "investment_opinion"
    ]
    assert [task.get("tickers") for task in compare_tasks] == [["NVDA", "AMD", "TSM", "MSFT"]]
    assert evidence_tasks == []
    params = ((compare_tasks[0].get("operation") or {}).get("params") or {})
    assert params.get("budget_profile") == 'semantic_requirements'
    assert result['understanding']['semantic_contract']['tasks'][0]['tickers'] == ["NVDA", "AMD", "TSM", "MSFT"]


def test_understanding_v2_can_be_disabled(monkeypatch):
    from backend.graph.nodes.route_request import route_request

    monkeypatch.setenv("FINSIGHT_UNDERSTANDING_V2_MODE", "off")

    result = _run(
        route_request(
            {
                "query": "NVDA 和 AMD 哪个估值更合理",
                "ui_context": {},
                "output_mode": "chat",
            }
        )
    )

    assert result.get("understanding_v2") == {}
    assert "v2" not in (result.get("understanding") or {})

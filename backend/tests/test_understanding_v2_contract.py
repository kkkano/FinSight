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
    assert {facet.get("name") for facet in v2.get("facets") or []} >= {"valuation", "fundamental", "risk"}
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

    gated = {**state, **understanding, **policy_gate({**state, **understanding})}
    plan = planner_stub(gated)["plan_ir"]
    step_names = [step.get("name") for step in plan.get("steps") or []]
    assert "get_performance_comparison" not in step_names
    assert {"get_company_info", "get_earnings_estimates"}.issubset(set(step_names))
    assert "fundamental_agent" in step_names


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

    assert {"fundamental_agent", "risk_agent"}.issubset(set(policy.get("allowed_agents") or []))
    assert "fundamental_agent" in [step.get("name") for step in plan.get("steps") or []]


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

# -*- coding: utf-8 -*-
import asyncio

from backend.graph.nodes.planner_stub import planner_stub
from backend.graph.nodes.policy_gate import policy_gate
from backend.graph.nodes.understand_request import understand_request


HOLDINGS_TOOLS = {
    "get_institutional_holdings",
    "get_institution_holdings_by_ticker",
    "get_insider_transactions",
    "get_holdings_overlap",
}


def _run(coro):
    return asyncio.run(coro)


def _understand(query: str, *, ui_context: dict | None = None) -> dict:
    return _run(
        understand_request(
            {
                "query": query,
                "output_mode": "brief",
                "ui_context": ui_context or {},
                "trace": {},
            }
        )
    )


def _step_names(plan_out: dict) -> list[str]:
    return [step.get("name") for step in ((plan_out.get("plan_ir") or {}).get("steps") or [])]


def _run_policy_and_plan(state: dict) -> tuple[dict, dict]:
    policy_out = policy_gate(state)
    planned_state = {**state, **policy_out}
    return policy_out, planner_stub(planned_state)


def test_buffett_portfolio_overlap_understanding_uses_holdings_task():
    result = _understand("巴菲特最近持仓变化和我的 NVDA/AAPL 组合有什么重叠？")

    assert (result.get("subject") or {}).get("subject_type") == "portfolio"
    assert (result.get("operation") or {}).get("name") == "holdings"
    assert result.get("blocked_tasks") == []

    tasks = result.get("tasks") or []
    assert len(tasks) == 1
    task = tasks[0]
    assert task.get("subject_type") == "portfolio"
    assert task.get("tickers") == ["NVDA", "AAPL"]
    assert (task.get("operation") or {}).get("name") == "holdings"
    assert (task.get("params") or {}).get("holder_cik_or_name") == "Berkshire Hathaway"


def test_company_insider_transactions_understanding_uses_holdings_task():
    result = _understand("AAPL 最近 insider 买卖有没有异常？")

    assert (result.get("subject") or {}).get("subject_type") == "company"
    assert (result.get("operation") or {}).get("name") == "holdings"

    tasks = result.get("tasks") or []
    assert len(tasks) == 1
    assert tasks[0].get("tickers") == ["AAPL"]
    assert (tasks[0].get("operation") or {}).get("name") == "holdings"


def test_institutional_adds_understanding_uses_holdings_task():
    result = _understand("哪些机构最近加仓了 MSFT？")

    assert (result.get("subject") or {}).get("subject_type") == "company"
    assert (result.get("operation") or {}).get("name") == "holdings"

    tasks = result.get("tasks") or []
    assert len(tasks) == 1
    assert tasks[0].get("tickers") == ["MSFT"]
    assert (tasks[0].get("operation") or {}).get("name") == "holdings"


def test_private_insider_information_is_not_form4_holdings(monkeypatch):
    result = _understand("AAPL insider information")

    assert (result.get("operation") or {}).get("name") != "holdings"
    assert not any((task.get("operation") or {}).get("name") == "holdings" for task in result.get("tasks") or [])

    monkeypatch.setenv("SEC_HOLDINGS_ENABLED", "true")
    state = {
        "query": "AAPL insider information",
        "output_mode": "brief",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "operation": {"name": "qa", "confidence": 0.6, "params": {}},
    }
    _, plan_out = _run_policy_and_plan(state)
    assert "get_insider_transactions" not in _step_names(plan_out)


def test_policy_gate_holdings_tools_are_us_only():
    base_state = {
        "query": "巴菲特最近持仓变化和我的 NVDA/AAPL 组合有什么重叠？",
        "output_mode": "brief",
        "subject": {"subject_type": "portfolio", "tickers": ["NVDA", "AAPL"]},
        "operation": {"name": "holdings", "confidence": 0.84, "params": {}},
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "portfolio",
                "tickers": ["NVDA", "AAPL"],
                "operation": {"name": "holdings", "confidence": 0.84, "params": {}},
                "status": "ready",
            }
        ],
    }

    us_tools = set((policy_gate({**base_state, "ui_context": {"market": "US"}}).get("policy") or {}).get("allowed_tools") or [])
    cn_tools = set((policy_gate({**base_state, "ui_context": {"market": "CN"}}).get("policy") or {}).get("allowed_tools") or [])
    hk_tools = set((policy_gate({**base_state, "ui_context": {"market": "HK"}}).get("policy") or {}).get("allowed_tools") or [])

    assert HOLDINGS_TOOLS.issubset(us_tools)
    assert HOLDINGS_TOOLS.isdisjoint(cn_tools)
    assert HOLDINGS_TOOLS.isdisjoint(hk_tools)


def test_planner_stub_emits_portfolio_overlap_step_when_sec_holdings_enabled(monkeypatch):
    monkeypatch.setenv("SEC_HOLDINGS_ENABLED", "true")
    query = "巴菲特最近持仓变化和我的 NVDA/AAPL 组合有什么重叠？"
    understood = _understand(query)
    state = {
        "query": query,
        "output_mode": "brief",
        "subject": understood["subject"],
        "operation": understood["operation"],
        "tasks": understood["tasks"],
    }

    _, plan_out = _run_policy_and_plan(state)
    steps = (plan_out.get("plan_ir") or {}).get("steps") or []
    overlap_steps = [step for step in steps if step.get("name") == "get_holdings_overlap"]

    assert len(overlap_steps) == 1
    inputs = overlap_steps[0].get("inputs") or {}
    assert inputs.get("holder_cik_or_name") == "Berkshire Hathaway"
    assert [row.get("ticker") for row in inputs.get("positions") or []] == ["NVDA", "AAPL"]


def test_planner_stub_emits_company_holdings_steps_when_sec_holdings_enabled(monkeypatch):
    monkeypatch.setenv("SEC_HOLDINGS_ENABLED", "true")
    understood = _understand("AAPL 最近 insider 买卖有没有异常？")
    state = {
        "query": "AAPL 最近 insider 买卖有没有异常？",
        "output_mode": "brief",
        "subject": understood["subject"],
        "operation": understood["operation"],
        "tasks": understood["tasks"],
    }

    _, plan_out = _run_policy_and_plan(state)
    step_names = _step_names(plan_out)

    assert "get_insider_transactions" in step_names
    assert "get_institution_holdings_by_ticker" in step_names


def test_planner_stub_skips_holdings_steps_when_sec_holdings_disabled(monkeypatch):
    monkeypatch.delenv("SEC_HOLDINGS_ENABLED", raising=False)
    understood = _understand("哪些机构最近加仓了 MSFT？")
    state = {
        "query": "哪些机构最近加仓了 MSFT？",
        "output_mode": "brief",
        "subject": understood["subject"],
        "operation": understood["operation"],
        "tasks": understood["tasks"],
    }

    _, plan_out = _run_policy_and_plan(state)

    assert HOLDINGS_TOOLS.isdisjoint(set(_step_names(plan_out)))

"""财期、两期计算与展示合同的离线回归，不调用外部服务。"""
from copy import deepcopy

import pytest

from backend.graph.request_compiler import compile_semantic_contract
from backend.graph.nodes.policy_gate import policy_gate
from backend.graph.planning.rule_planner import rule_based_planner
from backend.graph.synthesis.contracts import NormalizedEvidence
from backend.graph.synthesis.requirement_support import calculation_record, exact_support_reasons, time_scope_matches
from backend.graph.renderers.fact_formatters import format_fact
from backend.tools import sec
from backend.tools.financial_calculations import calculate_period_change


def fact(value, start, end, **fields):
    return {"subject": "EXM", "metric": "revenue", "value": value, "unit": "USD", "frequency": "quarterly",
        "period_start": start, "period_end": end, "filed": "2026-08-01", "concept": "Revenues",
        "source_url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000000001.json", **fields}


def evidence(payload):
    return NormalizedEvidence(source_id="financial", kind="filing_context", subject="EXM", usage="fact",
        text="已核验财务数据", task_ids=["task"], frequency=payload.get("frequency", "quarterly"), structured_data=payload)


def test_growth_keeps_two_inputs_and_cannot_be_satisfied_by_amount_only():
    current = fact(150, "2026-04-01", "2026-06-30")
    previous = fact(100, "2025-04-01", "2025-06-30", filed="2025-08-01")
    spec = {"operation": "growth_rate", "baseline": "year_ago"}
    computed = calculate_period_change(current, previous, **spec)
    assert computed["value"] == .5
    assert computed["derivation_inputs"] == [current, previous]
    payload = {"selected_period": "2026-06-30", "frequency": "quarterly", "revenue": [150],
        "fact_metadata": {"revenue": [current]}, "calculations": [computed]}
    req = {"metric": "revenue", "kind": "calculation", "calculation": spec,
        "time_scope": {"kind": "fiscal_quarter", "selection": "latest_complete", "completed_only": True}}
    item = evidence(payload)
    assert calculation_record(item, req) == computed
    assert exact_support_reasons(req, [item]) == []
    assert "营收同比增长率 50%" in format_fact(item, profile="chat")
    assert "2025-04-01 至 2025-06-30" in format_fact(item)
    payload["calculations"] = []
    assert "requirement_calculation_missing:revenue" in exact_support_reasons(req, [evidence(payload)])


@pytest.mark.parametrize("changes", [{"unit": "CNY"}, {"concept": "OtherRevenue"},
    {"period_start": "2025-01-01"}, {"subject": "OTHER"}, {"value": 0}, {"value": -100}])
def test_growth_rejects_incomparable_or_nonpositive_baseline(changes):
    assert calculate_period_change(fact(150, "2026-04-01", "2026-06-30"),
        {**fact(100, "2025-04-01", "2025-06-30"), **changes}, operation="growth_rate", baseline="year_ago") is None


def test_explicit_year_and_future_disclosure_are_rejected():
    row = fact(100, "2024-01-01", "2024-12-31", frequency="annual", filed="2025-03-01")
    item = evidence({"frequency": "annual", "value": 100, **row})
    assert not time_scope_matches(item, {"kind": "fiscal_year", "selection": "explicit", "period_start": "2025-01-01", "period_end": "2025-12-31"})
    assert time_scope_matches(item, {"kind": "fiscal_year", "period_end": "2024-12-31", "as_of": "2025-04-01"})
    assert not time_scope_matches(item, {"kind": "fiscal_year", "as_of": "2025-02-01"})


def test_compiler_rejects_component_field_names_and_separates_presentation():
    semantic = {"subjects": [{"id": "exm", "label": "Example", "type": "company", "tickers": ["EXM"]}],
        "requirements": [{"source_text": "新闻", "description": "新闻", "kind": "event_window", "metric": "news_catalysts",
            "subject": "EXM", "subject_refs": ["exm"], "attributes": ["include_date", "include_link", "itemized"]}]}
    compiled = compile_semantic_contract({"query": "新闻"}, semantic, {})
    req = compiled["tasks"][0]["answer_requirements"][0]
    assert req["attributes"] == []
    assert req["presentation"] == ["include_date", "include_link", "itemized"]
    bad = deepcopy(semantic)
    bad["requirements"][0]["components"] = ["metric", "revenue", "measurement"]
    with pytest.raises(ValueError, match="request_component_shape_invalid"):
        compile_semantic_contract({"query": "新闻"}, bad, {})


def test_sec_annual_scope_excludes_quarters_and_future_revisions(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "FinSight test@example.com")
    monkeypatch.setattr(sec, "_load_ticker_map", lambda headers: {"EXM": {"cik": "0000000001", "title": "Example"}})
    rows = [
        {"start": "2025-01-01", "end": "2025-12-31", "val": 150, "filed": "2026-02-01", "accn": "annual", "form": "10-K"},
        {"start": "2024-01-01", "end": "2024-12-31", "val": 100, "filed": "2025-02-01", "accn": "prior", "form": "10-K"},
        {"start": "2025-01-01", "end": "2025-12-31", "val": 900, "filed": "2026-11-01", "accn": "future", "form": "10-K/A"},
        {"start": "2026-04-01", "end": "2026-06-30", "val": 70, "filed": "2026-08-01", "accn": "quarter", "form": "10-Q"},
    ]
    monkeypatch.setattr(sec, "_fetch_companyfacts", lambda *args: {"cik": 1, "facts": {"us-gaap": {"Revenues": {"units": {"USD": rows}}}}})
    result = sec.get_sec_company_facts_quarterly("EXM", time_scope={"kind": "fiscal_year", "selection": "latest_complete", "as_of": "2026-10-07"},
        calculations=[{"metric": "revenue", "operation": "growth_rate", "baseline": "year_ago"}])
    assert result["error"] is None
    assert result["frequency"] == "annual"
    assert result["selected_period"] == "2025-12-31"
    assert result["revenue"] == [150, 100]
    assert result["calculations"][0]["value"] == .5
    assert "不能当作单季" not in format_fact(evidence(result))


def test_planner_keeps_annual_and_quarterly_calculations_separate():
    query = "EXM最新季度营收同比与完整财年营收同比"
    rows = [{"source_text": text, "description": text, "kind": "calculation", "metric": "revenue",
        "subject": "EXM", "subject_refs": ["exm"], "calculation": {"operation": "growth_rate", "baseline": "year_ago"},
        "time_scope": {"kind": kind, "selection": "latest_complete", "completed_only": True}}
        for text, kind in [("季度营收同比", "fiscal_quarter"), ("财年营收同比", "fiscal_year")]]
    state = {"query": query, "output_mode": "chat", **compile_semantic_contract({"query": query},
        {"subjects": [{"id": "exm", "label": "Example", "type": "company", "tickers": ["EXM"]}], "requirements": rows}, {"status": "confirmed"})}
    state.update(policy_gate(state))
    state.update(rule_based_planner(state))
    steps = [step for step in state["plan_ir"]["steps"] if step["name"] == "get_sec_company_facts_quarterly"]
    assert len(steps) == 2
    assert {step["inputs"]["time_scope"]["kind"] for step in steps} == {"fiscal_year", "fiscal_quarter"}
    assert all(step["inputs"]["calculations"] == [{"metric": "revenue", "operation": "growth_rate", "baseline": "year_ago"}] for step in steps)

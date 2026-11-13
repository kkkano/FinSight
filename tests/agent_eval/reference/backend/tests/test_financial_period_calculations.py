"""财期、两期计算与展示合同的离线回归，不调用外部服务。"""
from copy import deepcopy

import pytest

from backend.graph.request_compiler import compile_semantic_contract
from backend.graph.nodes.policy_gate import policy_gate
from backend.graph.planning.rule_planner import rule_based_planner
from backend.graph.synthesis.contracts import NormalizedEvidence
from backend.graph.synthesis.requirement_support import calculation_record, exact_support_reasons, presentation_reasons, time_scope_matches
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
        "presentation": ["include_inputs", "include_formula", "include_provenance"],
        "time_scope": {"kind": "fiscal_quarter", "selection": "latest_complete", "completed_only": True}}
    item = evidence(payload)
    assert calculation_record(item, req) == computed
    assert exact_support_reasons(req, [item]) == []
    assert presentation_reasons(req, [item]) == []
    assert "营收同比增长率 50%" in format_fact(item, profile="chat")
    assert "2025-04-01 至 2025-06-30" in format_fact(item)
    payload["calculations"] = []
    assert "requirement_calculation_missing:revenue" in exact_support_reasons(req, [evidence(payload)])
    assert "presentation_inputs_missing" in presentation_reasons(req, [evidence(payload)])


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


def test_unknown_fact_does_not_inherit_a_seeded_investment_report():
    query = "EXM营收同比，列计算依据和未知量"
    rows = [{"source_text": "营收同比", "description": "营收同比", "kind": "calculation", "metric": "revenue",
        "subject": "EXM", "subject_refs": ["exm"], "calculation": {"operation": "growth_rate", "baseline": "year_ago"},
        "presentation": ["include_inputs", "include_formula", "include_provenance"],
        "time_scope": {"kind": "fiscal_quarter", "selection": "latest_complete", "completed_only": True}},
        {"source_text": "未知量", "description": "未知量", "kind": "fact_attribute", "metric": "unknown",
         "subject": "EXM", "subject_refs": ["exm"]}]
    seed = {"query": query, "tasks": [{"id": "seed", "subject_type": "company", "subject_label": "Example", "tickers": ["EXM"],
        "operation": {"name": "investment_opinion", "params": {}}, "required_evidence": ["news_context", "technical_snapshot", "company_profile"]}]}
    state = {"query": query, "output_mode": "chat", **compile_semantic_contract(seed,
        {"subjects": [{"id": "exm", "label": "Example", "type": "company", "tickers": ["EXM"]}], "requirements": rows}, {"status": "confirmed"})}
    task = state["tasks"][0]
    assert task["operation"]["name"] == "qa"
    assert task["required_evidence"] == ["filing_context", "document_context"]
    assert task["answer_requirements"][1]["metric"] == "unknown"
    state.update(policy_gate(state))
    state.update(rule_based_planner(state))
    names = {step["name"] for step in state["plan_ir"]["steps"]}
    assert "get_sec_company_facts_quarterly" in names
    assert not names.intersection({"get_company_news", "news_agent", "technical_agent", "get_technical_snapshot"})


def test_comparison_reuses_both_companies_annual_calculations():
    query = "甲营收增长、乙营收增长，比较两家公司"
    rows = [{"source_text": text, "description": text, "kind": "calculation", "metric": "revenue",
        "subject": ticker, "subject_refs": [ref], "calculation": {"operation": "growth_rate", "baseline": "year_ago"},
        "time_scope": {"kind": "fiscal_year", "selection": "latest_complete", "completed_only": True, "source_text": text}}
        for text, ticker, ref in [("甲营收增长", "EXMA", "a"), ("乙营收增长", "EXMB", "b")]]
    rows.append({"source_text": "比较两家公司", "description": "比较增长", "kind": "comparison", "metric": "unknown",
        "subject_refs": ["a", "b"], "components": ["revenue"],
        "time_scope": {"kind": "fiscal_year", "selection": "latest_complete", "completed_only": True}})
    state = {"query": query, "output_mode": "chat", **compile_semantic_contract({"query": query},
        {"subjects": [{"id": ref, "label": ref, "type": "company", "tickers": [ticker]} for ref, ticker in [("a", "EXMA"), ("b", "EXMB")]],
         "relation": "compare", "requirements": rows}, {"status": "confirmed"})}
    comparison = state["tasks"][2]["answer_requirements"][0]
    assert comparison["metric"] == "comparison"
    assert comparison["capability_status"] == "supported"
    assert "filing_context" in state["tasks"][2]["required_evidence"]
    assert len(comparison["comparison_requirement_ids"]) == 2
    state.update(policy_gate(state))
    state.update(rule_based_planner(state))
    steps = [step for step in state["plan_ir"]["steps"] if step["name"] == "get_sec_company_facts_quarterly"]
    assert len(steps) == 2
    assert {step["inputs"]["ticker"] for step in steps} == {"EXMA", "EXMB"}
    assert all("task_3" in step["task_ids"] and len(step["task_ids"]) == 2 for step in steps)
    assert all(step["inputs"]["time_scope"]["kind"] == "fiscal_year" and step["inputs"]["calculations"] for step in steps)


def test_qualitative_components_trigger_semantic_repair_and_unknown_metric_remains():
    query = "估值、量子指标"
    raw = {"subjects": [{"id": "exm", "label": "Example", "type": "company", "tickers": ["EXM"]}],
        "requirements": [{"source_text": "估值", "description": "估值", "kind": "explanation", "metric": "valuation_reasonableness",
             "subject_refs": ["exm"], "components": ["valuation_reasonableness"]}]}
    with pytest.raises(ValueError, match="request_component_qualitative_invalid"):
        compile_semantic_contract({"query": query}, raw, {})
    raw["requirements"] = [{"source_text": "量子指标", "description": "未知实际指标比较", "kind": "comparison", "metric": "unknown",
        "metric_text": "量子指标", "subject_refs": ["exm"]}]
    requirement = compile_semantic_contract({"query": query}, raw, {})["tasks"][0]["answer_requirements"][0]
    assert requirement["metric"] == "unknown"
    assert requirement["capability_status"] == "unsupported"


def test_single_requested_listing_expansion_gets_one_semantic_repair(monkeypatch):
    import asyncio
    from langchain_core.messages import AIMessage
    import backend.graph.semantic_requirements as module

    query = "Example 0123.HK 最新营收"
    calls = []

    async def invoke(messages, **kwargs):
        calls.append(kwargs["context"])
        kwargs["context"].budget.reserve_provider_attempt()
        subjects = [{"id": "listing", "label": "Example", "type": "company", "tickers": ["0123.HK"]}]
        if len(calls) == 1:
            subjects.append({"id": "other", "label": "Example alternate listing", "type": "company", "tickers": ["EXM"]})
        rows = [{"source_text": "营收", "description": "营收", "kind": "fact_attribute", "metric": "revenue",
            "subject_refs": [subject["id"]], "subject": subject["tickers"][0]} for subject in subjects]
        return {"raw": AIMessage(content="{}", response_metadata={"finish_reason": "stop"}),
            "parsed": {"route": "research", "subjects": subjects, "relation": "single", "requirements": rows}}

    monkeypatch.setattr(module, "ainvoke_configured_llm", invoke)
    raw, diagnostics = asyncio.run(module.extract_semantic_requirements({"query": query}, {}))
    assert len(calls) == 2 and calls[0] is calls[1]
    assert diagnostics["validation_attempts"] == ["request_single_subject_expanded"]
    assert [subject["tickers"] for subject in raw["subjects"]] == [["0123.HK"]]


@pytest.mark.parametrize("relation,query", [("compare", "比较0123.HK和Example"), ("single", "0123.HK和EXM的营收"),
    ("single", "0123.HK和Second Company的营收")])
def test_explicit_comparison_or_multiple_requested_subjects_are_kept(relation, query):
    subjects = [{"id": "a", "label": "Example", "type": "company", "tickers": ["0123.HK"]},
        {"id": "b", "label": "Second Company", "type": "company", "tickers": ["EXM"]}]
    rows = [{"source_text": query, "description": "营收", "kind": "fact_attribute", "metric": "revenue",
        "subject_refs": [subject["id"]], "subject": subject["tickers"][0]} for subject in subjects]
    result = compile_semantic_contract({"query": query}, {"subjects": subjects, "relation": relation, "requirements": rows}, {})
    assert {ticker for task in result["tasks"] for ticker in task["tickers"]} == {"0123.HK", "EXM"}


def test_standard_window_return_operator_conflict_gets_one_semantic_repair(monkeypatch):
    import asyncio
    from langchain_core.messages import AIMessage
    import backend.graph.semantic_requirements as module

    query = "EXM最近20个交易日收益率"
    calls = []

    async def invoke(messages, **kwargs):
        calls.append(kwargs["context"])
        kwargs["context"].budget.reserve_provider_attempt()
        row = {"source_text": "20个交易日收益率", "description": "窗口收益", "kind": "calculation", "metric": "cumulative_return",
            "subject": "EXM", "subject_refs": ["exm"], "time_scope": {"kind": "trading_sessions", "count": 20, "completed_only": True}}
        if len(calls) == 1:
            row["calculation"] = {"operation": "growth_rate", "baseline": "previous_period"}
        return {"raw": AIMessage(content="{}", response_metadata={"finish_reason": "stop"}),
            "parsed": {"route": "research", "subjects": [{"id": "exm", "label": "Example", "type": "company", "tickers": ["EXM"]}], "requirements": [row]}}

    monkeypatch.setattr(module, "ainvoke_configured_llm", invoke)
    raw, diagnostics = asyncio.run(module.extract_semantic_requirements({"query": query}, {}))
    assert len(calls) == 2 and calls[0] is calls[1]
    assert diagnostics["validation_attempts"] == ["request_calculation_domain_conflict"]
    row = raw["requirements"][0]
    assert row["metric"] == "cumulative_return" and row["time_scope"]["count"] == 20 and row["calculation"] is None
    independent = deepcopy(raw)
    independent["requirements"].append({"source_text": "收益率", "description": "比较两个已计算收益率的真实要求", "kind": "calculation", "metric": "unknown",
        "metric_text": "两个收益率的变化", "subject_refs": ["exm"], "components": ["cumulative_return"],
        "calculation": {"operation": "growth_rate", "baseline": "previous_period"}})
    requirements = compile_semantic_contract({"query": query}, independent, {})["tasks"][0]["answer_requirements"]
    assert len(requirements) == 2 and requirements[1]["metric"] == "unknown" and requirements[1]["calculation"]


def test_data_obligations_disguised_as_empty_constraints_are_rejected():
    query = "列出AAOI过去七天新闻，附日期链接，排除旧消息，去重"
    raw = {"subjects": [{"id": "aaoi", "type": "company", "label": "AAOI", "tickers": ["AAOI"]}],
        "relation": "single", "requirements": [{"source_text": source, "description": source, "kind": "constraint",
            "metric": "news_catalysts", "subject_refs": ["aaoi"], "constraints": []}
            for source in ["列出AAOI过去七天新闻", "附日期链接", "排除旧消息", "去重"]], "constraints": []}
    with pytest.raises(ValueError, match="request_constraint_metric_conflict"):
        compile_semantic_contract({"query": query}, raw, {})
    corrected = deepcopy(raw)
    corrected["requirements"][0].update(kind="event_window", presentation=["include_date", "include_link"],
        time_scope={"kind": "calendar_window", "count": 7, "unit": "days", "direction": "past"})
    corrected["requirements"] = corrected["requirements"][:1]
    task = compile_semantic_contract({"query": query}, corrected, {})["tasks"][0]
    assert task["required_evidence"] == ["news_context"]
    control = {"constraint_type": "other", "source_text": "去重", "subject_refs": ["aaoi"]}
    raw["requirements"] = [{"source_text": "去重", "description": "仅保留控制条件", "kind": "constraint",
        "metric": "news_catalysts", "subject_refs": ["aaoi"], "constraints": [control]}]
    compiled = compile_semantic_contract({"query": query}, raw, {})
    assert compiled["understanding"]["semantic_contract"]["requirements"][0]["kind"] == "constraint"


def test_relational_explanation_binds_known_inputs_without_forcing_numeric_analysis():
    query = "甲营收、乙营收，并列数值并解释两公司差异"
    subjects = [{"id": ref, "label": ref, "type": "company", "tickers": [ticker]} for ref, ticker in [("a", "EXMA"), ("b", "EXMB")]]
    rows = [{"source_text": text, "description": text, "kind": "fact_attribute", "metric": "revenue", "subject_refs": [ref]}
        for text, ref in [("甲营收", "a"), ("乙营收", "b")]]
    rows.extend([
        {"source_text": "并列数值", "description": "并列数值", "kind": "comparison", "metric": "comparison", "subject_refs": ["a", "b"], "requires_analysis": False},
        {"source_text": "解释两公司差异", "description": "解释两公司差异", "kind": "explanation", "metric": "unknown", "subject_refs": ["a", "b"], "requires_analysis": True}])
    result = compile_semantic_contract({"query": query}, {"subjects": subjects, "relation": "compare", "requirements": rows}, {})
    relational = result["tasks"][2]["answer_requirements"]
    assert [row["metric"] for row in relational] == ["comparison", "comparison"]
    assert [row["requires_analysis"] for row in relational] == [False, True]
    assert all(len(row["comparison_requirement_ids"]) == 2 for row in relational)
    assert all("filing_context" in row["evidence_kinds"] for row in relational)
    unknown = compile_semantic_contract({"query": query}, {"subjects": subjects, "relation": "compare", "requirements": rows[-1:]}, {})
    assert unknown["tasks"][0]["answer_requirements"][0]["metric"] == "unknown"


@pytest.mark.parametrize("ticker,needs_snapshot", [("0700.HK", True), ("300750.SZ", True), ("NVDA", False)])
def test_market_financial_numeric_floor_preserves_structured_source(ticker, needs_snapshot):
    query = f"{ticker}季度营收"
    raw = {"subjects": [{"id": "company", "type": "company", "label": ticker, "tickers": [ticker]}],
        "relation": "single", "requirements": [{"source_text": query, "description": query,
            "kind": "fact_attribute", "metric": "revenue", "subject_refs": ["company"]}]}
    result = compile_semantic_contract({"query": query}, raw, {})
    evidence = result["tasks"][0]["required_evidence"]
    assert "filing_context" in evidence
    assert ("fundamental_snapshot" in evidence) is needs_snapshot

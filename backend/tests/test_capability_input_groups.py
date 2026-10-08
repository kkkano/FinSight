"""必需输入、替代来源和未知限定条件的完整合同回归。"""
from dataclasses import replace

from backend.graph.research_capabilities import CAPABILITIES, InputGroup
from backend.graph.request_compiler import compile_semantic_contract
from backend.graph.nodes.policy_gate import policy_gate
from backend.graph.planning.rule_planner import rule_based_planner
from backend.graph.coverage_validator import validate_plan_coverage
from backend.graph.synthesis.contracts import NormalizedEvidence, TaskSynthesisResult
from backend.graph.synthesis.requirement_validation import evaluate_answer_requirements
from backend.report.quality_engine import evaluate_result_quality


def compile_rows(query, ticker, rows, mode="chat"):
    raw = {"subjects": [{"id": "issuer", "type": "company", "label": ticker, "tickers": [ticker]}],
           "output_mode": mode, "requirements": [
        {"source_text": query, "description": query, "kind": "fact_attribute", "metric": "revenue",
         "subject_refs": ["issuer"], **row} for row in rows]}
    state = {"query": query, "output_mode": mode, "ui_context": {}}
    state.update(compile_semantic_contract(state, raw, {}))
    state.update(policy_gate(state))
    state.update(rule_based_planner(state))
    return state


def test_market_support_checks_every_required_group_and_enrichment_is_optional():
    valuation = CAPABILITIES["valuation_reasonableness"]
    assert valuation.supports_market("CN")
    assert "earnings_estimates" in valuation.enrichment
    required_forecast = replace(valuation, required_input_groups=(
        InputGroup(group_id="profile", any_of=["company_profile"]),
        InputGroup(group_id="forecast", any_of=["earnings_estimates"])))
    assert required_forecast.producers("CN")
    assert not required_forecast.supports_market("CN")


def test_alternative_producer_satisfies_coverage_without_optional_forecast():
    state = compile_rows("研究公司估值", "002174.SZ", [{"metric": "valuation_reasonableness", "kind": "explanation"}], "investment_report")
    frame = state["request_frames"][0]
    minimal = {"steps": [{"id": "profile", "name": "get_company_info", "task_ids": ["task_1"],
                           "subject_tickers": ["002174.SZ"], "evidence_kinds": ["company_profile"]},
                          {"id": "filing", "name": "get_local_market_filings", "task_ids": ["task_1"],
                           "subject_tickers": ["002174.SZ"], "evidence_kinds": ["filing_context"]}]}
    assert validate_plan_coverage(request_frame=frame, plan_ir=minimal, market="CN")["status"] == "ok"
    assert state["trace"]["coverage_validator"]["status"] == "ok"
    assert "get_earnings_estimates" not in {step["name"] for step in state["plan_ir"]["steps"]}


def test_legacy_unknown_price_modifier_keeps_window_collection_and_remains_partial():
    query = "TSLA过去20个已经结束的交易日价格收益"
    state = compile_rows(query, "TSLA", [{"metric": "cumulative_return", "measurement": "return",
        "time_scope": {"kind": "trading_sessions", "count": 20, "completed_only": True},
        "qualifiers": [{"name": "reporting_basis", "value": "price_return", "source_text": "价格收益"}]}])
    req = state["tasks"][0]["answer_requirements"][0]
    assert req["capability_status"] == "supported"
    assert req["qualifiers"][0]["name"] == "unknown" and req["unmapped_qualifiers"][0]["value"] == "price_return"
    assert any(step["name"] == "get_price_window_metrics" and step["inputs"]["sessions"] == 20 for step in state["plan_ir"]["steps"])
    evidence = NormalizedEvidence(source_id="window", task_ids=["task_1"], usage="fact", kind="price_window", subject="TSLA", text="已计算的20交易日收盘路径",
        structured_data={"sessions": 20, "completed_only": True, "price_basis": "split_adjusted_close", "dividends_included": False,
                         "metrics": {"cumulative_return": {"value": .1, "intervals": 20}}})
    task = TaskSynthesisResult(task_id="task_1", title="TSLA", priority=0, order_index=0, request_frame_id="frame",
        render_kind="single", render_group_id="frame", status="answered", fact_ids=["window"], claim_ids=[], evidence_ids=["window"],
        direction_supporting_claim_ids=[], agent_names=[], agreements=[], disagreements=[], conflicts=[], risks=[], limitations=[],
        fallback_used=False, error_codes=[])
    evaluate_answer_requirements(result=task, requirements=[req], evidence_index={"window": evidence}, claim_index={}, subjects=["TSLA"])
    assert task.status == "partial"
    assert task.requirement_results[0]["reason"] == "requirement_qualifier_unmapped"


def test_byd_legacy_report_kind_is_not_an_accounting_basis_and_base_metrics_are_collected():
    query = "比亚迪2025完整财年的经营现金流、资本开支和自由现金流"
    state = compile_rows(query, "002594.SZ", [
        {"metric": metric, "time_scope": {"kind": "fiscal_year", "period_start": "2025-01-01", "period_end": "2025-12-31"},
         "qualifiers": [{"name": "reporting_basis", "value": "annual_report", "source_text": "2025完整财年"}]}
        for metric in ("operating_cash_flow", "capital_expenditure", "free_cash_flow")])
    rows = state["tasks"][0]["answer_requirements"]
    assert all(row["capability_status"] == "supported" and row["unmapped_qualifiers"] for row in rows)
    disclosures = [step for step in state["plan_ir"]["steps"] if step["name"] == "get_local_market_filings"]
    assert disclosures and {"operating_cash_flow", "capital_expenditure", "free_cash_flow"} <= set(disclosures[0]["inputs"]["financial_metrics"])


def test_input_group_inherits_only_its_requirement_subject_and_task():
    req = {"requirement_id": "a-price", "kind": "fact_attribute", "subject": "AAPL", "subject_refs": ["a"]}
    frame = {"frame_id": "mixed", "subject": {"tickers": ["AAPL", "MSFT"]}, "task_ids": ["a-task", "b-task"],
             "evidence_obligations": ["price_snapshot"], "render_contract": {"answer_requirements": [req]},
             "required_input_groups": [{"group_id": "price", "requirement_id": "a-price", "any_of": ["price_snapshot"]}]}
    plan = {"tasks": [{"id": "a-task", "answer_requirements": [req]}, {"id": "b-task", "answer_requirements": [{"requirement_id": "b-news"}]}],
            "steps": [{"id": "price", "name": "get_stock_price", "task_ids": ["a-task"], "subject_tickers": ["AAPL"], "evidence_kinds": ["price_snapshot"]}]}
    assert validate_plan_coverage(request_frame=frame, plan_ir=plan)["status"] == "ok"


def test_input_presentation_and_typed_calculation_classification_do_not_drop_valid_financial_requests():
    query = "公司营收及同比增长列出计算输入"
    state = compile_rows(query, "AMD", [
        {"metric": "revenue", "presentation": ["include_inputs"]},
        {"metric": "revenue", "kind": "fact_attribute", "calculation": {"operation": "growth_rate", "baseline": "year_ago"}}])
    rows = state["tasks"][0]["answer_requirements"]
    assert len(rows) == 2 and rows[1]["kind"] == "calculation"
    assert rows[0]["presentation"] == ["include_inputs"] and rows[1]["calculation"]["baseline"] == "year_ago"


def test_partial_report_can_publish_verified_selected_facts_but_index_only_cannot():
    fact = {"source_id": "fact", "usage": "fact", "kind": "fundamental_snapshot", "text": "Revenue 100 CNY", "structured_data": {"revenue": 100}}
    task = {"task_id": "task", "status": "partial", "answer_requirements": [{"requirement_id": "revenue"}],
            "requirement_results": [{"requirement_id": "revenue", "status": "partial", "evidence_ids": ["fact"], "claim_ids": []}],
            "missing_requirements": [{"requirement_id": "revenue", "reason": "requirement_qualifier_unmapped"}]}
    state = {"output_mode": "chat", "understanding": {"route": "research", "requirements_status": "confirmed"},
             "artifacts": {"research_result": {"task_results": [task], "evidence_index": {"fact": fact}, "claim_index": {}}}}
    quality = evaluate_result_quality(state=state)
    assert quality["answer_status"] == "partial" and quality["publishable"] is True
    fact.update(kind="filing_context", structured_data={"content_type": "filing_index", "content_read": True, "body": "目录"})
    quality = evaluate_result_quality(state={**state, "output_mode": "investment_report"})
    assert quality["has_supported_content"] is False and quality["publishable"] is False
    state["artifacts"]["research_structural_block_reasons"] = ["evidence_id_content_conflict"]
    fact.update(kind="fundamental_snapshot", structured_data={"revenue": 100})
    assert evaluate_result_quality(state=state)["publishable"] is False

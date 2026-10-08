# -*- coding: utf-8 -*-
"""规则降级金样，以及有真实语义分母的主入口合同回归。"""
import pytest

from .conftest import assert_matches_snapshot, run_pipeline_deterministic

GOLDEN_QUERIES = {
    "single_price": "AAPL 现在多少钱",
    "single_report": "给我一份 NVDA 的投资分析",
    "compare": "对比 AAPL 和 MSFT 的估值",
    "multi_question": "对比 AAPL 和 MSFT 的估值，另外美联储下次议息是什么时候",
    "macro_only": "美国 CPI 最近走势怎么样",
    "news_impact": "TSLA 最近的新闻对股价有什么影响",
    "greeting": "你好",
    "vague_no_subject": "帮我分析一下",
    "url_doc": "总结一下 https://example.com/a-16k-filing 的要点",
    "cn_ticker": "600036 走势如何",
}


@pytest.mark.parametrize("name", sorted(GOLDEN_QUERIES))
def test_golden(name, deterministic_env):
    payload = run_pipeline_deterministic(GOLDEN_QUERIES[name])
    assert_matches_snapshot(name, payload)


CONFIRMED_CASES = {
    "single_price": (["AAPL"], {"quote"}, {"get_stock_price"}),
    "single_report": (["NVDA"], {"investment_attractiveness"}, {"get_stock_price", "get_company_info"}),
    "compare": (["AAPL", "MSFT"], {"valuation_reasonableness"}, {"get_stock_price", "get_company_info", "get_earnings_estimates"}),
    "multi_question": (["AAPL", "MSFT"], {"valuation_reasonableness", "macro_data"}, {"get_stock_price", "get_company_info", "get_official_macro_releases"}),
    "macro_only": ([], {"macro_data"}, {"get_official_macro_releases"}),
    "news_impact": (["TSLA"], {"external_impact"}, {"get_stock_price", "get_company_news"}),
    "url_doc": ([], {"document_summary"}, {"fetch_url_content"}),
    "cn_ticker": (["600036.SS"], {"trend_quality"}, {"get_stock_price", "get_technical_snapshot"}),
}


@pytest.mark.parametrize("name", CONFIRMED_CASES)
def test_confirmed_primary_contract_has_an_explicit_denominator(name, confirmed_semantic_env):
    result = run_pipeline_deterministic(GOLDEN_QUERIES[name], full_state=True)
    understanding = result["understanding"]
    contract = understanding.get("semantic_contract") or {}
    tickers, metrics, steps = CONFIRMED_CASES[name]
    assert understanding.get("requirements_status") == "confirmed"
    assert contract.get("version") == "request_spec.v2"
    assert contract.get("status") == "confirmed"
    assert sorted(ticker for subject in contract["subjects"] for ticker in subject["tickers"]) == sorted(tickers)
    assert {requirement["metric"] for requirement in contract["requirements"]} == metrics
    assert all(requirement["source_text"] in GOLDEN_QUERIES[name] for requirement in contract["requirements"])
    requirement_ids = {requirement["requirement_id"] for requirement in contract["requirements"]}
    projected_ids = {requirement["requirement_id"] for task in result["tasks"] for requirement in task["answer_requirements"]}
    assert requirement_ids == projected_ids
    assert steps <= {step["name"] for step in result["plan_ir"]["steps"]}
    assert result["trace"]["coverage_validator"]["status"] == "ok"
    assert result["output_mode"] == ("investment_report" if name == "single_report" else "chat")


def test_unconfirmed_report_without_evidence_cannot_claim_completion(deterministic_env):
    result = run_pipeline_deterministic(GOLDEN_QUERIES["single_report"], full_state=True)
    assert result["understanding"]["requirements_status"] == "deterministic_fallback"
    research = result["artifacts"]["research_result"]
    assert research["evidence_index"] == {}
    assert research["status"] == "unavailable"
    assert all(task["status"] != "answered" for task in research["task_results"])
    assert result["artifacts"]["publishable"] is False


def test_mixed_fallback_keeps_company_and_macro_evidence_scopes_separate(deterministic_env):
    result = run_pipeline_deterministic(GOLDEN_QUERIES["multi_question"], full_state=True)
    companies = [task for task in result["tasks"] if task["subject_type"] == "company"]
    macro = [task for task in result["tasks"] if task["subject_type"] == "macro"]
    assert len(macro) == 1
    assert all("macro_context" not in task["required_evidence"] for task in companies)
    assert all("美联储" not in task["request_text"] for task in companies)
    macro_steps = [step for step in result["plan_ir"]["steps"] if step["name"] in {"get_current_datetime", "search", "macro_agent"}]
    assert all(step["task_ids"] == [macro[0]["id"]] for step in macro_steps)

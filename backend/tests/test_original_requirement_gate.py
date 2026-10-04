"""防止请求在规划中丢项，以及用同维度的其它事实冒充完成。"""
from copy import deepcopy

import pytest

from backend.graph.synthesis.analysis_requirements import answer_requirements_by_task, requested_task_partition
from backend.graph.synthesis.contracts import Claim, NormalizedEvidence, TaskSynthesisResult
from backend.graph.synthesis.requirement_validation import evaluate_answer_requirements
from backend.graph.synthesis.requirement_validation import _comparable_financial_periods
from backend.graph.renderers.fact_formatters import format_fact


def task():
    return TaskSynthesisResult(task_id="task", title="区间研究", priority=0, order_index=0,
        request_frame_id="frame", render_kind="single", render_group_id="frame", status="answered",
        claim_ids=[], evidence_ids=[], direction_supporting_claim_ids=[], agent_names=[], agreements=[],
        disagreements=[], conflicts=[], risks=[], limitations=[], fallback_used=False, error_codes=[],
        requested_subjects=["SPY"], requested_dimensions=["performance"])


def requirement(**overrides):
    return {"requirement_id": "return", "kind": "calculation", "dimension": "performance",
        "metric": "cumulative_return", "source_text": "最近五个交易日累计收益", "description": "五日累计收益",
        "evidence_kinds": ["price_window"], "requires_analysis": False, "requires_explicit_binding": True,
        "capability_status": "supported", "time_scope": {"kind": "trading_sessions", "count": 5, "completed_only": True}, **overrides}


def window(sessions=5):
    return NormalizedEvidence(source_id="window", task_ids=["task"], kind="price_window", usage="fact", subject="SPY",
        text="已计算的收盘路径", currency="USD", structured_data={"sessions": sessions, "completed_only": True,
        "price_basis": "split_adjusted_close", "dividends_included": False, "period_end": "2026-10-02",
        "metrics": {"cumulative_return": {"value": .05, "base_date": "2026-09-25", "base_close": 100,
            "end_date": "2026-10-02", "end_close": 105, "intervals": sessions}}})


def evaluate(req, evidence, claims=None):
    result = task()
    result.fact_ids = result.evidence_ids = list(evidence)
    result.claim_ids = list(claims or {})
    evaluate_answer_requirements(result=result, requirements=[req], evidence_index=evidence, claim_index=claims or {}, subjects=["SPY"])
    return result


def test_original_snapshot_keeps_dropped_tasks_and_atomic_requirements():
    original = [{"id": "task", "answer_requirements": [requirement()]},
                {"id": "calendar", "answer_requirements": [{"requirement_id": "earnings", "description": "财报确认日期"}]}]
    state = {"tasks": [{"id": "task", "answer_requirements": []}],
             "understanding": {"semantic_contract": {"status": "confirmed", "tasks": deepcopy(original)}}}
    assert requested_task_partition(state)[0] == original
    assert set(answer_requirements_by_task(state)) == {"task", "calendar"}
    assert answer_requirements_by_task(state)["task"] == [requirement()]


def test_quote_cannot_satisfy_window_calculation_even_when_same_dimension():
    quote = NormalizedEvidence(source_id="quote", task_ids=["task"], subject="SPY", kind="price_snapshot", usage="fact", text="SPY 最新价格105 USD", market_price=105)
    result = evaluate(requirement(), {"quote": quote})
    assert result.status == "partial"
    assert result.requirement_results[0]["status"] == "missing"
    assert "requirement_metric_missing:cumulative_return" in result.requirement_results[0]["reason"]


def test_twenty_session_calculation_does_not_satisfy_five_session_request():
    result = evaluate(requirement(), {"window": window(20)})
    assert result.requirement_results[0]["status"] == "partial"
    assert "requirement_period_unverified" in result.requirement_results[0]["reason"]


def test_exact_window_is_answered_and_rendered_with_formula_dates_and_dividend_basis():
    evidence = window()
    result = evaluate(requirement(), {"window": evidence})
    assert result.requirement_results[0]["status"] == "answered"
    text = format_fact(evidence, profile="chat")
    for token in ("2026-09-25", "2026-10-02", "100", "105", "5%", "USD", "不计现金分红", "÷"):
        assert token in text


def test_daily_indicator_is_not_a_counted_window_and_other_indicators_cannot_fill_its_slot():
    evidence = NormalizedEvidence(source_id="technical", task_ids=["task"], kind="technical_snapshot", usage="fact", subject="SPY",
        text="技术指标", frequency="daily", structured_data={"rsi14": 54, "macd": 1.2, "support": 100})
    req = requirement(metric="rsi14", dimension="technical_quality", evidence_kinds=["technical_snapshot"], time_scope={"kind": "none"}, data_frequency="daily")
    assert evaluate(req, {"technical": evidence}).requirement_results[0]["status"] == "answered"
    req["metric"] = "support_resistance"
    assert "requirement_metric_missing:support_resistance" in evaluate(req, {"technical": evidence}).requirement_results[0]["reason"]
    req["metric"] = "rsi14"
    req["data_frequency"] = "weekly"
    assert "requirement_sampling_frequency_unverified" in evaluate(req, {"technical": evidence}).requirement_results[0]["reason"]
    # 抽取器默认值 unspecified 表示用户没有要求采样频率，不能把所有要求都判为频率未核实。
    req["data_frequency"] = "unspecified"
    assert evaluate(req, {"technical": evidence}).requirement_results[0]["status"] == "answered"


def test_unknown_requirement_stays_unanswered_despite_other_financial_facts():
    result = evaluate(requirement(metric="unknown", capability_status="unsupported", evidence_kinds=[], time_scope={}), {"window": window()})
    assert result.requirement_results[0]["status"] != "answered"
    assert "requirement_unsupported" in result.requirement_results[0]["reason"]


def test_explicit_requirement_binding_prevents_same_dimension_explanation_substitution():
    claim = Claim(claim_id="claim", task_id="task", agent_name="research_analyst", text="该期间价格上涨。", stance="unknown",
        dimension="market", metric="performance", confidence=.8, evidence_ids=["window"], limitations=[],
        requirement_ids=["another_question"], assertion_type="opinion")
    result = evaluate(requirement(requires_analysis=True), {"window": window()}, {"claim": claim})
    assert result.requirement_results[0]["status"] == "partial"
    assert "requirement_explanation_missing" in result.requirement_results[0]["reason"]


def test_excluding_comparison_is_checked_without_creating_a_data_requirement():
    req = requirement(kind="constraint", metric="", constraint_type="exclude_comparison", evidence_kinds=[], time_scope={})
    result = evaluate(req, {})
    assert result.requirement_results[0]["status"] == "answered"
    result.render_kind = "compare"
    evaluate_answer_requirements(result=result, requirements=[req], evidence_index={}, claim_index={}, subjects=["SPY"])
    assert result.requirement_results[0]["status"] != "answered"
    assert "excluded_comparison_executed" in result.requirement_results[0]["reason"]


def test_latest_completed_close_constraint_uses_calendar_proof_not_a_claim():
    evidence = window()
    evidence.structured_data.update(expected_session_dates=["2026-09-25", "2026-10-02"], missing_session_dates=[])
    req = requirement(kind="constraint", metric="unknown", constraint_type="other", evidence_kinds=[],
        time_scope={"kind": "latest_quote", "selection": "latest_complete", "completed_only": True})
    assert evaluate(req, {"window": evidence}).requirement_results[0]["status"] == "answered"
    evidence.structured_data["expected_session_dates"].append("2026-10-05")
    result = evaluate(req, {"window": evidence})
    assert result.requirement_results[0]["status"] != "answered"
    assert "requirement_completed_session_unverified" in result.requirement_results[0]["reason"]


def test_dated_closing_quote_is_a_close_but_cannot_stand_in_for_a_multi_session_path():
    evidence = NormalizedEvidence(source_id="quote", task_ids=["task"], kind="price_snapshot", usage="fact", subject="SPY",
        text="日线收盘报价", market_price=105, as_of="2026-10-02", currency="USD",
        metadata={"market_session": "regular_close", "source_time_precision": "date", "source_time_status": "provided"})
    req = requirement(metric="quote", evidence_kinds=["price_snapshot"], attributes=["end_close", "source_timestamp", "currency", "market_session"],
        time_scope={"kind": "latest_quote", "selection": "latest_complete", "completed_only": True})
    assert evaluate(req, {"quote": evidence}).requirement_results[0]["status"] == "answered"
    req.update(kind="constraint", metric="unknown", constraint_type="other")
    assert evaluate(req, {"quote": evidence}).requirement_results[0]["status"] == "answered"
    req["time_scope"] = {"kind": "trading_sessions", "count": 5, "selection": "latest_complete", "completed_only": True}
    assert evaluate(req, {"quote": evidence}).requirement_results[0]["status"] != "answered"


def test_primary_source_requirement_does_not_accept_a_model_claim_over_a_media_link():
    req = requirement(kind="constraint", metric="constraint", constraint_type="source_policy", source_requirement="primary", evidence_kinds=[], time_scope={})
    evidence = window()
    evidence.url = "https://www.reuters.com/business/company-update"
    result = evaluate(req, {"window": evidence})
    assert "requirement_primary_source_missing" in result.requirement_results[0]["reason"]
    evidence.url = "https://www.sec.gov/Archives/edgar/data/company/filing.htm"
    assert evaluate(req, {"window": evidence}).requirement_results[0]["status"] == "answered"


def test_attached_source_policy_is_not_lost_when_no_standalone_constraint_is_emitted():
    evidence = window()
    evidence.url = "https://www.reuters.com/business/company-update"
    req = requirement(constraints=[{"constraint_type": "source_policy", "source_requirement": "primary", "source_text": "只用原始官方来源"}])
    result = evaluate(req, {"window": evidence})
    assert "requirement_primary_source_missing" in result.requirement_results[0]["reason"]


def test_quarter_capital_allocation_does_not_accept_an_annual_cash_flow():
    facts = {key: {"value": value, "period_start": "2026-04-01", "period_end": "2026-06-30", "unit": "USD"}
             for key, value in [("operating_cash_flow", 100), ("capital_expenditure", 30), ("dividends_paid", 20), ("repurchases_paid", 10)]}
    evidence = NormalizedEvidence(source_id="capital", task_ids=["task"], kind="capital_allocation", usage="fact", subject="SPY",
        text="同期现金分配", frequency="quarterly", unit="USD", structured_data={"facts": facts, "capital_allocation_surplus": 40})
    req = requirement(metric="capital_allocation_surplus", dimension="fundamental_quality", evidence_kinds=["capital_allocation"], time_scope={"kind": "fiscal_quarter"})
    assert evaluate(req, {"capital": evidence}).requirement_results[0]["status"] == "answered"
    evidence.structured_data["facts"]["operating_cash_flow"]["period_start"] = "2025-07-01"
    result = evaluate(req, {"capital": evidence})
    assert "capital_allocation_period_mismatch" in result.requirement_results[0]["reason"]


@pytest.mark.parametrize("dimension", ["time_consistency", "time"])
def test_same_quarter_constraint_is_verified_from_cash_periods_without_an_llm_claim(dimension):
    scope = {"kind": "fiscal_quarter", "selection": "latest_complete"}
    requirements = [requirement(requirement_id=metric, metric=metric, dimension="fundamental_quality", evidence_kinds=["capital_allocation"], time_scope=scope)
                    for metric in ("operating_cash_flow", "dividends_paid")]
    requirements.append(requirement(requirement_id="same_quarter", kind="constraint", metric="unknown", constraint_type="other", evidence_kinds=[], time_scope=scope,
        source_text="请按同一季度核对", constraints=[{"source_text": "请按同一季度核对", "constraint_type": "other", "dimension": dimension}]))
    facts = {metric: {"value": value, "period_start": "2026-04-01", "period_end": "2026-06-30", "unit": "USD"}
             for metric, value in (("operating_cash_flow", 100), ("dividends_paid", 20))}
    evidence = NormalizedEvidence(source_id="capital", task_ids=["task"], kind="capital_allocation", usage="fact", subject="SPY",
        text="同期现金事实", frequency="quarterly", structured_data={"facts": facts})
    result = task()
    result.fact_ids = result.evidence_ids = ["capital"]
    evaluate_answer_requirements(result=result, requirements=requirements, evidence_index={"capital": evidence}, claim_index={}, subjects=["SPY"])
    assert all(check["status"] == "answered" for check in result.requirement_results)
    facts["dividends_paid"]["period_start"] = "2026-01-01"
    evaluate_answer_requirements(result=result, requirements=requirements, evidence_index={"capital": evidence}, claim_index={}, subjects=["SPY"])
    assert "requirement_period_unverified" in result.requirement_results[-1]["reason"]


def test_fiscal_year_comparison_allows_52_week_dates_but_not_a_quarter_or_other_currency():
    periods = [{("2025-01-01", "2025-12-31", "USD")}, {("2024-12-30", "2025-12-28", "USD")}]
    assert _comparable_financial_periods(periods, {"kind": "fiscal_year"})
    assert not _comparable_financial_periods(periods, {"kind": "fiscal_quarter"})
    assert not _comparable_financial_periods([periods[0], {("2025-10-01", "2025-12-31", "USD")}], {"kind": "fiscal_year"})
    assert not _comparable_financial_periods([periods[0], {("2025-01-01", "2025-12-31", "CNY")}], {"kind": "fiscal_year"})


def test_dividend_payment_history_cannot_satisfy_an_official_declaration():
    paid = NormalizedEvidence(source_id="paid", task_ids=["task"], kind="capital_allocation", usage="fact",
        subject="SPY", text="历史股息现金支付", structured_data={"dividends_paid": 100})
    req = requirement(metric="dividend_announcement", dimension="news_catalysts", evidence_kinds=["filing_context"], time_scope={})
    result = evaluate(req, {"paid": paid})
    assert "requirement_official_declaration_missing" in result.requirement_results[0]["reason"]
    declared = NormalizedEvidence(source_id="declared", task_ids=["task"], kind="filing_context", usage="fact",
        subject="SPY", text="官方派息宣告", structured_data={"content_read": True, "content_sections": {"material_event": "The board declared a cash dividend."},
            "dividend_announcements": [{"amount_per_share": .5, "currency": None, "source_url": "https://www.sec.gov/Archives/example.htm", "content_read": True, "verification": "official_filing_body"}]})
    assert "requirement_declaration_currency_unverified" in evaluate(req, {"declared": declared}).requirement_results[0]["reason"]
    declared.structured_data["dividend_announcements"][0]["currency"] = "USD"
    assert evaluate(req, {"declared": declared}).requirement_results[0]["status"] == "answered"


def test_exclusion_inside_longer_constraint_sentence_is_checked_against_executed_dimensions():
    sentence = "只讨论量价确认和跌回区间的失效条件，不展开基本面。"
    req = requirement(requirement_id="exclude", kind="constraint", metric="unknown", constraint_type="exclude_dimension",
        evidence_kinds=[], time_scope={"kind": "none"}, source_text=sentence,
        constraints=[{"source_text": "不展开基本面", "constraint_type": "exclude_dimension", "dimension": "fundamental"}])
    assert evaluate(req, {"window": window()}).requirement_results[0]["status"] == "answered"
    result = task()
    result.requested_dimensions = ["performance", "fundamental_quality"]
    result.fact_ids = result.evidence_ids = ["window"]
    evaluate_answer_requirements(result=result, requirements=[req], evidence_index={"window": window()}, claim_index={}, subjects=["SPY"])
    assert "excluded_dimension_executed" in result.requirement_results[0]["reason"]

"""SEC 单季比率的期间、单位、正基数和市场输入引用合同。"""
from copy import deepcopy

import pytest

from backend.agent_runtime.analysis import analyze_dataset
from backend.agent_runtime.data import RunData
from backend.agent_runtime.citations import references


@pytest.fixture
def payload():
    periods = ["2026-07-26", "2026-04-26", "2025-07-27"]
    starts = ["2026-04-27", "2026-01-26", "2025-04-28"]
    metrics = {
        "revenue": [96_221_000_000, 81_615_000_000, 46_743_000_000],
        "gross_profit": [72_142_000_000, 61_157_000_000, 33_853_000_000],
        "operating_income": [63_734_000_000, 53_536_000_000, 28_440_000_000],
        "net_income": [59_688_000_000, 58_321_000_000, 26_422_000_000],
        "operating_cash_flow": [24_077_000_000, 50_344_000_000, 15_365_000_000],
        "free_cash_flow": [None, None, None],
        "free_cash_flow_after_productive_asset_purchases": [21_400_000_000, 48_587_000_000, 13_470_000_000],
        "total_assets": [320_272_000_000, 259_525_000_000, 145_021_000_000],
        "total_liabilities": [91_288_000_000, 76_355_000_000, 48_835_000_000],
        "long_term_debt": [32_366_000_000, None, None],
        "cash_and_equivalents": [22_443_000_000, None, None],
        "capital_expenditures": [None, None, None],
    }
    source_url = "https://data.sec.gov/api/xbrl/companyfacts/CIK0001045810.json"
    metadata = {}
    for metric, values in metrics.items():
        instant = metric in {"total_assets", "total_liabilities", "long_term_debt", "cash_and_equivalents"}
        metadata[metric] = [{"subject": "NVDA", "metric": metric, "value": value, "unit": "USD",
            "source": "sec_companyfacts", "source_url": source_url, "frequency": "instant" if instant else "quarterly",
            "period_start": None if instant else start, "period_end": end, "concept": metric}
            if value is not None else None for value, start, end in zip(values, starts, periods)]
    return {"ticker": "NVDA", "source": "sec_companyfacts", "source_url": source_url, "currency": "USD",
            "frequency": "quarterly", "periods": periods, "period_ends": periods, **metrics, "fact_metadata": metadata}


def record(payload):
    data = RunData("u", "s", "r", "NVDA估值")
    ref = data.record("get_sec_company_facts_quarterly", {"ticker": "NVDA"}, payload)
    return data, ref


def test_latest_quarter_ratios_growth_and_lineage_use_actual_facts(payload):
    data, ref = record(payload)
    original = deepcopy(data.records[ref])
    result = analyze_dataset(data, ref, "financial_ratios")
    row = result["rows"][0]
    assert result["status"] == "ok"
    assert (row["ticker"], row["period_end"], row["currency"]) == ("NVDA", "2026-07-26", "USD")
    assert row["gross_margin_pct"] == pytest.approx(72_142 / 96_221 * 100)
    assert row["operating_margin_pct"] == pytest.approx(63_734 / 96_221 * 100)
    assert row["net_margin_pct"] == pytest.approx(59_688 / 96_221 * 100)
    assert row["operating_cash_flow_to_net_income_pct"] == pytest.approx(24_077 / 59_688 * 100)
    assert row["liabilities_to_assets_pct"] == pytest.approx(91_288 / 320_272 * 100)
    assert row["net_income_less_operating_income_margin_pp"] == pytest.approx((59_688 - 63_734) / 96_221 * 100)
    assert row["long_term_debt_less_cash_amount"] == 9_923_000_000
    assert row["capital_expenditures_to_revenue_pct"] is None
    assert row["revenue_qoq_pct"] == pytest.approx((96_221 / 81_615 - 1) * 100)
    assert row["net_income_yoy_pct"] == pytest.approx((59_688 / 26_422 - 1) * 100)
    assert row["revenue_yoy_baseline_period_end"] == "2025-07-27"
    assert row["free_cash_flow_margin_pct"] is None
    assert result["metric_gaps"]["free_cash_flow_margin_pct"] == "missing_or_incompatible_fact"
    calculation = next(item for item in result["calculations"] if item["metric"] == "gross_margin_pct")
    assert calculation["formula"] == "gross_profit/revenue*100"
    assert [item["value"] for item in calculation["derivation_inputs"]] == [72_142_000_000, 96_221_000_000]
    assert all(item["source_url"] == payload["source_url"] for item in calculation["derivation_inputs"])
    assert data.records[ref] == original
    assert result["financial_context"]["revenue"] == 96_221_000_000
    assert "fact_metadata" not in result["financial_context"]
    assert set(data.source_refs(ref)).issubset(data.source_refs(result["data_refs"][0]))
    sid = data.source_refs(result["data_refs"][0])[0]
    assert references(f"财务比率计算结果 [{sid}]", data.sources) == {"resolved": [sid], "unknown": []}


@pytest.mark.parametrize("change", ["unit", "end", "start"])
def test_mismatched_fact_unit_or_interval_does_not_make_a_ratio(payload, change):
    metadata = payload["fact_metadata"]["gross_profit"][0]
    metadata[{"unit": "unit", "end": "period_end", "start": "period_start"}[change]] = {
        "unit": "EUR", "end": "2026-04-26", "start": "2026-04-26"}[change]
    data, ref = record(payload)
    result = analyze_dataset(data, ref, "financial_ratios")
    assert result["rows"][0]["gross_margin_pct"] is None
    assert "gross_margin_pct" in result["metric_gaps"]
    assert result["rows"][0]["net_margin_pct"] is not None


def test_missing_latest_revenue_is_not_replaced_with_an_older_quarter(payload):
    payload["revenue"][0] = None
    payload["fact_metadata"]["revenue"][0] = None
    data, ref = record(payload)
    row = analyze_dataset(data, ref, "financial_ratios")["rows"][0]
    assert row["period_end"] == "2026-07-26"
    assert row["gross_margin_pct"] is None and row["revenue_qoq_pct"] is None
    assert row["operating_cash_flow_to_net_income_pct"] is not None


def test_declared_negative_free_cash_flow_is_kept_and_not_replaced_by_alternative_basis(payload):
    payload["free_cash_flow"][0] = -100_000_000
    payload["fact_metadata"]["free_cash_flow"][0] = {
        **payload["fact_metadata"]["operating_cash_flow"][0], "metric": "free_cash_flow", "value": -100_000_000}
    data, ref = record(payload)
    row = analyze_dataset(data, ref, "financial_ratios")["rows"][0]
    assert row["free_cash_flow_margin_pct"] == pytest.approx(-100_000_000 / 96_221_000_000 * 100)


def test_declared_capex_intensity_and_cash_debt_difference_keep_their_basis(payload):
    payload["capital_expenditures"][0] = 1_000_000_000
    payload["fact_metadata"]["capital_expenditures"][0] = {
        **payload["fact_metadata"]["operating_cash_flow"][0], "metric": "capital_expenditures", "value": 1_000_000_000}
    data, ref = record(payload)
    result = analyze_dataset(data, ref, "financial_ratios")
    assert result["rows"][0]["capital_expenditures_to_revenue_pct"] == pytest.approx(1_000 / 96_221 * 100)
    debt = next(item for item in result["calculations"] if item["metric"] == "long_term_debt_less_cash_amount")
    assert debt["formula"] == "long_term_debt-cash_and_equivalents" and debt["unit"] == "USD"
    assert "不代表总净债务" in debt["basis"]
    assert "net_debt" not in result["rows"][0]


def test_nonpositive_income_baselines_and_denominator_do_not_create_growth_or_cash_conversion(payload):
    for index, value in enumerate((0, -1_000_000_000, 0)):
        payload["net_income"][index] = value
        payload["fact_metadata"]["net_income"][index]["value"] = value
    data, ref = record(payload)
    row = analyze_dataset(data, ref, "financial_ratios")["rows"][0]
    assert row["operating_cash_flow_to_net_income_pct"] is None
    assert row["net_income_qoq_pct"] is None and row["net_income_yoy_pct"] is None
    assert row["net_margin_pct"] == 0 and row["revenue_qoq_pct"] is not None


def test_year_ago_growth_requires_matching_fiscal_interval_and_concept(payload):
    payload["fact_metadata"]["revenue"][2]["concept"] = "other_revenue_definition"
    payload["fact_metadata"]["net_income"][2]["period_start"] = "2025-05-20"
    data, ref = record(payload)
    row = analyze_dataset(data, ref, "financial_ratios")["rows"][0]
    assert row["revenue_yoy_pct"] is None and row["net_income_yoy_pct"] is None
    assert row["revenue_qoq_pct"] is not None


def test_same_ticker_market_inputs_remain_original_and_join_source_lineage(payload):
    data, ref = record(payload)
    profile = data.record("get_company_info", {"ticker": "NVDA"}, {"source": "fixture", "forwardPE": 11.73, "trailingPE": 23.60})
    quote = data.record("get_stock_price", {"ticker": "NVDA"}, "NVDA Current Price: $186.64")
    result = analyze_dataset(data, ref, "financial_ratios", {"other_dataset_refs": [profile, quote]})
    computed = result["data_refs"][0]
    assert data.records[computed]["inputs"]["dataset_refs"] == [ref, profile, quote]
    assert result["market_context"] == [{"tool": data.records[key]["tool"], "data_ref": key, "output": data.records[key]["output"]} for key in (profile, quote)]
    assert set(data.source_refs(ref) + data.source_refs(profile) + data.source_refs(quote)).issubset(data.source_refs(computed))
    sid = data.source_refs(computed)[0]
    assert references(f"财务与市场计算结果 [{sid}]", data.sources) == {"resolved": [sid], "unknown": []}


@pytest.mark.parametrize("tool,ticker,status", [("get_stock_price", "AAPL", "success"), ("search", "NVDA", "success"), ("get_company_info", "NVDA", "unavailable")])
def test_market_context_rejects_other_subjects_search_or_failed_results(payload, tool, ticker, status):
    data, ref = record(payload)
    other = data.record(tool, {"ticker": ticker}, {"price": 186.64}, status=status)
    before = len(data.records)
    result = analyze_dataset(data, ref, "financial_ratios", {"other_dataset_refs": [other]})
    assert result["error"] == "financial_market_context_invalid" and len(data.records) == before


def test_financial_operation_rejects_annual_data_and_unrequested_assumptions(payload):
    payload["frequency"] = "annual"
    data, ref = record(payload)
    assert analyze_dataset(data, ref, "financial_ratios")["error"] == "financial_quarterly_facts_required"
    assert analyze_dataset(data, ref, "financial_ratios", {"eps": 9.84})["error"] == "analysis_parameters_invalid"

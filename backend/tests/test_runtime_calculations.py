"""沙箱纯计算库与现有隔离 HTTP 入口的确定性合同。"""
import importlib
import json
from pathlib import Path
from copy import deepcopy
import shutil
import subprocess
import sys

import httpx
import pandas as pd
import pytest

from backend.agent_runtime.analysis import _financial_ratios, analyze_dataset, run_analysis_code
from backend.agent_runtime.data import RunData
from backend.agent_runtime.envelope import Source, ToolResult
from backend.analysis_worker import finsight
from backend.analysis_worker.data_access import get_frame


def prices(values, dates=None):
    return pd.DataFrame({"date": dates if dates is not None else pd.date_range("2026-01-01", periods=len(values)), "close": values})


def financial_rows():
    rows = []
    for start, end, revenue, net in [
        ("2026-07-01", "2026-09-30", 120, 30),
        ("2026-04-01", "2026-06-30", 100, 20),
        ("2025-07-01", "2025-09-30", 80, 15),
    ]:
        values = {"revenue": revenue, "gross_profit": revenue / 2, "operating_income": revenue * .3,
                  "net_income": net, "operating_cash_flow": 45, "free_cash_flow": 24, "capital_expenditures": 10,
                  "total_assets": 400, "total_liabilities": 200, "long_term_debt": 90, "cash_and_equivalents": 50}
        row = {"ticker": "TEST_A", "source": "sec_companyfacts", "currency": "USD", "frequency": "quarterly",
               "source_url": "https://example.test/filing/" + end, "period_start": start, "period_end": end, **values}
        row["fact_metadata"] = {metric: {"subject": "TEST_A", "metric": metric, "value": value, "unit": "USD",
            "frequency": "instant" if metric in {"total_assets", "total_liabilities", "long_term_debt", "cash_and_equivalents"} else "quarterly",
            "period_start": None if metric in {"total_assets", "total_liabilities", "long_term_debt", "cash_and_equivalents"} else start,
            "period_end": end, "concept": "us-gaap:" + metric, "source": "sec_companyfacts", "source_url": row["source_url"]}
            for metric, value in values.items()}
        rows.append(row)
    return rows


def companyfacts_payload():
    rows = financial_rows()
    metrics = list(rows[0]["fact_metadata"])
    return {"ticker": "TEST_A", "source": "sec_companyfacts", "currency": "USD", "frequency": "quarterly",
            "source_url": "https://example.test/companyfacts", "period_ends": [row["period_end"] for row in rows],
            "periods": ["2026Q3", "2026Q2", "2025Q3"],
            **{metric: [row[metric] for row in rows] for metric in metrics},
            "fact_metadata": {metric: [row["fact_metadata"][metric] for row in rows] for metric in metrics}}


def test_valuation_scenarios_preserve_legacy_math_and_explicit_assumptions():
    data = RunData("test", "session", "run", "估值假设")
    ref = data.record("get_company_info", {}, {"ticker": "TEST_A"})
    legacy = analyze_dataset(data, ref, "valuation_scenarios", {"eps": 4, "multiples": [20, 30], "currency": "USD"})
    result = finsight.valuation_scenarios(4, [20, 30], currency="USD")
    assert result["rows"] == legacy["rows"]
    assert [row["scenario_price"] for row in result["rows"]] == [80, 120]
    assert all(row["return_pct"] is None for row in result["rows"])
    assert result["method"] == {**legacy["method"], "eps_basis": "explicit_assumption"}
    assert result["units"] == {"multiple": "multiple", "eps": "USD/share", "scenario_price": "USD", "return_pct": "ratio"}
    assert result["limitations"] == legacy["limitations"]
    assert finsight.valuation_scenarios(4)["method"]["currency"] == "unknown"
    assert finsight.valuation_scenarios(4)["units"]["eps"] == "unknown"
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("eps,multiples", [
    (0, [20]), (-1, [20]), (float("nan"), [20]), (float("inf"), [20]), (True, [20]),
    (4, [0]), (4, [-1]), (4, [float("inf")]), (4, [False]), (4, range(1, 22)), (1e308, [20]),
])
def test_valuation_rejects_invalid_assumptions_and_non_finite_results(eps, multiples):
    with pytest.raises(ValueError, match="invalid_valuation_assumptions"):
        finsight.valuation_scenarios(eps, multiples)


def test_financial_ratios_match_existing_math_periods_units_and_provenance():
    rows = financial_rows()
    original = deepcopy(rows)
    result = finsight.financial_ratios(pd.DataFrame(rows))
    assert result == _financial_ratios(rows)
    latest = result["rows"][0]
    expected = {"gross_margin_pct": 50, "operating_margin_pct": 30, "net_margin_pct": 25,
                "operating_cash_flow_to_net_income_pct": 150, "free_cash_flow_margin_pct": 20,
                "liabilities_to_assets_pct": 50, "capital_expenditures_to_revenue_pct": 100 / 12,
                "net_income_less_operating_income_margin_pp": -5, "long_term_debt_less_cash_amount": 40,
                "revenue_qoq_pct": 20, "revenue_yoy_pct": 50, "net_income_qoq_pct": 50, "net_income_yoy_pct": 100}
    for metric, value in expected.items():
        assert latest[metric] == pytest.approx(value)
    assert latest["revenue_qoq_baseline_period_end"] == "2026-06-30"
    assert latest["revenue_yoy_baseline_period_end"] == "2025-09-30"
    assert {item["unit"] for item in result["calculations"]} == {"%", "pp", "USD"}
    assert all(fact["subject"] == "TEST_A" and fact["unit"] == "USD" and fact["source_url"]
               for calculation in result["calculations"] for fact in calculation["derivation_inputs"])
    assert result["metric_gaps"] == {} and rows == original
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("field,value,error", [
    ("ticker", "TEST_B", "financial_fact_context_mismatch"),
    ("currency", "HKD", "financial_fact_context_mismatch"),
    ("source", "other_source", "financial_quarterly_facts_required"),
    ("frequency", "annual", "financial_quarterly_facts_required"),
])
def test_financial_ratios_reject_mixed_subject_currency_and_non_quarterly_inputs(field, value, error):
    rows = financial_rows()
    rows[1][field] = value
    result = finsight.financial_ratios(pd.DataFrame(rows))
    assert result == _financial_ratios(rows)
    assert result["status"] == "unavailable" and result["error"] == error


@pytest.mark.parametrize("field,value,gap", [
    ("unit", "HKD", "missing_or_incompatible_fact"),
    ("subject", "TEST_B", "missing_or_incompatible_fact"),
    ("value", 999, "missing_or_incompatible_fact"),
    ("period_end", "2026-06-30", "missing_or_incompatible_fact"),
    ("period_start", "2026-01-01", "missing_or_incompatible_fact"),
    ("period_start", "2026-07-02", "period_start_mismatch"),
])
def test_financial_ratios_keep_incompatible_metric_missing_without_changing_good_facts(field, value, gap):
    rows = financial_rows()
    rows[0]["fact_metadata"]["gross_profit"][field] = value
    result = finsight.financial_ratios(pd.DataFrame(rows))
    assert result == _financial_ratios(rows)
    assert result["rows"][0]["gross_margin_pct"] is None
    assert result["metric_gaps"]["gross_margin_pct"] == gap
    assert result["rows"][0]["net_margin_pct"] == 25


@pytest.mark.parametrize("invalid", ["non_positive", "different_concept", "missing_source", "ambiguous_period"])
def test_growth_requires_one_comparable_positive_baseline_with_source(invalid):
    rows = financial_rows()
    if invalid == "non_positive":
        rows[1]["revenue"] = rows[1]["fact_metadata"]["revenue"]["value"] = -100
    elif invalid == "different_concept":
        rows[1]["fact_metadata"]["revenue"]["concept"] = "us-gaap:different_concept"
    elif invalid == "missing_source":
        rows[1]["fact_metadata"]["revenue"]["source_url"] = None
    else:
        rows.append(deepcopy(rows[1]))
    result = finsight.financial_ratios(pd.DataFrame(rows))
    assert result == _financial_ratios(rows)
    assert result["rows"][0]["revenue_qoq_pct"] is None
    assert result["rows"][0]["revenue_yoy_pct"] == 50
    assert result["metric_gaps"]["revenue_qoq_pct"] == (
        "ambiguous_baseline" if invalid == "ambiguous_period" else "comparable_positive_baseline_unavailable")


def test_financial_denominators_and_missing_values_are_not_fabricated():
    rows = financial_rows()
    rows[0]["net_income"] = rows[0]["fact_metadata"]["net_income"]["value"] = 0
    rows[0]["free_cash_flow"] = None
    result = finsight.financial_ratios(pd.DataFrame(rows))
    assert result["rows"][0]["operating_cash_flow_to_net_income_pct"] is None
    assert result["metric_gaps"]["operating_cash_flow_to_net_income_pct"] == "non_positive_denominator"
    assert result["rows"][0]["free_cash_flow_margin_pct"] is None
    assert result["rows"][0]["net_margin_pct"] == 0
    empty = finsight.financial_ratios(pd.DataFrame([{
        "ticker": "TEST_A", "source": "sec_companyfacts", "frequency": "quarterly", "currency": "USD", "period_end": "2026-09-30"}]))
    assert empty["status"] == "unavailable" and empty["error"] == "financial_ratios_unavailable"


def test_companyfacts_frames_keep_cash_debt_and_metric_metadata_for_ratios():
    payload = companyfacts_payload()
    before = deepcopy(payload)
    frame = get_frame({"h_financial": payload}, "h_financial", table="companyfacts")
    result = finsight.financial_ratios(frame)
    assert frame["cash_and_equivalents"].tolist() == [50, 50, 50]
    assert frame["long_term_debt"].tolist() == [90, 90, 90]
    assert result["rows"][0]["long_term_debt_less_cash_amount"] == 40
    assert result["rows"][0]["revenue_yoy_pct"] == 50
    assert result["calculations"][0]["derivation_inputs"][0]["source_url"] == payload["fact_metadata"]["gross_profit"][0]["source_url"]
    assert payload == before


def test_financial_library_imports_standalone_without_backend_package(tmp_path):
    worker = Path(__file__).resolve().parents[1] / "analysis_worker"
    for name in ("finsight.py", "financial_math.py"):
        shutil.copyfile(worker / name, tmp_path / name)
    code = ("import sys; sys.path.insert(0, " + repr(str(tmp_path)) + "); import finsight; "
            "assert finsight.valuation_scenarios(4,[20])['rows'][0]['scenario_price']==80; "
            "assert finsight.financial_ratios(finsight.pd.DataFrame())['error']=='financial_quarterly_facts_required'; "
            "assert not any(name=='backend' or name.startswith('backend.') for name in sys.modules)")
    completed = subprocess.run([sys.executable, "-I", "-B", "-c", code], cwd=tmp_path, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr


def test_statistics_matches_existing_algorithm_and_keeps_unknown_returns():
    frame = prices([10, None, 12, 9])
    before = frame.copy(deep=True)
    result = finsight.series_statistics(frame, unit="USD")
    data = RunData("test", "session", "run", "统计")
    ref = data.record("get_price_history", {}, {"rows": json.loads(frame.to_json(orient="records", date_format="iso"))})
    legacy = analyze_dataset(data, ref, "series_statistics")
    assert result["rows"] == legacy["rows"]
    assert result["units"]["return_ratio"] == "ratio" and result["units"]["mean"] == "USD"
    assert result["method"]["missing_values"] == 1
    assert finsight.series_statistics(prices([0, 5]))["rows"][0]["return_ratio"] is None
    pd.testing.assert_frame_equal(frame, before)
    json.dumps(result, allow_nan=False)


def test_moving_average_requires_full_observed_window_and_keeps_missing_values():
    result = finsight.moving_averages(prices([1, 2, 3, None, 5, 6, 7]), windows=[3], unit="USD")
    assert [row["ma3"] for row in result["rows"]] == [None, None, 2, None, None, None, 6]
    assert result["rows"][3]["close"] is None
    assert result["method"]["min_periods"] == "full_window" and result["units"]["ma3"] == "USD"
    json.dumps(result, allow_nan=False)


def test_consecutive_declines_matches_legacy_maximal_streaks():
    frame = prices([100, 90, 80, 85, 70, 60])
    data = RunData("test", "session", "run", "连续下跌")
    ref = data.record("get_price_history", {}, {"rows": json.loads(frame.to_json(orient="records", date_format="iso"))})
    old = analyze_dataset(data, ref, "historical_drawdown_episodes", {"frequency": "daily", "min_periods": 2})
    result = finsight.consecutive_declines(frame, min_periods=2)
    assert result["sample_count"] == 2 and result["completed_sample_count"] == 1
    assert [item["periods"] for item in result["episodes"]] == [2, 2]
    assert [item["return_ratio"] for item in result["episodes"]] == pytest.approx([item["return_pct"] for item in old["episodes"]])
    assert [item["start"] for item in result["episodes"]] == [item["start"] for item in old["episodes"]]


def test_missing_periods_break_decline_streak_and_incomplete_week_is_explicit():
    result = finsight.consecutive_declines(prices([100, 90, None, 70, 60]), min_periods=2)
    assert result["episodes"] == [] and result["rows"][2]["close"] is None
    weekly = prices([100, 90, 80], ["2026-01-02", "2026-01-09", "2026-01-16"])
    result = finsight.consecutive_declines(weekly, frequency="weekly", min_periods=2, latest_period_closed=False)
    assert len(result["rows"]) == 2 and result["episodes"] == []
    assert result["method"]["excluded_incomplete_period"] == "2026-01-16T00:00:00+00:00"


def test_peak_drawdown_differs_from_consecutive_declines_and_marks_recovery():
    frame = prices([100, 90, 95, 85, 101, 99, 98])
    result = finsight.drawdown_episodes(frame, unit="USD")
    assert result["sample_count"] == 2 and result["completed_sample_count"] == 1
    first, last = result["episodes"]
    assert first["periods"] == 3 and first["return_ratio"] == pytest.approx(-.15)
    assert first["recovery_date"].startswith("2026-01-05") and not first["ongoing"]
    assert last["ongoing"] and last["recovery_date"] is None
    assert finsight.consecutive_declines(frame, min_periods=3)["episodes"] == []
    missing = finsight.drawdown_episodes(prices([100, 80, None, 75]))
    assert missing["episodes"][0]["interrupted_by_missing"]
    assert missing["completed_sample_count"] == 0 and missing["rows"][2]["drawdown_ratio"] is None
    json.dumps(result, allow_nan=False)


def test_comparison_uses_common_dates_with_explicit_percent_units_and_no_gap_fill():
    left = prices([100, None, 90, 120])
    right = prices([200, 210, 220, 200])
    left.attrs.update(currency="USD", price_basis="adjusted_close", dividends_included=False)
    right.attrs.update(left.attrs)
    result = finsight.compare_series({"A": left, "B": right})
    assert [row["date"] for row in result["rows"]] == ["2026-01-01", "2026-01-03", "2026-01-04"]
    assert [row["series_1"] for row in result["rows"]] == pytest.approx([0, -10, 20])
    assert [row["series_2"] for row in result["rows"]] == pytest.approx([0, 10, 0])
    assert result["comparison_stats"]["crossovers"][0]["dates"] == ["2026-01-04"]
    assert result["method"]["currency"] == "USD" and result["units"]["series_1"] == "%"
    assert result["comparison_stats"]["lead_days"] == {"A": 1, "B": 1, "tie": 1}
    assert finsight.compare_series({"A": prices([1, 2]), "B": prices([2, 3])})["method"]["currency"] == "unknown"
    with pytest.raises(ValueError, match="comparison_basis_mismatch"):
        finsight.compare_series({"A": left, "B": right}, metadata={"B": {"currency": "HKD"}})


@pytest.mark.parametrize("function,kwargs", [
    (finsight.consecutive_declines, {"minimum_loss": 5}),
    (finsight.drawdown_episodes, {"minimum_loss": float("nan")}),
    (finsight.moving_averages, {"windows": [0]}),
    (finsight.series_statistics, {"latest_n": 3}),
])
def test_invalid_calculation_parameters_are_explicit(function, kwargs):
    with pytest.raises(ValueError):
        function(prices([1, 2]), **kwargs)


@pytest.fixture
def runner(monkeypatch, tmp_path):
    # 这里只执行可信测试代码，验证独立 runner 的名称空间，不启动或修改容器。
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "analysis_worker"))
    module = importlib.import_module("backend.analysis_worker.runner")
    monkeypatch.setattr(module, "INPUT", tmp_path / "request.json")
    return module


def test_runner_exposes_library_and_existing_dataset_helpers(runner):
    payload = {"code": "assert datasets['h_prices']['rows'][0]['close'] == 10\n"
                       "assert np.mean(get_frame('h_prices')['close']) == 15\n"
                       "result = finsight.series_statistics(frames['h_prices'], unit='USD')",
               "datasets": {"h_prices": {"rows": [{"date": "2026-01-01", "close": 10}, {"date": "2026-01-02", "close": 20}]}}}
    runner.INPUT.write_text(json.dumps(payload), encoding="utf-8")
    result = runner.run()
    assert result["status"] == "ok" and result["result"]["rows"][0]["mean"] == 15


def test_runner_accepts_hypotheses_without_fabricating_datasets(runner):
    runner.INPUT.write_text(json.dumps({"code": "import finsight\nassert not datasets and not frames\n"
                                               "result = finsight.series_statistics(pd.DataFrame({'date':['2026-01-01','2026-01-02'], 'close':[10,12]}))",
                                       "datasets": {}}), encoding="utf-8")
    result = runner.run()
    assert result["status"] == "ok" and result["result"]["rows"][0]["return_ratio"] == pytest.approx(.2)


def test_runner_can_compose_financial_ratios_and_valuation_without_new_tools(runner):
    payload = companyfacts_payload()
    runner.INPUT.write_text(json.dumps({"code": "import finsight\n"
        "result = {'ratios': finsight.financial_ratios(frames['h_financial']), "
        "'scenarios': finsight.valuation_scenarios(4, [20,30], currency='USD')}\n"
        "assert datasets['h_financial']['cash_and_equivalents'] == [50,50,50]",
        "datasets": {"h_financial": payload}}), encoding="utf-8")
    output = runner.run()
    assert output["status"] == "ok"
    assert output["result"]["ratios"]["rows"][0]["long_term_debt_less_cash_amount"] == 40
    assert output["result"]["ratios"]["rows"][0]["revenue_yoy_pct"] == 50
    assert [row["scenario_price"] for row in output["result"]["scenarios"]["rows"]] == [80, 120]


@pytest.mark.asyncio
async def test_financial_worker_result_inherits_input_sources_without_rewriting_raw_data(monkeypatch):
    payload = companyfacts_payload()
    data = RunData("test", "session", "run", "财务计算")
    handle = data.record("get_sec_company_facts_quarterly", {"ticker": "TEST_A"}, payload,
        envelope=ToolResult(status="ok", kind="table", sources=[Source(title="财报来源", url=payload["source_url"])]))
    original = deepcopy(data.records[handle])
    source_refs = data.source_refs(handle)
    output = finsight.financial_ratios(get_frame({handle: payload}, handle))
    original_client = httpx.AsyncClient

    async def worker(request):
        submitted = json.loads(request.content)
        assert submitted["datasets"] == {handle: payload}
        return httpx.Response(200, json={"status": "ok", "result": output})

    monkeypatch.setenv("FINSIGHT_ANALYSIS_WORKER_URL", "https://worker.example")
    monkeypatch.setenv("FINSIGHT_ANALYSIS_WORKER_TOKEN", "test-only-key")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(worker), **kwargs))
    result = await run_analysis_code(data, "result = finsight.financial_ratios(frames['" + handle + "'])", [handle], timeout=2)
    derived = data.records[result["data_refs"][0]]
    assert result["status"] == "ok" and source_refs
    assert data.source_refs(result["data_refs"][0]) == source_refs
    assert derived["output"]["method"]["kind"] == "derived"
    assert derived["output"]["method"]["input_refs"] == [handle]
    assert derived["output"]["calculations"] == output["calculations"]
    assert data.records[handle] == original


@pytest.mark.asyncio
async def test_hypothetical_code_is_only_sent_to_worker(monkeypatch):
    calls = []
    original_client = httpx.AsyncClient

    async def worker(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200, json={"status": "ok", "result": {"rows": [{"hypothesis": 6}]}})

    monkeypatch.setenv("FINSIGHT_ANALYSIS_WORKER_URL", "https://worker.example")
    monkeypatch.setenv("FINSIGHT_ANALYSIS_WORKER_TOKEN", "test-only-key")
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: original_client(transport=httpx.MockTransport(worker), **kwargs))
    data = RunData("test", "session", "run", "纯假设")
    code = "raise RuntimeError('此代码不能在 Web 进程执行')"
    result = await run_analysis_code(data, code, [], timeout=2)
    assert calls == [{"code": code, "datasets": {}, "timeout_seconds": 2}]
    assert result["status"] == "ok" and len(result["data_refs"]) == 1
    assert data.source_refs(result["data_refs"][0]) == []

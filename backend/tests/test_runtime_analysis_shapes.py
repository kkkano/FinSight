"""真实取数入口的财报/预期结构进入确定性分析，不请求外部服务。"""
from copy import deepcopy
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.agent_runtime.analysis import analyze_dataset, render_chart
from backend.agent_runtime.data import DatasetRowsError, RunData


@pytest.fixture
def sec_payload(monkeypatch):
    from backend.tools import sec

    def facts(values):
        return [{"start": start, "end": end, "val": value, "form": "10-Q", "fp": quarter, "filed": filed}
                for start, end, quarter, filed, value in [
                    ("2025-04-01", "2025-06-30", "Q3", "2025-08-01", values[0]),
                    ("2025-01-01", "2025-03-31", "Q2", "2025-05-01", values[1]),
                ]]

    companyfacts = {"facts": {"us-gaap": {
        "Revenues": {"units": {"USD": facts([100.0, 90.0])}},
        "EarningsPerShareDiluted": {"units": {"USD/shares": facts([1.55, 1.42])}},
    }}}
    monkeypatch.setattr(sec, "_resolve_user_agent", lambda: "FinSight tests@example.com")
    monkeypatch.setattr(sec, "_load_ticker_map", lambda _: {"AAPL": {"cik": "0000320193", "title": "Apple Inc."}})
    monkeypatch.setattr(sec, "_fetch_companyfacts", lambda *_: companyfacts)
    payload = sec.get_sec_company_facts_quarterly("AAPL", limit=2, time_scope={"as_of": "2025-09-01"})
    assert payload["error"] is None
    return payload


@pytest.fixture
def earnings_payload(monkeypatch):
    from backend.tools import financial

    stock = SimpleNamespace(
        earnings_estimate=pd.DataFrame({"avg": [2.0, 3.0], "numberOfAnalysts": [20, 18]}, index=["0q", "+1q"]),
        eps_trend=pd.DataFrame({"current": [2.0, 3.0], "7daysAgo": [1.9, 2.9]}, index=["0q", "+1q"]),
        eps_revisions=pd.DataFrame({"upLast30days": [2, 4], "downLast30days": [1, 1]}, index=["0q", "+1q"]),
        calendar={"Earnings Date": ["2025-10-30"]},
    )
    monkeypatch.setattr(financial, "create_ticker", lambda _: stock)
    payload = financial.get_earnings_estimates("AAPL")
    assert payload["error"] is None
    return payload


def record(payload, tool):
    data = RunData("fixture-user", "fixture-session", "fixture-run", "核对财报与预期")
    ref = data.record(tool, {"ticker": "AAPL"}, payload)
    return data, ref


def test_fiscal_context_matches_only_its_declared_period_and_survives_model_projection():
    from backend.agent_runtime.envelope import ToolResult, to_model

    fiscal = {"period_end": "2026-09-30", "fiscal_year": 2027, "fiscal_period": "Q1",
              "filed": "2026-10-28", "accession": "fixture-filing"}
    payload = {"source": "sec_companyfacts", "period_ends": ["2026-09-30", "2026-06-30"], "revenue": [92, 90],
               "latest_filing_fiscal_context": fiscal}
    before = deepcopy(payload)
    data, ref = record(payload, "get_sec_company_facts_quarterly")
    rows = data.rows(ref)
    assert rows[0]["fiscal_context"] == fiscal
    assert "fiscal_context" not in rows[1]
    text = to_model(ToolResult(status="ok", kind="table", data=payload), 2000)
    assert '"fiscal_year":2027' in text and '"fiscal_period":"Q1"' in text
    rows[0]["fiscal_context"]["fiscal_year"] = 1900
    assert payload == before and data.rows(ref)[0]["fiscal_context"] == fiscal


def test_financial_metadata_preview_preserves_selected_fact_filing_date():
    from backend.agent_runtime.data import fact_metadata_preview

    fact = {"unit": "USD", "period_end": "2026-09-30", "filed": "2026-10-28",
            "form": "10-Q", "accession": "fixture-filing", "audit": "verbose details"}
    assert fact_metadata_preview({"revenue": fact}) == {"revenue": {key: value for key, value in fact.items() if key != "audit"}}


def test_sec_tool_payload_becomes_rows_without_losing_period_units_or_missing_values(sec_payload):
    data, ref = record(sec_payload, "get_sec_company_facts_quarterly")
    before = deepcopy(data.records[ref])

    rows = data.rows(ref)

    assert [(row["period_end"], row["revenue"], row["eps"]) for row in rows] == [
        ("2025-06-30", 100.0, 1.55), ("2025-03-31", 90.0, 1.42)]
    assert rows[0]["net_income"] is None
    assert rows[0]["fact_metadata"]["net_income"] is None
    assert rows[0]["fact_metadata"]["revenue"]["unit"] == "USD"
    assert rows[0]["fact_metadata"]["eps"]["unit"] == "USD/shares"
    assert rows[0]["fact_metadata"]["eps"]["period_start"] == "2025-04-01"
    assert rows[0]["fact_metadata"]["eps"]["filed"] == "2025-08-01"
    assert rows[0]["source"] == "sec_companyfacts"
    assert rows[0]["currency"] == "USD" and rows[0]["frequency"] == "quarterly"
    rows[0]["fact_metadata"]["eps"]["unit"] = "modified"
    assert data.records[ref] == before


def test_sec_rows_can_be_indexed_and_charted_with_original_source_links(sec_payload):
    data, ref = record(sec_payload, "get_sec_company_facts_quarterly")

    result = analyze_dataset(data, ref, "indexed_comparison", {"value": "revenue", "date": "period_end"})
    artifact = render_chart(data, result["data_refs"][0], "季度收入", "bar", "period_end", [{"field": "revenue", "unit": "USD"}])

    assert result["status"] == "ok"
    assert [row["indexed"] for row in result["rows"]] == pytest.approx([100.0, 90.0])
    assert artifact["data"]["rows"][1]["fact_metadata"]["revenue"] == sec_payload["fact_metadata"]["revenue"][1]
    assert set(data.source_refs(ref)).issubset(artifact["source_refs"])


def test_earnings_multiple_tables_require_explicit_selection(earnings_payload):
    data, ref = record(earnings_payload, "get_earnings_estimates")

    result = analyze_dataset(data, ref, "indexed_comparison", {"value": "avg", "date": "period"})

    assert result["status"] == "unavailable" and result["error"] == "dataset_table_required"
    assert result["available_tables"] == ["earnings_estimate", "eps_trend", "eps_revisions"]
    assert result["required_parameters"] == ["table"]
    assert len(data.records) == 1


@pytest.mark.parametrize("table,field,other_field,expected", [
    ("earnings_estimate", "avg", "current", [100.0, 150.0]),
    ("eps_trend", "current", "avg", [100.0, 150.0]),
    ("eps_revisions", "upLast30days", "avg", [100.0, 200.0]),
])
def test_earnings_selected_table_keeps_its_own_fields_and_periods(earnings_payload, table, field, other_field, expected):
    data, ref = record(earnings_payload, "get_earnings_estimates")

    result = analyze_dataset(data, ref, "indexed_comparison", {"table": table, "value": field, "date": "period"})

    assert result["status"] == "ok"
    assert [row["period"] for row in result["rows"]] == ["0q", "+1q"]
    assert [row["indexed"] for row in result["rows"]] == pytest.approx(expected)
    assert all(other_field not in row and row["source_table"] == table for row in result["rows"])
    assert all(row["source"] == "yfinance" and row["as_of"] == earnings_payload["as_of"] for row in result["rows"])
    assert all("currency" not in row for row in result["rows"])  # 预期接口未提供币种，不补猜测值。


def test_empty_selected_earnings_table_does_not_fall_back_to_another_table(earnings_payload):
    earnings_payload["earnings_estimate"] = []
    data, ref = record(earnings_payload, "get_earnings_estimates")

    result = analyze_dataset(data, ref, "indexed_comparison", {"table": "earnings_estimate", "value": "avg", "date": "period"})

    assert result["error"] == "dataset_has_no_rows"
    assert len(data.records) == 1


def test_misaligned_sec_metric_arrays_are_not_truncated_or_filled(sec_payload):
    sec_payload["eps"] = [1.55]
    data, ref = record(sec_payload, "get_sec_company_facts_quarterly")

    with pytest.raises(DatasetRowsError, match="dataset_columns_misaligned"):
        data.rows(ref)
    result = analyze_dataset(data, ref, "indexed_comparison", {"value": "eps", "date": "period_end"})
    assert result["status"] == "unavailable" and result["error"] == "dataset_columns_misaligned"
    assert len(data.records) == 1


def test_valuation_uses_explicit_assumptions_without_requiring_tabular_rows():
    data, ref = record({"source": "fixture", "forwardEps": 4.0, "currency": "USD"}, "get_company_info")
    assert data.rows(ref) == []

    result = analyze_dataset(data, ref, "valuation_scenarios", {"eps": 4, "multiples": [20, 30], "currency": "USD"})

    assert result["status"] == "ok"
    assert [row["scenario_price"] for row in result["rows"]] == [80, 120]
    assert result["method"]["kind"] == "assumption"
    assert set(data.source_refs(ref)).issubset(data.source_refs(result["data_refs"][0]))
    with pytest.raises(ValueError, match="dataset_not_found_in_this_run"):
        analyze_dataset(data, "other-run", "valuation_scenarios", {"eps": 4})


def test_unsupported_operation_and_missing_columns_explain_available_choices(sec_payload):
    data, ref = record(sec_payload, "get_sec_company_facts_quarterly")

    unsupported = analyze_dataset(data, ref, "correlation")
    missing = analyze_dataset(data, ref, "indexed_comparison")

    assert unsupported["error"] == "analysis_operation_unsupported"
    assert "indexed_comparison" in unsupported["supported_operations"]
    assert missing["error"] == "comparison_columns_missing"
    assert {"period_end", "revenue", "eps"}.issubset(missing["available_columns"])
    assert len(data.records) == 1


@pytest.mark.parametrize('wrapper', [lambda rows: {'rows_df': rows}, lambda rows: {'chart_dataset': {'rows': rows}}])
def test_python_named_result_table_can_be_charted(wrapper):
    data, ref = record(wrapper([{'date': '2026-11-05', 'close': 10}, {'date': '2026-11-06', 'close': 12}]), 'run_analysis_code')
    chart = render_chart(data, ref, '收盘价', 'line', 'date', [{'field': 'close'}])
    assert [row['close'] for row in chart['data']['rows']] == [10, 12]


def test_python_multiple_tables_require_choice_and_missing_columns_are_explained():
    data, ref = record({'first': [{'date': '2026-11-06', 'close': 10}], 'second': [{'date': '2026-11-06', 'close': 12}]}, 'run_analysis_code')
    with pytest.raises(DatasetRowsError) as missing:
        render_chart(data, ref, '收盘价', 'line', 'date', [{'field': 'close'}])
    assert missing.value.details['available_tables'] == ['first', 'second']
    chart = render_chart(data, ref, '收盘价', 'line', 'date', [{'field': 'close'}], table='second')
    assert chart['data']['rows'][0]['close'] == 12
    with pytest.raises(DatasetRowsError) as columns:
        render_chart(data, ref, '收盘价', 'line', 'wrong', [{'field': 'close'}], table='second')
    assert columns.value.details['available_columns'] == ['date', 'close']


def test_latest_two_statistics_are_sorted_and_do_not_use_the_whole_history():
    data, ref = record({'rows': [{'period_end': '2026-07-26', 'revenue': 96221000000},
                                {'period_end': '2026-04-26', 'revenue': 81615000000},
                                {'period_end': '2026-01-25', 'revenue': 50000000000}]}, 'get_sec_company_facts_quarterly')
    result = analyze_dataset(data, ref, 'series_statistics', {'date': 'period_end', 'value': 'revenue', 'latest_n': 2})
    row = result['rows'][0]
    assert row['observations'] == 2 and row['difference'] == 14606000000
    assert row['return_ratio'] == pytest.approx(14606000000 / 81615000000)
    assert result['method']['start'].startswith('2026-04-26')


def test_comparison_stats_distinguish_final_leader_from_always_leading():
    data, ref = record({'ticker': 'NVDA', 'rows': [{'date': d, 'close': v} for d, v in [('2026-01-01', 100), ('2026-01-02', 110), ('2026-01-03', 105)]]}, 'get_stock_historical_data')
    data.records[ref]['inputs']['ticker'] = 'NVDA'
    other = data.record('get_stock_historical_data', {'ticker': 'AMD'}, {'rows': [{'date': d, 'close': v} for d, v in [('2026-01-01', 100), ('2026-01-02', 101), ('2026-01-03', 120)]]})
    output = analyze_dataset(data, ref, 'indexed_comparison', {'other_dataset_refs': [other]})
    stats = output['comparison_stats']
    assert stats['lead_days'] == {'NVDA': 1, 'AMD': 1, 'tie': 1}
    assert stats['series']['NVDA']['declining_periods'] == 1
    assert stats['strictly_increasing'] == {'NVDA': False, 'AMD': True}
    assert stats['crossovers'] == [{'left': 'NVDA', 'right': 'AMD', 'count': 1, 'dates': ['2026-01-03'], 'dates_truncated': False}]


def test_comparison_crossover_ignores_initial_tie_and_returns_to_same_leader():
    data = RunData('u', 's', 'r', '比较')
    refs = []
    for ticker, values in [('AAPL', [100, 102, 100, 103, 99, 100, 101]), ('MSFT', [100]*7)]:
        refs.append(data.record('get_stock_historical_data', {'ticker': ticker}, {
            'rows': [{'date': f'2026-01-{index+1:02d}', 'close': value} for index, value in enumerate(values)]}))
    output = analyze_dataset(data, refs[0], 'indexed_comparison', {'other_dataset_refs': [refs[1]]})
    assert output['comparison_stats']['crossovers'] == [{'left': 'AAPL', 'right': 'MSFT', 'count': 2,
                                                        'dates': ['2026-01-05', '2026-01-07'], 'dates_truncated': False}]


def test_bounded_comparison_projection_preserves_full_crossover_dates_for_readback():
    import json
    from backend.agent_runtime.context import tokens
    from backend.agent_runtime.envelope import ToolResult, to_model
    dates = ['2026-01-06', '2026-01-13', '2026-02-05', '2026-03-19']
    output = {'rows': [{'date': f'2026-01-{i%28+1:02d}', 'a': i, 'b': i+1} for i in range(215)],
              'comparison_stats': {'crossovers': [{'left': 'NVDA', 'right': 'AMD', 'count': 4, 'dates': dates, 'dates_truncated': False}]}}
    data, ref = record(output, 'run_analysis_code')
    result = ToolResult(status='ok', kind='computation', data=output)
    projection = to_model(result, 1000, handle=ref)
    assert tokens(projection) <= 1000 and ref in projection
    assert result.data['comparison_stats']['crossovers'][0]['dates'] == dates
    raw = ''.join(data.read(ref, offset, 8000)['content'] for offset in range(0, data.read(ref)['total_chars'], 8000))
    assert json.loads(raw)['output']['comparison_stats']['crossovers'][0]['dates'] == dates


def test_chart_reports_leading_gaps_without_filling_them():
    rows = [{'date': f'2026-10-{n+1:02d}', 'close': 100+n, 'ma20': None if n < 19 else 109.5+n-19} for n in range(23)]
    data, ref = record({'rows': rows}, 'run_analysis_code')
    chart = render_chart(data, ref, '20日均线', 'line', 'date', [{'field': 'close'}, {'field': 'ma20', 'name': '20日均线'}])
    assert chart['coverage']['ma20'] == {'points': 23, 'valid': 4, 'missing': 19, 'leading_missing': 19,
                                       'first_valid': '2026-10-20', 'last_valid': '2026-10-23'}
    assert chart['coverage']['close']['missing'] == 0
    assert chart['data']['rows'] == rows and '19个缺失点' in chart['limitations'][0]


@pytest.mark.asyncio
async def test_read_financial_rows_preserves_metadata_and_bounds_model_projection(tmp_path, monkeypatch):
    from backend.tests.test_agent_runtime import execute, runtime
    from backend.agent_runtime.context import tokens
    monkeypatch.setenv('FINSIGHT_ACTION_STORE', str(tmp_path / 'actions.sqlite'))
    rt, _ = runtime(tmp_path, [])
    ref = rt.data.record('get_sec_company_facts_quarterly', {'ticker': 'NVDA'}, {
        'source': 'sec_companyfacts', 'period_ends': ['2026-07-26', '2026-04-26'],
        'revenue': [96221000000, 81615000000], 'fact_metadata': {'revenue': [
            {'unit': 'USD', 'audit': 'x' * 20000}, {'unit': 'USD', 'audit': 'x' * 20000}]}})
    original = deepcopy(rt.data.records[ref])
    result = await execute(rt, 'read_data', {'handle': ref})
    projection = rt.registry.model_text(result, 2000)
    assert result.status == 'ok' and tokens(projection) <= 2000
    assert 'revenue (USD)' in projection and '96221000000' in projection
    assert 'audit' not in projection
    assert result.data['rows'][0]['fact_metadata']['revenue']['audit'] == 'x' * 20000
    metadata = await execute(rt, 'read_data', {'handle': ref, 'columns': ['fact_metadata']})
    assert metadata.status == 'ok'
    assert metadata.data['rows'][0]['fact_metadata']['revenue'] == {'unit': 'USD', 'audit': 'x' * 20000}
    assert rt.data.records[ref] == original
    await rt.close()

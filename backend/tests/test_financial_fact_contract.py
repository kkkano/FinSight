"""无网络 fixture：会计定义、主体、期间、单位和来源不可在适配时改变。"""
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.agents.fundamental_agent import FundamentalAgent
from backend.agents.macro_agent import MacroAgent
from backend.agents.news_agent import NewsAgent
from backend.tools import financial, local_disclosure, macro, sec
from backend.tools.financial_facts import search_line_is_noise


def _sec_entry(value, *, start="2026-05-03", end="2026-08-01", filed="2026-08-25", **extra):
    return {"val": value, "start": start, "end": end, "filed": filed, "form": "10-Q", "fp": "Q2", "accn": "0001-26-001", **extra}


@pytest.mark.parametrize("reverse", [False, True])
def test_quarterly_fact_selection_ignores_ytd_annual_and_array_order(reverse):
    entries = [
        _sec_entry(50),
        _sec_entry(95, start="2026-02-01"),
        _sec_entry(180, start="2025-08-03", form="10-K", fp="FY", filed="2027-01-01"),
        _sec_entry(999, start=None),
    ]
    if reverse:
        entries.reverse()
    payload = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": entries}}}}}
    result = sec._extract_companyfacts_facts(payload, concepts=("Revenues",), unit_candidates=("USD",), subject="NVDA", metric="revenue")

    fact = result["2026-08-01"]
    assert fact.value == 50
    assert fact.period_start == "2026-05-03"
    assert fact.period_end == "2026-08-01"
    assert fact.subject == "NVDA" and fact.unit == "USD"
    assert fact.frequency == "quarterly" and fact.source == "sec_companyfacts"


def test_quarterly_eps_is_not_derived_from_ytd():
    payload = {"facts": {"us-gaap": {"EarningsPerShareDiluted": {"units": {"USD/shares": [_sec_entry(4.5, start="2026-02-01")]}}}}}
    assert sec._extract_companyfacts_metric(payload, concepts=("EarningsPerShareDiluted",), unit_candidates=("USD/shares",)) == {}


def test_conflicting_same_version_quarter_values_remain_missing():
    payload = {"facts": {"us-gaap": {"Revenues": {"units": {"USD": [_sec_entry(50), _sec_entry(51)]}}}}}
    assert sec._extract_companyfacts_metric(payload, concepts=("Revenues",), unit_candidates=("USD",)) == {}


def test_sec_output_retains_actual_ends_and_instant_balance(monkeypatch):
    monkeypatch.setenv("SEC_USER_AGENT", "FinSight test@example.com")
    monkeypatch.setattr(sec, "_load_ticker_map", lambda _: {"NVDA": {"cik": "0001045810", "title": "NVIDIA"}})
    monkeypatch.setattr(sec, "_fetch_companyfacts", lambda *_: {"cik": 1045810, "facts": {"us-gaap": {
        "Revenues": {"units": {"USD": [_sec_entry(50)]}},
        "Assets": {"units": {"USD": [{"end": "2026-08-01", "val": 200, "form": "10-Q", "filed": "2026-08-25"}]}},
        "NetCashProvidedByUsedInOperatingActivities": {"units": {"USD": [_sec_entry(30, start="2026-02-01")]}},
    }}})
    result = sec.get_sec_company_facts_quarterly("NVDA")
    assert result["periods"] == result["period_ends"] == ["2026-08-01"]
    assert result["total_assets"] == [200]
    assert result["operating_cash_flow"] == [None]
    assert result["fact_metadata"]["total_assets"][0]["frequency"] == "instant"
    assert result["fact_metadata"]["revenue"][0]["filed"] == "2026-08-25"
    converted = financial._convert_sec_companyfacts_payload(result)
    assert converted["financials"]["columns"] == ["2026-08-01"]
    assert converted["financials"]["currency"] == "USD"


def test_sec_fallback_does_not_invent_calendar_end_for_fiscal_label():
    assert financial._convert_sec_companyfacts_payload({"ticker": "NVDA", "periods": ["2026Q2"], "revenue": [50]}) is None


def _table(names, values, *, columns=None, frequency="quarterly", currency="USD"):
    columns = columns or ["2026-08-01", "2026-05-02"]
    return {"columns": columns, "index": names, "data": [dict(zip(columns, row)) for row in values], "frequency": frequency, "currency": currency}


@pytest.mark.parametrize("reverse", [False, True])
def test_accounting_alias_priority_rejects_cost_ebitda_and_alternate_net_income(reverse):
    rows = [
        ("Reconciled Cost Of Revenue", [24, 20]), ("Total Revenue", [88, 80]),
        ("Net Income From Continuing Operations", [59, 55]), ("Net Income", [57, 52]),
        ("EBITDA", [65, 60]), ("Operating Income", [61, 58]),
    ]
    if reverse:
        rows.reverse()
    agent = object.__new__(FundamentalAgent)
    result = agent._build_normalized_metrics({"financials": _table([name for name, _ in rows], [value for _, value in rows])})["metrics"]
    assert [result[key]["latest"] for key in ("revenue", "net_income", "operating_income")] == [88, 57, 61]


def test_unsupported_accounting_rows_do_not_become_facts_or_claims():
    agent = object.__new__(FundamentalAgent)
    normalized = agent._build_normalized_metrics({"financials": _table(["Reconciled Cost Of Revenue", "EBITDA"], [[24, 20], [65, 60]])})
    assert normalized["metrics"]["revenue"]["latest"] is None
    assert normalized["metrics"]["operating_income"]["latest"] is None
    assert agent._build_native_claims(query="财报", ticker="NVDA", normalized=normalized, evidence=[], risks=[], confidence=0.8, source_ids=[]) == []
    assert "[数据缺失]" in agent._deterministic_summary({"financials": {"financials": _table(["EBITDA"], [[65, 60]])}})


def test_growth_is_aligned_by_real_dates_and_not_by_column_position():
    agent = object.__new__(FundamentalAgent)
    columns = ["2026-08-01", "2025-08-02", "2026-05-02"]
    result = agent._build_normalized_metrics({"financials": _table(["Total Revenue"], [[150, 100, 120]], columns=columns)})["metrics"]["revenue"]
    assert result["latest_period"] == "2026-08-01"
    assert result["yoy"] == pytest.approx(0.5)
    assert result["qoq"] == pytest.approx(0.25)
    assert result["yoy_period"] == "2025-08-02"


def test_two_quarters_do_not_have_year_over_year_growth():
    agent = object.__new__(FundamentalAgent)
    result = agent._build_normalized_metrics({"financials": _table(["Total Revenue"], [[150, 120]])})["metrics"]["revenue"]
    assert result["qoq"] == pytest.approx(0.25)
    assert result["yoy"] is None and result["yoy_period"] is None


def test_missing_intermediate_quarter_does_not_become_qoq():
    agent = object.__new__(FundamentalAgent)
    result = agent._build_normalized_metrics({"financials": _table(["Total Revenue"], [[150, 100]], columns=["2026-08-01", "2026-02-01"])})["metrics"]["revenue"]
    assert result["qoq"] is None


def test_cross_frequency_cashflow_is_missing_even_if_end_matches():
    agent = object.__new__(FundamentalAgent)
    result = agent._build_normalized_metrics({
        "financials": _table(["Total Revenue"], [[150, 120]], currency="CNY"),
        "cashflow": _table(["Operating Cash Flow"], [[300, 200]], columns=["2026-08-01", "2025-08-02"], frequency="annual"),
    })["metrics"]
    assert result["operating_cash_flow"]["latest"] is None
    assert result["operating_cash_flow"]["missing_reason"] == "statement_frequency_mismatch"
    assert "CNY" in agent._format_metric_sentence("营收", result["revenue"])
    assert "$" not in agent._format_metric_sentence("营收", result["revenue"])


def test_yfinance_statement_frequency_is_explicit_and_prefers_quarters(monkeypatch):
    table = pd.DataFrame({pd.Timestamp("2026-08-01"): [50]}, index=["Total Revenue"])
    ticker = SimpleNamespace(quarterly_income_stmt=table, quarterly_balance_sheet=table, quarterly_cashflow=table, info={"financialCurrency": "HKD"})
    monkeypatch.setattr(financial, "create_ticker", lambda _: ticker)
    result = financial._fetch_financials_from_yfinance("0700.HK")
    assert all(result[key]["frequency"] == "quarterly" for key in ("financials", "balance_sheet", "cashflow"))
    assert result["currency"] == "HKD"


@pytest.mark.parametrize("body,expected", [
    ("证券代码：600519 贵州茅台股份有限公司 2026年度公告", "document_stock_code"),
    ("证券代码：603993 洛阳钼业 公告中提到贵州茅台", None),
    ("本网站搜索结果 贵州茅台 2026年公告", None),
])
def test_local_issuer_checks_declared_stock_code_before_mentions(body, expected):
    # 搜索摘要不调用此原文核验函数；原文仅公司名称路径需声明式名称。
    if body.startswith("本网站"):
        assert local_disclosure._issuer_identity(body, "600519.SS") is None
    else:
        assert local_disclosure._issuer_identity(body, "600519.SS") == expected


def test_local_search_results_remain_discoveries_without_verified_document(monkeypatch):
    monkeypatch.setattr(local_disclosure, "search", lambda _: "1. 贵州茅台年报\nhttps://www.cninfo.com.cn/new/disclosure/detail?id=1")
    monkeypatch.setattr(local_disclosure, "_fetch_disclosure_text", lambda _: "证券代码：603993 洛阳钼业股份有限公司 年报")
    result = local_disclosure.get_local_market_filings("600519.SS")
    assert result["filings"] == []
    assert result["discovery_candidates"][0]["issuer_verified"] is False
    assert result["error"] == "issuer_verified_filings_unavailable"


def test_hk_zero_padded_stock_code_is_bound_to_issuer(monkeypatch):
    monkeypatch.setattr(local_disclosure, "search", lambda _: "1. Tencent Holdings annual results\nhttps://www.hkexnews.hk/listedco/listconews/sehk/2026/report.pdf")
    monkeypatch.setattr(local_disclosure, "_fetch_disclosure_text", lambda _: "Tencent Holdings Limited Stock Code: 00700 Annual Results")
    result = local_disclosure.get_local_market_filings("0700.HK")
    assert len(result["filings"]) == 1
    assert result["filings"][0]["issuer_ticker"] == "0700.HK"


@pytest.mark.parametrize("oversized", [False, True])
def test_disclosure_original_fetch_is_bounded_and_closes_response(monkeypatch, oversized):
    closed = []
    content = b"x" * 3_000_001 if oversized else "<html><h1>证券代码：600519</h1></html>".encode("utf-8")
    response = SimpleNamespace(status_code=200, iter_content=lambda **_: iter([content]), close=lambda: closed.append(True))
    monkeypatch.setattr(local_disclosure, "_http_get_no_retry", lambda *_, **kwargs: response)
    result = local_disclosure._fetch_disclosure_text("https://www.cninfo.com.cn/fixture.html")
    assert closed == [True]
    assert result == "" if oversized else "600519" in result


@pytest.mark.parametrize("line", ["Search Results (Exa):", "搜索结果：", "------------------------", "URL:"])
def test_search_format_lines_are_not_news(line):
    assert search_line_is_noise(line)
    assert object.__new__(NewsAgent)._parse_search_results(line, "AAOI") == []


def test_news_search_parser_preserves_title_url_and_unverified_date_hint():
    raw = "Search Results (Exa):\n======================\n1. AAOI announces new production agreement\nPublished 2026-10-02\nhttps://example.com/aaoi\n"
    result = object.__new__(NewsAgent)._parse_search_results(raw, "AAOI")
    assert len(result) == 1
    assert result[0]["title"] == "AAOI announces new production agreement"
    assert result[0]["url"] == "https://example.com/aaoi"
    assert result[0]["date_hint"] == "2026-10-02"
    assert result[0]["published_at"] is None
    assert result[0]["event_quality"]["verification"] == "discovery_only"


def test_fred_cpi_requests_yoy_transformation_and_preserves_unit_date(monkeypatch):
    monkeypatch.setattr(macro, "FRED_API_KEY", "fixture-key")
    requests = []
    def fake_get(_url, *, params, **_kwargs):
        requests.append(params)
        return SimpleNamespace(status_code=200, json=lambda: {"observations": [{"date": "2026-08-01", "value": "3.2"}]})
    monkeypatch.setattr(macro, "_http_get", fake_get)
    result = macro.get_fred_data()
    assert next(params for params in requests if params["series_id"] == "CPIAUCSL")["units"] == "pc1"
    assert result["indicator_metadata"]["cpi"]["definition"] == "inflation_yoy"
    assert result["indicator_metadata"]["cpi"]["period_end"] == "2026-08-01"
    assert "同比" in result["cpi_formatted"]
    assert object.__new__(MacroAgent)._extract_numeric_metrics(result)["cpi"] == 3.2


def test_macro_agent_never_interprets_untyped_cpi_index_as_percent():
    agent = object.__new__(MacroAgent)
    assert "cpi" not in agent._extract_numeric_metrics({"cpi": 329.4})
    assert "cpi" not in agent._extract_numeric_metrics({"cpi": 329.4, "indicator_metadata": {"cpi": {"unit": "index", "definition": "price_index"}}})
    assert "cpi" not in agent._extract_numeric_metrics_from_text("CPI increased 0.3% this month")
    assert agent._extract_numeric_metrics_from_text("CPI inflation 3.2% year-over-year")["cpi"] == 3.2

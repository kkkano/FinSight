"""无网络 fixture：会计定义、主体、期间、单位和来源不可在适配时改变。"""
from types import SimpleNamespace

import pandas as pd
import pytest

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
    assert result["cpi"] == 3.2

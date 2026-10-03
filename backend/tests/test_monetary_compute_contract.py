"""估值只比较已声明同币种数据，不隐式把市值或财务数字当美元。"""
from types import SimpleNamespace

import pytest

from backend.dashboard import data_service
from backend.tools.financial_facts import parse_profile_market_cap
from backend.tools.python_compute import run_python_compute


def _valuation(company_currency, financial_currency):
    return run_python_compute(
        dataset_refs=["step:get_company_info", "step:get_sec_company_facts_quarterly"],
        operation="valuation_sanity", params={},
        datasets={
            "step:get_company_info": f"- Market Cap: {company_currency} 5,000\n- Currency: {company_currency}",
            "step:get_sec_company_facts_quarterly": {
                "currency": financial_currency, "frequency": "quarterly",
                "periods": ["2026-08-01", "2026-05-02"],
                "revenue": [125.0, 100.0], "net_income": [15.0, 10.0],
            },
        },
    )


def test_hkd_market_cap_cny_financials_cannot_produce_ps_or_pe():
    result = _valuation("HKD", "CNY")
    assert result["metrics"]["market_cap"] == 5000
    assert result["metrics"]["annualized_revenue"] == 500
    assert result["metrics"]["price_to_sales"] is None
    assert result["metrics"]["price_to_earnings"] is None
    assert result["metric_metadata"]["market_cap"]["currency"] == "HKD"
    assert result["metric_metadata"]["annualized_revenue"]["currency"] == "CNY"
    assert any("mismatched" in warning for warning in result["warnings"])


def test_same_currency_native_sec_arrays_produce_ratios_with_actual_period():
    result = _valuation("USD", "USD")
    assert result["metrics"]["price_to_sales"] == 10
    assert result["metrics"]["price_to_earnings"] == pytest.approx(83.3333)
    assert result["metric_metadata"]["annualized_revenue"]["period_end"] == "2026-08-01"
    assert result["metric_metadata"]["annualized_revenue"]["definition"] == "single_quarter_times_four"


def test_legacy_dollar_sign_alone_does_not_prove_currency():
    amount = parse_profile_market_cap("- Market Cap: $5.0B")
    assert amount.value == 5_000_000_000
    assert amount.currency is None


def test_conflicting_profile_currency_declarations_are_rejected():
    amount = parse_profile_market_cap("- Market Cap: HKD 5,000\n- Currency: USD")
    assert amount.value is None and amount.currency is None


def test_finnhub_dashboard_preserves_hkd_and_million_scale(monkeypatch):
    monkeypatch.setattr(data_service, "_finnhub_request", lambda path, _: {"marketCapitalization": 1250.5, "currency": "HKD"} if path == "stock/profile2" else {"metric": {"peTTM": 20}})
    result = data_service._fetch_valuation_from_finnhub("0700.HK")
    assert result["market_cap"] == 1_250_500_000
    assert result["market_cap_currency"] == result["currency"] == "HKD"


def test_finnhub_dashboard_does_not_relabel_untyped_market_cap(monkeypatch):
    monkeypatch.setattr(data_service, "_finnhub_request", lambda path, _: {"marketCapitalization": 1250.5} if path == "stock/profile2" else {"metric": {"peTTM": 20}})
    result = data_service._fetch_valuation_from_finnhub("0700.HK")
    assert result["market_cap"] is None
    assert result["market_cap_currency"] is None
    assert result["trailing_pe"] == 20


def test_yahoo_dashboard_keeps_quote_currency_without_financial_currency_substitution(monkeypatch):
    monkeypatch.setattr(data_service, "_create_ticker", lambda _: SimpleNamespace(info={"marketCap": 4000, "currency": "HKD", "financialCurrency": "CNY"}))
    monkeypatch.setattr(data_service, "_fetch_valuation_from_cn_hk_market", lambda _: None)
    result = data_service.fetch_valuation("0700.HK")
    assert result["market_cap"] == 4000
    assert result["currency"] == "HKD"


def test_cn_hk_dashboard_requires_provider_currency_for_market_cap(monkeypatch):
    import backend.tools.cn_hk_market as market

    monkeypatch.setattr(market, "fetch_cn_hk_quote_metrics", lambda _: {"market_cap": 4000, "trailing_pe": 20})
    result = data_service._fetch_valuation_from_cn_hk_market("600519.SS")
    assert result["market_cap"] is None
    assert result["currency"] is None

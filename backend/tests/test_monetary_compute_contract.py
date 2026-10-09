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


@pytest.mark.parametrize("symbol,currency", [("0700.HK", "HKD"), ("600519.SS", "CNY"), ("AAPL", "USD")])
def test_valuation_keeps_declared_quote_currency_and_source_time_in_all_markets(monkeypatch, symbol, currency):
    monkeypatch.setattr(data_service, "_create_ticker", lambda _: SimpleNamespace(info={
        "marketCap": 4000, "currency": currency, "financialCurrency": "EUR", "trailingPE": 20,
        "regularMarketTime": 1791489600, "fiftyTwoWeekHigh": 120, "fiftyTwoWeekLow": 80,
    }))
    monkeypatch.setattr(data_service, "_fetch_valuation_from_cn_hk_market", lambda _: None)
    result = data_service.fetch_valuation(symbol)
    from backend.dashboard.snapshot import _build_meta
    import time
    meta = _build_meta(provider="unknown", source_type="fundamental", payload=result,
                       started_at=time.perf_counter(), fallback_reason=None)
    assert result["currency"] == result["market_cap_currency"] == currency
    assert meta["provider"] == "yfinance" and meta["status"] == "ok"
    assert meta["as_of"] == result["as_of"] and meta["as_of"]


def test_local_valuation_does_not_lose_fallback_provider_or_claim_complete_metadata(monkeypatch):
    import backend.tools.cn_hk_market as market
    monkeypatch.setattr(market, "fetch_cn_hk_quote_metrics", lambda _: {
        "market_cap": 4000, "price_to_book": 2.9, "source": "eastmoney_quote",
    })
    result = data_service._fetch_valuation_from_cn_hk_market("0700.HK")
    assert result["provider"] == "eastmoney_quote"
    assert result["status"] == "degraded" and result["as_of"] is None
    assert result["market_cap"] is None and result["currency"] is None


def test_local_valuation_merges_explicit_quote_currency_for_price_fields(monkeypatch):
    import backend.tools.cn_hk_market as market
    monkeypatch.setattr(market, "fetch_cn_hk_quote_metrics", lambda _: {
        "market_cap": 4000, "week52_high": 500, "week52_low": 300,
        "source": "eastmoney_quote",
    })
    monkeypatch.setattr(data_service, "_create_ticker", lambda _: SimpleNamespace(info={"currency": "HKD"}))
    result = data_service.fetch_valuation("0700.HK")
    assert result["currency"] == "HKD"
    assert result["market_cap"] is None


def test_eastmoney_dynamic_pe_is_not_a_zero_ttm_metric(monkeypatch):
    import backend.tools.cn_hk_market as market
    monkeypatch.setattr(market, "_eastmoney_get_json", lambda *_args: {"data": {
        "f59": 2, "f43": 41920, "f116": 4000, "f162": 0, "f167": 291,
    }})
    result = market.fetch_cn_hk_quote_metrics("0700.HK")
    assert result["trailing_pe"] is None

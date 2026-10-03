"""公司市值使用供应商报价币种；未知数值和单位必须保持缺失。"""
from types import SimpleNamespace

import pytest

from backend.agents.fundamental_agent import FundamentalAgent
from backend.tools import financial


@pytest.mark.parametrize("ticker,currency", [("0700.HK", "HKD"), ("600519.SS", "CNY"), ("NVDA", "USD")])
def test_yahoo_market_cap_uses_quote_currency_not_financial_currency(monkeypatch, ticker, currency):
    monkeypatch.setattr(financial, "create_ticker", lambda _: SimpleNamespace(info={
        "longName": "Fixture issuer", "currency": currency, "financialCurrency": "EUR", "marketCap": 4_000_000_000,
    }))
    result = financial.get_company_info(ticker)
    assert f"- Market Cap: {currency} 4,000,000,000" in result
    assert f"- Currency: {currency}" in result
    assert "$" not in result and "EUR" not in result
    parsed = object.__new__(FundamentalAgent)._parse_company_info(result)
    assert parsed["market_cap"] == f"{currency} 4,000,000,000"


@pytest.mark.parametrize("profile", [
    {"currency": "HKD"},
    {"currency": "HKD", "marketCap": None},
    {"currency": "HKD", "marketCap": 0},
    {"marketCap": 4_000_000_000, "financialCurrency": "USD"},
    {"currency": "USD", "marketCap": float("nan")},
])
def test_missing_cap_or_currency_is_explicit_and_not_zero_dollars(monkeypatch, profile):
    monkeypatch.setattr(financial, "create_ticker", lambda _: SimpleNamespace(info={"longName": "Fixture issuer", **profile}))
    result = financial.get_company_info("0700.HK")
    assert "- Market Cap: [数据缺失]" in result
    assert "$" not in result
    assert "- Market Cap: 0" not in result


def test_finnhub_market_cap_keeps_provider_currency_and_million_scale(monkeypatch):
    monkeypatch.setattr(financial, "create_ticker", lambda _: SimpleNamespace(info={}))
    monkeypatch.setattr(financial, "finnhub_client", SimpleNamespace(company_profile2=lambda **_: {
        "name": "Fixture issuer", "currency": "HKD", "marketCapitalization": 1250.5,
    }))
    result = financial.get_company_info("0700.HK")
    assert "- Market Cap: HKD 1,250,500,000" in result
    assert "- Currency: HKD" in result
    assert "$" not in result


@pytest.mark.parametrize("currency", ["CNY", None])
def test_alphavantage_market_cap_preserves_currency_or_declares_missing(monkeypatch, currency):
    monkeypatch.setattr(financial, "create_ticker", lambda _: SimpleNamespace(info={}))
    monkeypatch.setattr(financial, "finnhub_client", None)
    monkeypatch.setattr(financial, "_http_get", lambda *_, **__: SimpleNamespace(json=lambda: {
        "Symbol": "600519.SS", "Name": "Fixture issuer", "Currency": currency, "MarketCapitalization": "1200000000",
    }))
    result = financial.get_company_info("600519.SS")
    assert "- Market Cap: CNY 1,200,000,000" in result if currency else "- Market Cap: [数据缺失]" in result
    assert "$" not in result


def test_quote_minor_unit_is_not_silently_promoted_to_pounds():
    result = financial._company_market_cap_lines(1000, "GBp")
    assert "- Market Cap: GBp 1,000" in result
    assert "GBP" not in result

# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.graph.renderers.compare import _format_market_cap, _forward_eps_from_estimates, _parse_company_valuation, _valuation_evidence_by_ticker


def test_market_cap_uses_shared_currency_parser_and_never_assumes_dollar_unit():
    parsed = _parse_company_valuation("- Market Cap: HKD 4,000,000,000\n- Currency: HKD\n- Forward P/E: 20")
    assert parsed["market_cap"] == 4_000_000_000 and parsed["currency"] == "HKD"
    assert _format_market_cap(parsed["market_cap"], parsed["currency"]) == "HKD 4.00B"
    unknown = _parse_company_valuation("- Market Cap: $4,000,000,000")
    assert unknown["currency"] is None


def test_quarter_eps_is_not_divided_into_price_as_annual_forward_pe():
    payload = {"earnings_estimate": [{"period": "+1q", "avg": 2.0}, {"period": "+1y", "avg": 8.0}]}
    assert _forward_eps_from_estimates(payload) == (8.0, "+1y")


def test_forward_pe_is_not_derived_across_price_and_eps_currencies():
    state = {"subject": {"tickers": ["0700.HK"]}, "plan_ir": {"steps": [{"id": "eps", "name": "get_earnings_estimates", "inputs": {"ticker": "0700.HK"}}]}, "artifacts": {"step_results": {"eps": {"output": {"currency": "CNY", "earnings_estimate": [{"period": "+1y", "avg": 10.0}]}}}}}
    result = _valuation_evidence_by_ticker(state, prices={"0700.HK": {"price": 500.0, "currency": "HKD"}})
    assert "forward_pe" not in result["0700.HK"]

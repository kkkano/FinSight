from __future__ import annotations

import types

from backend.tools import financial


def test_convert_sec_companyfacts_payload_builds_agent_tables():
    payload = {
        "ticker": "MSFT",
        "periods": ["2025Q3", "2025Q2"],
        "revenue": [70.0, 65.0],
        "gross_profit": [48.0, 44.0],
        "operating_income": [30.0, 27.0],
        "net_income": [24.0, 22.0],
        "eps": [3.2, 3.0],
        "total_assets": [510.0, 500.0],
        "total_liabilities": [210.0, 205.0],
        "operating_cash_flow": [28.0, 26.0],
        "free_cash_flow": [22.0, 20.0],
        "error": None,
    }

    converted = financial._convert_sec_companyfacts_payload(payload)
    assert isinstance(converted, dict)
    assert converted.get("source") == "sec_companyfacts"
    assert converted.get("error") is None

    income = converted.get("financials") or {}
    assert income.get("columns") == ["2025-09-30", "2025-06-30"]
    assert "Total Revenue" in (income.get("index") or [])
    assert "Operating Income" in (income.get("index") or [])

    balance = converted.get("balance_sheet") or {}
    assert "Total Assets" in (balance.get("index") or [])
    assert "Total Liabilities" in (balance.get("index") or [])

    cashflow = converted.get("cashflow") or {}
    assert "Operating Cash Flow" in (cashflow.get("index") or [])
    assert "Free Cash Flow" in (cashflow.get("index") or [])


def test_get_financial_statements_uses_sec_fallback_when_yfinance_empty(monkeypatch):
    class EmptyTicker:
        def __init__(self, _ticker: str):
            self.financials = None
            self.income_stmt = None
            self.quarterly_financials = None
            self.quarterly_income_stmt = None
            self.balance_sheet = None
            self.quarterly_balance_sheet = None
            self.cashflow = None
            self.quarterly_cashflow = None

    monkeypatch.setattr(financial, "yf", types.SimpleNamespace(Ticker=EmptyTicker))
    monkeypatch.setattr(
        financial,
        "_fetch_financials_from_sec_companyfacts",
        lambda _ticker: {
            "ticker": "MSFT",
            "timestamp": "2026-02-24T00:00:00",
            "financials": {"columns": ["2025-09-30"], "index": ["Total Revenue"], "data": [{"2025-09-30": 70.0}]},
            "balance_sheet": None,
            "cashflow": None,
            "error": None,
            "warnings": ["fallback:sec_companyfacts"],
            "source": "sec_companyfacts",
        },
    )

    result = financial.get_financial_statements("MSFT")
    assert isinstance(result, dict)
    assert result.get("source") == "sec_companyfacts"
    assert result.get("error") is None
    assert "fallback:sec_companyfacts" in (result.get("warnings") or [])


def test_get_financial_statements_returns_error_when_all_sources_fail(monkeypatch):
    class EmptyTicker:
        def __init__(self, _ticker: str):
            self.financials = None
            self.income_stmt = None
            self.quarterly_financials = None
            self.quarterly_income_stmt = None
            self.balance_sheet = None
            self.quarterly_balance_sheet = None
            self.cashflow = None
            self.quarterly_cashflow = None

    monkeypatch.setattr(financial, "yf", types.SimpleNamespace(Ticker=EmptyTicker))
    monkeypatch.setattr(financial, "_fetch_financials_from_sec_companyfacts", lambda _ticker: None)

    result = financial.get_financial_statements("MSFT")
    assert isinstance(result, dict)
    assert result.get("source") != "sec_companyfacts"
    assert isinstance(result.get("error"), str) and result.get("error")

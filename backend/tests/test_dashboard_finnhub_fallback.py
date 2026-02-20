from __future__ import annotations

import sys
import types

import pandas as pd

from backend.dashboard import data_service
from backend.dashboard import peer_service


def test_fetch_valuation_uses_finnhub_fallback_when_yfinance_empty(monkeypatch):
    class EmptyTicker:
        def __init__(self, symbol: str):
            self.info = {}

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=EmptyTicker))
    monkeypatch.setattr(
        data_service,
        "_fetch_valuation_from_finnhub",
        lambda symbol: {"market_cap": 123.0, "trailing_pe": 20.0, "forward_pe": 18.0},
    )

    result = data_service.fetch_valuation("AAPL")
    assert isinstance(result, dict)
    assert result["market_cap"] == 123.0
    assert result["trailing_pe"] == 20.0


def test_fetch_financials_uses_finnhub_fallback_when_yfinance_missing(monkeypatch):
    class EmptyTicker:
        def __init__(self, symbol: str):
            self.quarterly_income_stmt = pd.DataFrame()
            self.quarterly_financials = pd.DataFrame()
            self.quarterly_balance_sheet = pd.DataFrame()
            self.quarterly_cashflow = pd.DataFrame()

    fallback_payload = {
        "periods": ["2025FY", "2024FY"],
        "revenue": [100.0, 90.0],
        "gross_profit": [50.0, 45.0],
        "operating_income": [20.0, 18.0],
        "net_income": [15.0, 14.0],
        "eps": [1.2, 1.1],
        "total_assets": [300.0, 280.0],
        "total_liabilities": [120.0, 110.0],
        "operating_cash_flow": [25.0, 24.0],
        "free_cash_flow": [10.0, 9.0],
    }

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=EmptyTicker))
    monkeypatch.setattr(
        data_service,
        "_fetch_financial_statements_from_finnhub",
        lambda symbol, periods=8: fallback_payload,
    )
    monkeypatch.setattr(
        data_service,
        "_fetch_financial_statements_from_sec_companyfacts",
        lambda symbol, periods=8: None,
    )

    result = data_service.fetch_financial_statements("AAPL")
    assert result == fallback_payload


def test_peer_service_uses_finnhub_when_yfinance_info_empty(monkeypatch):
    class EmptyTicker:
        def __init__(self, symbol: str):
            self.info = {}

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=EmptyTicker))
    monkeypatch.setattr(
        peer_service,
        "_fetch_single_peer_metrics_from_finnhub",
        lambda sym: {
            "symbol": sym,
            "name": sym,
            "trailing_pe": 30.0,
            "forward_pe": 25.0,
            "price_to_book": 5.0,
            "ev_to_ebitda": 12.0,
            "net_margin": 0.2,
            "roe": 0.3,
            "revenue_growth": 0.1,
            "dividend_yield": 0.01,
            "market_cap": 1_000_000_000.0,
        },
    )

    result = peer_service.fetch_peer_comparison("GOOGL", peers=["AAPL", "MSFT"])
    assert isinstance(result, dict)
    rows = result.get("peers") or []
    assert len(rows) == 3
    assert any((row.get("trailing_pe") or 0) > 0 for row in rows)


def test_resolve_peers_falls_back_to_default_list_when_sector_unknown(monkeypatch):
    class EmptyTicker:
        def __init__(self, symbol: str):
            self.info = {}

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=EmptyTicker))
    peers = peer_service.resolve_peers("ZZZZ", limit=4)
    assert len(peers) == 4
    assert all(p != "ZZZZ" for p in peers)


def test_fetch_financials_prefers_sec_companyfacts_before_finnhub(monkeypatch):
    class EmptyTicker:
        def __init__(self, symbol: str):
            self.quarterly_income_stmt = pd.DataFrame()
            self.quarterly_financials = pd.DataFrame()
            self.quarterly_balance_sheet = pd.DataFrame()
            self.quarterly_cashflow = pd.DataFrame()

    sec_payload = {
        "periods": ["2025Q3", "2025Q2"],
        "revenue": [100.0, 90.0],
        "gross_profit": [40.0, 35.0],
        "operating_income": [20.0, 18.0],
        "net_income": [15.0, 14.0],
        "eps": [1.5, 1.4],
        "total_assets": [300.0, 280.0],
        "total_liabilities": [120.0, 110.0],
        "operating_cash_flow": [30.0, 28.0],
        "free_cash_flow": [20.0, 18.0],
    }

    monkeypatch.setitem(sys.modules, "yfinance", types.SimpleNamespace(Ticker=EmptyTicker))
    monkeypatch.setattr(
        data_service,
        "_fetch_financial_statements_from_sec_companyfacts",
        lambda symbol, periods=8: sec_payload,
    )
    monkeypatch.setattr(
        data_service,
        "_fetch_financial_statements_from_finnhub",
        lambda symbol, periods=8: None,
    )

    result = data_service.fetch_financial_statements("AAPL")
    assert result == sec_payload


def test_fetch_financials_uses_cn_hk_route_for_cn_symbol(monkeypatch):
    payload = {
        "periods": ["2025Q3", "2025Q2"],
        "revenue": [130.0, 110.0],
        "gross_profit": [60.0, 50.0],
        "operating_income": [40.0, 35.0],
        "net_income": [25.0, 22.0],
        "eps": [2.5, 2.2],
        "total_assets": [500.0, 480.0],
        "total_liabilities": [100.0, 95.0],
        "operating_cash_flow": [50.0, 45.0],
        "free_cash_flow": [30.0, 28.0],
    }
    monkeypatch.setattr(
        data_service,
        "_fetch_financial_statements_from_cn_hk_market",
        lambda symbol, periods=8: payload,
    )

    result = data_service.fetch_financial_statements("600519.SS")
    assert result == payload


def test_resolve_peers_uses_market_specific_defaults():
    cn_peers = peer_service.resolve_peers("600519.SS", limit=3)
    hk_peers = peer_service.resolve_peers("0700.HK", limit=3)
    us_peers = peer_service.resolve_peers("AAPL", limit=3)

    assert cn_peers and all(p.endswith((".SS", ".SZ", ".BJ")) for p in cn_peers)
    assert hk_peers and all(p.endswith(".HK") for p in hk_peers)
    assert us_peers and all("." not in p for p in us_peers)

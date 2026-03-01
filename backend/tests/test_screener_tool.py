# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.tools import screener


class _DummyResponse:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


def test_screen_stocks_returns_config_error_without_api_key(monkeypatch):
    monkeypatch.setattr(screener, "FMP_API_KEY", "")

    result = screener.screen_stocks(market="US", filters={}, limit=10, page=1)

    assert result["success"] is False
    assert result["error"] == "FMP_API_KEY is not configured"
    assert result["count"] == 0


def test_screen_stocks_parses_items(monkeypatch):
    monkeypatch.setattr(screener, "FMP_API_KEY", "demo-key")

    def _fake_get(_url: str, params: dict, timeout: int):
        assert params["sort"] == "marketCap"
        assert params["order"] == "desc"
        return _DummyResponse(
            200,
            [
                {
                    "symbol": "AAPL",
                    "companyName": "Apple Inc.",
                    "sector": "Technology",
                    "industry": "Consumer Electronics",
                    "country": "US",
                    "exchangeShortName": "NASDAQ",
                    "price": 180.12,
                    "marketCap": 1000,
                    "volume": 250,
                    "beta": 1.2,
                    "lastAnnualDividend": 0.5,
                    "changesPercentage": 1.1,
                }
            ],
        )

    monkeypatch.setattr(screener, "_http_get", _fake_get)

    result = screener.screen_stocks(market="US", filters={"sector": "Technology"}, limit=20, page=2)

    assert result["success"] is True
    assert result["market"] == "US"
    assert result["page"] == 2
    assert result["count"] == 1
    assert result["items"][0]["symbol"] == "AAPL"
    assert result["items"][0]["price"] == 180.12


def test_screen_stocks_applies_cn_market_filter(monkeypatch):
    monkeypatch.setattr(screener, "FMP_API_KEY", "demo-key")

    captured = {}

    def _fake_get(_url: str, params: dict, timeout: int):
        captured.update(params)
        return _DummyResponse(200, [])

    monkeypatch.setattr(screener, "_http_get", _fake_get)

    result = screener.screen_stocks(market="CN", filters={}, limit=10, page=1)

    assert result["success"] is True
    assert captured.get("country") == "CN"
    assert captured.get("offset") == 0
    assert "coverage is limited" in str(result.get("capability_note") or "")

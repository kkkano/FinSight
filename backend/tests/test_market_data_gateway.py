# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

import pytest

from backend.services.market_data_gateway import (
    MarketDataGateway,
    MarketDataValidationError,
    validate_financial_payload,
    validate_kline_bars,
    validate_news_items,
    validate_quote_payload,
)


def _bars() -> list[dict[str, object]]:
    return [
        {
            "time": "2026-07-09 00:00",
            "open": 100.0,
            "high": 103.0,
            "low": 99.0,
            "close": 102.0,
            "volume": 1000.0,
        },
        {
            "time": "2026-07-10 00:00",
            "open": 102.0,
            "high": 105.0,
            "low": 101.0,
            "close": 104.0,
            "volume": 1200.0,
        },
    ]


def _payload(bars=None, *, interval: str = "1d") -> dict[str, object]:
    return {"kline_data": bars if bars is not None else _bars(), "interval": interval}


def test_gateway_uses_one_trusted_primary_and_exposes_provenance():
    calls: list[str] = []

    def primary(symbol: str, period: str, interval: str):
        calls.append(f"{symbol}:{period}:{interval}")
        return _payload(interval=interval)

    def secondary(*_args, **_kwargs):
        raise AssertionError("primary success must not call secondary")

    gateway = MarketDataGateway(
        providers={"primary": primary, "secondary": secondary},
        primary_provider="primary",
        secondary_provider="secondary",
        trusted_providers={"primary", "secondary"},
        cache_ttl_seconds=0,
    )

    result = gateway.get_kline("aapl", period="1mo", interval="1d")

    assert calls == ["AAPL:1mo:1d"]
    assert result["kline_data"] == _bars()
    assert result["provider"] == "primary"
    assert result["quality"] == "trusted"
    assert result["degraded"] is False
    assert result["error_code"] is None
    assert result["as_of"]
    assert isinstance(result["freshness_seconds"], int)
    assert result["attempted_providers"] == ["primary"]


def test_gateway_rejects_invalid_primary_and_calls_only_one_secondary():
    calls: list[str] = []

    def invalid_primary(*_args, **_kwargs):
        calls.append("primary")
        rows = _bars()
        rows[0] = rows[0] | {"high": 98.0}
        return _payload(rows)

    def secondary(*_args, **_kwargs):
        calls.append("secondary")
        return _payload()

    gateway = MarketDataGateway(
        providers={"primary": invalid_primary, "secondary": secondary},
        primary_provider="primary",
        secondary_provider="secondary",
        trusted_providers={"secondary"},
        cache_ttl_seconds=0,
    )

    result = gateway.get_kline("AAPL", period="1mo", interval="1d")

    assert calls == ["primary", "secondary"]
    assert result["provider"] == "secondary"
    assert result["quality"] == "trusted"
    assert result["degraded"] is True
    assert result["attempted_providers"] == ["primary", "secondary"]


def test_gateway_fails_closed_after_at_most_two_providers():
    calls: list[str] = []

    def unavailable(name: str):
        def fetch(*_args, **_kwargs):
            calls.append(name)
            return None

        return fetch

    gateway = MarketDataGateway(
        providers={
            "primary": unavailable("primary"),
            "secondary": unavailable("secondary"),
            "unused": unavailable("unused"),
        },
        primary_provider="primary",
        secondary_provider="secondary",
        trusted_providers={"primary", "secondary", "unused"},
        cache_ttl_seconds=0,
    )

    result = gateway.get_kline("AAPL", period="1mo", interval="1d")

    assert calls == ["primary", "secondary"]
    assert result["kline_data"] == []
    assert result["error_code"] == "market_data_unavailable"
    assert result["attempted_providers"] == calls
    assert "synthetic" not in result


@pytest.mark.parametrize(
    "bars",
    [
        [_bars()[0], _bars()[0]],
        [_bars()[1], _bars()[0]],
        [_bars()[0] | {"open": -1.0}],
        [_bars()[0] | {"low": 104.0}],
        [_bars()[0] | {"volume": -1.0}],
    ],
)
def test_kline_validation_rejects_duplicates_order_and_invalid_ohlcv(bars):
    with pytest.raises(MarketDataValidationError):
        validate_kline_bars(bars)


def test_price_production_path_contains_no_synthetic_ohlc_markers():
    source = (Path(__file__).parents[1] / "tools" / "price.py").read_text(encoding="utf-8")
    assert "price_fallback_hourly" not in source
    assert '"price_fallback"' not in source
    assert "stooq_intraday_stub" not in source


def test_stooq_daily_data_is_not_relabelled_as_hourly(monkeypatch):
    from backend.tools import price

    class Response:
        status_code = 200
        text = (
            "Date,Open,High,Low,Close,Volume\n"
            "2026-07-09,100,103,99,102,1000\n"
            "2026-07-10,102,105,101,104,1200\n"
        )

    monkeypatch.setattr(price, "_http_get", lambda *_args, **_kwargs: Response())

    assert price._fetch_with_stooq_history("AAPL", period="1mo", interval="1h") is None


def test_quote_contract_accepts_negative_change_and_exposes_provenance():
    gateway = MarketDataGateway(
        providers={},
        primary_provider="",
        cache_ttl_seconds=0,
        quote_providers={
            "primary": lambda _symbol: {
                "data": {"price": 205.0, "change": -2.5, "change_percent": -1.2},
                "as_of": "2026-07-15T14:30:00Z",
            }
        },
        quote_primary_provider="primary",
        quote_trusted_providers={"primary"},
        quote_cache_ttl_seconds=0,
    )

    result = gateway.get_quote("aapl")

    assert result["data"] == {"price": 205.0, "change": -2.5, "change_percent": -1.2}
    assert result["provider"] == "primary"
    assert result["quality"] == "trusted"
    assert result["error_code"] is None


def test_news_contract_rejects_unlinked_primary_then_uses_one_secondary():
    calls: list[str] = []

    def primary(_symbol: str, _limit: int):
        calls.append("primary")
        return [{"title": "Unlinked item", "source": "wire", "published_at": "2026-07-15T10:00:00Z"}]

    def secondary(symbol: str, _limit: int):
        calls.append("secondary")
        return [
            {
                "title": f"{symbol} reports quarterly results",
                "source": "Reuters",
                "url": "https://www.reuters.com/markets/aapl-results-2026-07-15/",
                "published_at": "2026-07-15T11:00:00Z",
            }
        ]

    gateway = MarketDataGateway(
        providers={},
        primary_provider="",
        cache_ttl_seconds=0,
        news_providers={"primary": primary, "secondary": secondary},
        news_primary_provider="primary",
        news_secondary_provider="secondary",
        news_trusted_providers={"secondary"},
        news_cache_ttl_seconds=0,
    )

    result = gateway.get_news("AAPL", limit=3)

    assert calls == ["primary", "secondary"]
    assert result["quality"] == "trusted"
    assert result["degraded"] is True
    assert result["data"][0]["url"].startswith("https://www.reuters.com/")


def test_financial_contract_falls_back_once_and_rejects_empty_tables():
    calls: list[str] = []

    def primary(_symbol: str):
        calls.append("primary")
        return {"financials": None, "balance_sheet": None, "cashflow": None}

    def secondary(symbol: str):
        calls.append("secondary")
        return {
            "ticker": symbol,
            "timestamp": "2026-07-15T00:00:00Z",
            "financials": {
                "columns": ["2026-06-30"],
                "index": ["Total Revenue"],
                "data": [{"2026-06-30": 100.0}],
            },
            "balance_sheet": None,
            "cashflow": None,
            "error": None,
        }

    gateway = MarketDataGateway(
        providers={},
        primary_provider="",
        cache_ttl_seconds=0,
        financial_providers={"primary": primary, "secondary": secondary},
        financial_primary_provider="primary",
        financial_secondary_provider="secondary",
        financial_trusted_providers={"secondary"},
        financial_cache_ttl_seconds=0,
    )

    result = gateway.get_financials("MSFT")

    assert calls == ["primary", "secondary"]
    assert result["provider"] == "secondary"
    assert result["quality"] == "trusted"
    assert result["data"]["financials"]["index"] == ["Total Revenue"]


def test_all_capabilities_use_stable_error_code_after_at_most_two_calls():
    calls: list[str] = []

    def unavailable(name: str):
        def fetch(*_args, **_kwargs):
            calls.append(name)
            return None

        return fetch

    gateway = MarketDataGateway(
        providers={"kp": unavailable("kp"), "ks": unavailable("ks")},
        primary_provider="kp",
        secondary_provider="ks",
        cache_ttl_seconds=0,
        quote_providers={"qp": unavailable("qp"), "qs": unavailable("qs")},
        quote_primary_provider="qp",
        quote_secondary_provider="qs",
        quote_cache_ttl_seconds=0,
        news_providers={"np": unavailable("np"), "ns": unavailable("ns")},
        news_primary_provider="np",
        news_secondary_provider="ns",
        news_cache_ttl_seconds=0,
        financial_providers={"fp": unavailable("fp"), "fs": unavailable("fs")},
        financial_primary_provider="fp",
        financial_secondary_provider="fs",
        financial_cache_ttl_seconds=0,
    )

    results = [
        gateway.get_kline("AAPL"),
        gateway.get_quote("AAPL"),
        gateway.get_news("AAPL"),
        gateway.get_financials("AAPL"),
    ]

    assert calls == ["kp", "ks", "qp", "qs", "np", "ns", "fp", "fs"]
    assert all(result["error_code"] == "market_data_unavailable" for result in results)


def test_reference_us_tickers_100_requests_never_emit_synthetic_data():
    calls = 0

    def provider(_symbol: str, _period: str, _interval: str):
        nonlocal calls
        calls += 1
        return _payload()

    gateway = MarketDataGateway(
        providers={"trusted": provider},
        primary_provider="trusted",
        trusted_providers={"trusted"},
        cache_ttl_seconds=0,
    )
    symbols = ("AAPL", "MSFT", "NVDA", "AMZN", "TSLA")

    results = [gateway.get_kline(symbols[index % len(symbols)]) for index in range(100)]

    assert calls == 100
    assert all(result["quality"] == "trusted" and result["error_code"] is None for result in results)
    assert all("synthetic" not in result and "mock" not in result for result in results)


def test_public_validators_reject_empty_payloads():
    with pytest.raises(MarketDataValidationError):
        validate_quote_payload(None)
    with pytest.raises(MarketDataValidationError):
        validate_news_items([])
    with pytest.raises(MarketDataValidationError):
        validate_financial_payload({})

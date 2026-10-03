# -*- coding: utf-8 -*-
"""Tests for shared quote parsing helpers."""

from __future__ import annotations

import math

import pandas as pd
import pytest

from backend.utils.quote import (
    fallback_quote_yfinance,
    parse_quote_payload,
    resolve_live_quote,
    safe_float,
)


class TestSafeFloat:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (123, 123.0),
            (123.45, 123.45),
            ("123.45", 123.45),
            ("-42.5", -42.5),
            (0, 0.0),
            ("0", 0.0),
            (None, None),
            ("", None),
            ("abc", None),
            (float("nan"), None),
            (float("inf"), None),
            (float("-inf"), None),
        ],
    )
    def test_safe_float(self, value, expected):
        out = safe_float(value)
        if expected is None:
            assert out is None
        else:
            assert out == pytest.approx(expected)


class TestParseQuotePayload:
    def test_none_payload(self):
        assert parse_quote_payload(None) is None

    def test_plain_dict_payload(self):
        payload = {"price": "123.4", "change": "-1.2", "change_percent": "-0.96"}
        parsed = parse_quote_payload(payload)
        assert parsed == {
            "price": 123.4,
            "change": -1.2,
            "change_percent": -0.96,
        }

    def test_nested_data_payload(self):
        payload = {"data": {"price": 88, "change": 2, "change_percent": 2.33}}
        parsed = parse_quote_payload(payload)
        assert parsed == {
            "price": 88.0,
            "change": 2.0,
            "change_percent": 2.33,
        }

    def test_nested_payload_without_price(self):
        payload = {"data": {"change": 1.2}}
        assert parse_quote_payload(payload) is None

    def test_dict_payload_with_nan_price(self):
        payload = {"price": float("nan"), "change": 1.0, "change_percent": 1.2}
        assert parse_quote_payload(payload) is None

    def test_text_payload_full_pattern(self):
        payload = "Current Price: $145.56 | Change: -2.10 (-1.42%)"
        parsed = parse_quote_payload(payload)
        assert parsed == {
            "price": 145.56,
            "change": -2.1,
            "change_percent": -1.42,
        }

    def test_text_payload_fallback_price_pattern(self):
        payload = "AAPL last seen around $199.7 in pre-market"
        parsed = parse_quote_payload(payload)
        assert parsed == {
            "price": 199.7,
            "change": None,
            "change_percent": None,
        }

    def test_text_payload_without_price(self):
        payload = "No market data available"
        assert parse_quote_payload(payload) is None

    def test_change_percent_field_name_is_standardized(self):
        parsed = parse_quote_payload({"price": 100, "change": 1, "change_percent": 1})
        assert parsed is not None
        assert "change_percent" in parsed
        assert "change_pct" not in parsed

    def test_nested_envelope_preserves_quote_metadata(self):
        parsed = parse_quote_payload({
            "provider": "twelve_data", "as_of": "2026-10-02T00:00:00Z",
            "data": {"price": 333.69, "currency": "USD"},
        })
        assert parsed["source"] == "twelve_data"
        assert parsed["as_of"] == "2026-10-02T00:00:00Z"
        assert parsed["currency"] == "USD"

    def test_live_quote_text_preserves_metadata_and_actual_provider(self):
        payload = ("AAPL Current Price: $333.69 | Change: +3.37 (+1.02%) "
                   "| Provider: twelve_data | As of: 2026-10-02T00:00:00Z "
                   "| Currency: USD | Quality: verified")
        parsed, raw = resolve_live_quote("AAPL", lambda _: payload)
        assert raw == payload
        assert parsed["source"] == "twelve_data"
        assert parsed["as_of"] == "2026-10-02T00:00:00Z"
        assert parsed["currency"] == "USD"
        assert parsed["quality"] == "verified"

    def test_nested_data_metadata_takes_precedence(self):
        parsed = parse_quote_payload({"source": "tools_bridge", "currency": "USD", "data": {
            "price": 500, "provider": "eastmoney", "currency": "CNY", "as_of": "2026-10-02",
        }})
        assert parsed["source"] == "eastmoney"
        assert parsed["currency"] == "CNY"

    def test_text_unknown_metadata_is_not_present(self):
        parsed = parse_quote_payload("Current Price: $100 | Provider: None | As of: None")
        assert "source" not in parsed
        assert "as_of" not in parsed


class TestFallbackQuoteYfinance:
    def test_yfinance_import_error(self, monkeypatch: pytest.MonkeyPatch):
        def unavailable(_ticker: str):
            raise ImportError("yfinance not installed")

        monkeypatch.setattr("backend.tools.yfinance_client.create_ticker", unavailable)
        assert fallback_quote_yfinance("AAPL") is None

    def test_success_with_mock_yfinance(self, monkeypatch: pytest.MonkeyPatch):
        class FakeTicker:
            def history(self, period: str, interval: str):
                assert period == "5d"
                assert interval == "1d"
                return pd.DataFrame({"Close": [100.0, 101.0, 103.0]})

        monkeypatch.setattr("backend.tools.yfinance_client.create_ticker", lambda _ticker: FakeTicker())

        result = fallback_quote_yfinance("AAPL")

        assert result is not None
        assert result["price"] == pytest.approx(103.0)
        assert result["change"] == pytest.approx(2.0)
        assert result["change_percent"] == pytest.approx((2.0 / 101.0) * 100.0)
        assert result["source"] == "yfinance_fallback"

    def test_returns_none_when_history_empty(self, monkeypatch: pytest.MonkeyPatch):
        class FakeTicker:
            def history(self, period: str, interval: str):
                return pd.DataFrame({"Close": []})

        monkeypatch.setattr("backend.tools.yfinance_client.create_ticker", lambda _ticker: FakeTicker())

        assert fallback_quote_yfinance("AAPL") is None

    def test_returns_none_when_close_is_invalid(self, monkeypatch: pytest.MonkeyPatch):
        class FakeTicker:
            def history(self, period: str, interval: str):
                return pd.DataFrame({"Close": [100.0, math.inf]})

        monkeypatch.setattr("backend.tools.yfinance_client.create_ticker", lambda _ticker: FakeTicker())

        assert fallback_quote_yfinance("AAPL") is None

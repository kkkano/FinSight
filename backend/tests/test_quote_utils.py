# -*- coding: utf-8 -*-
"""Tests for shared quote parsing helpers."""

from __future__ import annotations

import builtins
import math
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from backend.utils.quote import (
    fallback_quote_yfinance,
    parse_quote_payload,
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


class TestFallbackQuoteYfinance:
    def test_yfinance_import_error(self, monkeypatch: pytest.MonkeyPatch):
        original_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "yfinance":
                raise ImportError("yfinance not installed")
            return original_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        assert fallback_quote_yfinance("AAPL") is None

    def test_success_with_mock_yfinance(self, monkeypatch: pytest.MonkeyPatch):
        class FakeTicker:
            def history(self, period: str, interval: str):
                assert period == "5d"
                assert interval == "1d"
                return pd.DataFrame({"Close": [100.0, 101.0, 103.0]})

        fake_module = SimpleNamespace(Ticker=lambda _ticker: FakeTicker())
        monkeypatch.setitem(sys.modules, "yfinance", fake_module)

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

        fake_module = SimpleNamespace(Ticker=lambda _ticker: FakeTicker())
        monkeypatch.setitem(sys.modules, "yfinance", fake_module)

        assert fallback_quote_yfinance("AAPL") is None

    def test_returns_none_when_close_is_invalid(self, monkeypatch: pytest.MonkeyPatch):
        class FakeTicker:
            def history(self, period: str, interval: str):
                return pd.DataFrame({"Close": [100.0, math.inf]})

        fake_module = SimpleNamespace(Ticker=lambda _ticker: FakeTicker())
        monkeypatch.setitem(sys.modules, "yfinance", fake_module)

        assert fallback_quote_yfinance("AAPL") is None

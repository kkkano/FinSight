# -*- coding: utf-8 -*-
"""WP6-F1：akshare 作为 A 股价格与历史行情首选源。"""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pandas as pd

from backend.tools import price


def test_akshare_spot_formats_price_and_change(monkeypatch):
    fake = SimpleNamespace(
        stock_bid_ask_em=lambda *, symbol: pd.DataFrame(
            {
                "item": ["最新", "涨幅"],
                "value": [42.31, 1.25],
            }
        )
    )
    monkeypatch.setitem(sys.modules, "akshare", fake)

    result = price._fetch_with_akshare_spot("600036.SS")

    assert result is not None
    assert "600036.SS" in result
    assert "$42.31" in result
    assert "CNY 42.31" in result
    assert "change 1.25%" in result
    assert "source: akshare/eastmoney" in result


def test_a_share_spot_ladder_tries_akshare_first(monkeypatch):
    calls: list[str] = []

    def source(name, result=None):
        def fetch(_ticker):
            calls.append(name)
            return result

        return fetch

    monkeypatch.setattr(price, "_fetch_with_akshare_spot", source("akshare"))
    monkeypatch.setattr(price, "_fetch_with_yfinance", source("yfinance"))
    monkeypatch.setattr(price, "_fetch_yahoo_api_v8", source("yahoo_v8"))
    monkeypatch.setattr(
        price,
        "_search_for_price",
        source("search", "600036.SS Current Price: $42.31"),
    )

    result = price.get_stock_price("600036")

    assert calls == ["akshare", "yfinance", "yahoo_v8", "search"]
    assert "$42.31" in result


def test_akshare_history_maps_chinese_columns(monkeypatch):
    captured: dict[str, str] = {}

    def stock_zh_a_hist(**kwargs):
        captured.update(kwargs)
        return pd.DataFrame(
            {
                "日期": ["2026-07-10", "2026-07-11"],
                "开盘": [40.0, 41.0],
                "最高": [43.0, 44.0],
                "最低": [39.5, 40.5],
                "收盘": [42.0, 43.0],
                "成交量": [1000, 1200],
            }
        )

    monkeypatch.setitem(
        sys.modules,
        "akshare",
        SimpleNamespace(stock_zh_a_hist=stock_zh_a_hist),
    )

    result = price._fetch_with_akshare_hist("600036.SS", period="1y")

    assert captured["symbol"] == "600036"
    assert captured["period"] == "daily"
    assert captured["adjust"] == "qfq"
    assert result == {
        "kline_data": [
            {
                "time": "2026-07-10 00:00",
                "open": 40.0,
                "high": 43.0,
                "low": 39.5,
                "close": 42.0,
                "volume": 1000.0,
            },
            {
                "time": "2026-07-11 00:00",
                "open": 41.0,
                "high": 44.0,
                "low": 40.5,
                "close": 43.0,
                "volume": 1200.0,
            },
        ],
        "period": "1y",
        "interval": "1d",
        "source": "akshare/eastmoney",
    }


def test_a_share_history_uses_akshare_before_yfinance(monkeypatch):
    expected = {
        "kline_data": [{"time": "2026-07-11 00:00", "close": 42.31}],
        "period": "1y",
        "interval": "1d",
        "source": "akshare/eastmoney",
    }
    monkeypatch.setattr(price, "_fetch_with_akshare_hist", lambda *_args, **_kwargs: expected)

    class ForbiddenTicker:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("akshare 命中后不应调用 yfinance")

    monkeypatch.setattr(price.yf, "Ticker", ForbiddenTicker)

    assert price.get_stock_historical_data("600036") == expected


def test_akshare_lazy_import_missing_is_safe(monkeypatch):
    monkeypatch.setitem(sys.modules, "akshare", None)
    assert price._fetch_with_akshare_spot("600036.SS") is None
    assert price._fetch_with_akshare_hist("600036.SS") is None

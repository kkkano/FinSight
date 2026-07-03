# -*- coding: utf-8 -*-
"""BE-01：数据源返回文本无 $ 数字时，get_stock_price 不得丢弃该成功源。

注意：get_stock_price 内部会读取 source_func.__name__，因此 patch 必须用
new=真函数/lambda（自带 __name__），不能用 Mock 包装。
"""
from unittest.mock import patch

import backend.tools.price as price_mod

_NONE_SOURCES = (
    "_fetch_with_stooq_price",
    "_scrape_google_finance",
    "_scrape_cnbc",
    "_fetch_with_pandas_datareader",
    "_fetch_with_yfinance",
    "_fetch_with_alpha_vantage",
    "_fetch_with_finnhub",
    "_fetch_with_twelve_data_price",
    "_scrape_yahoo_finance",
    "_search_for_price",
)


def _patch_all_none():
    """把除首选源外的全部美股级联源替换为返回 None 的真函数。"""
    return [patch.object(price_mod, name, new=lambda ticker: None) for name in _NONE_SOURCES]


def test_source_without_dollar_sign_is_not_discarded():
    """源返回 '195.30 USD'（无 $ 前缀）→ 应原样返回，而不是 NameError 后降级到全失败。"""

    def fake_source(ticker):
        return "AAPL current price: 195.30 USD (from fake_source)"

    patches = [patch.object(price_mod, "_fetch_yahoo_api_v8", new=fake_source), *_patch_all_none()]
    for p in patches:
        p.start()
    try:
        result = price_mod.get_stock_price("AAPL")
    finally:
        for p in patches:
            p.stop()

    assert "195.30 USD" in result
    assert "All data sources failed" not in result


def test_source_with_dollar_sign_appends_ladder():
    """有 $ 数字时保留原有 Suggested ladder 行为。"""

    def fake_source(ticker):
        return "AAPL: $200.00"

    with patch.object(price_mod, "_fetch_yahoo_api_v8", new=fake_source):
        result = price_mod.get_stock_price("AAPL")

    assert "$200.00" in result
    assert "Suggested ladder: $198.00 / $196.00" in result

# -*- coding: utf-8 -*-
"""tool 层数据源降级信息传播到报告的测试（P1-9 残留缺口）。

覆盖点：
1. get_stock_price 多源循环：第一个源失败、第二个源成功 → get_last_fetch_info 标记降级。
2. 第一个源直接成功 → 未降级。
3. PriceAgent 拿到 tool 层降级信息后，AgentOutput.fallback_used=True 且 reason 含源名。

全程不调用真实外部 API：通过 monkeypatch 替换底层源函数 / 用 stub tools。
"""
from __future__ import annotations

import pytest

from backend.tools import price as price_tools
from backend.agents.price_agent import PriceAgent


class _Cache:
    """最小缓存桩：永远 miss，set 无副作用。"""

    def get(self, key: str):
        del key
        return None

    def set(self, key: str, value, ttl=None) -> None:
        del key, value, ttl


@pytest.fixture(autouse=True)
def _clear_fetch_info():
    """每个用例前后清空模块级取数注册表，避免用例间串味。"""
    price_tools._last_fetch_info.clear()
    yield
    price_tools._last_fetch_info.clear()


def test_get_last_fetch_info_marks_degraded_when_first_source_fails(monkeypatch):
    """第一个源失败、第二个源成功 → is_degraded=True，attempt=2。"""

    def _boom(_ticker):
        # 模拟首选源异常（走 except 分支，不 sleep）
        raise RuntimeError("primary source down")

    def _ok(_ticker):
        # 模拟备用源成功返回（含 $ 价格，触发 ladder 逻辑）
        return "AAPL Current Price: $107.00 | Change: $1.00 (+0.94%)"

    # 普通美股源链首两个为 _fetch_yahoo_api_v8 / _fetch_with_stooq_price
    monkeypatch.setattr(price_tools, "_fetch_yahoo_api_v8", _boom)
    monkeypatch.setattr(price_tools, "_fetch_with_stooq_price", _ok)

    result = price_tools.get_stock_price("AAPL")

    # 取数本身成功（返回备用源的价格字符串）
    assert "Current Price" in result

    info = price_tools.get_last_fetch_info("AAPL")
    assert info is not None
    assert info["is_degraded"] is True
    assert info["attempt"] == 2
    assert info["source"] == "_ok"  # 第二个源成功，记录其函数名


def test_get_last_fetch_info_not_degraded_when_first_source_succeeds(monkeypatch):
    """第一个源直接成功 → is_degraded=False，attempt=1。"""

    def _ok(_ticker):
        return "AAPL Current Price: $107.00 | Change: $1.00 (+0.94%)"

    monkeypatch.setattr(price_tools, "_fetch_yahoo_api_v8", _ok)

    result = price_tools.get_stock_price("AAPL")
    assert "Current Price" in result

    info = price_tools.get_last_fetch_info("AAPL")
    assert info is not None
    assert info["is_degraded"] is False
    assert info["attempt"] == 1
    assert info["source"] == "_ok"


def test_get_last_fetch_info_key_is_upper_stripped(monkeypatch):
    """注册表 key 统一大写 strip：用小写带空格的 ticker 也能查到。"""

    def _ok(_ticker):
        return "AAPL Current Price: $107.00 | Change: $1.00 (+0.94%)"

    monkeypatch.setattr(price_tools, "_fetch_yahoo_api_v8", _ok)
    price_tools.get_stock_price("  aapl  ")

    # 用任意大小写 / 空格组合查询都应命中
    assert price_tools.get_last_fetch_info("aapl") is not None
    assert price_tools.get_last_fetch_info(" AAPL ") is not None


def test_get_last_fetch_info_all_sources_failed(monkeypatch):
    """全部源失败 → source=None，is_degraded=True。"""

    def _boom(_ticker):
        raise RuntimeError("down")

    # 把普通美股源链涉及的源全部替换为抛异常（覆盖所有可能被调用的）
    for name in (
        "_fetch_yahoo_api_v8",
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
    ):
        monkeypatch.setattr(price_tools, name, _boom)

    result = price_tools.get_stock_price("ZZZZ")
    assert result.startswith("Error:")

    info = price_tools.get_last_fetch_info("ZZZZ")
    assert info is not None
    assert info["source"] is None
    assert info["is_degraded"] is True


class _ToolsWithDegradedFetchInfo:
    """stub tools：get_last_fetch_info 返回降级信息（不调外部 API）。"""

    def get_last_fetch_info(self, ticker: str):
        del ticker
        return {"source": "_fetch_with_stooq_price", "attempt": 2, "is_degraded": True}


def test_price_agent_propagates_tool_fallback_into_output():
    """PriceAgent 拿到 tool 层降级信息 → AgentOutput.fallback_used=True 且 reason 含源名。"""
    agent = PriceAgent(None, _Cache(), _ToolsWithDegradedFetchInfo())
    agent._current_ticker = "AAPL"

    # 走 _format_output 的裸 dict 分支（非 snapshot），原本不降级
    raw_data = {"ticker": "AAPL", "price": 107.0, "currency": "USD", "source": "yfinance"}
    output = agent._format_output("AAPL 当前价格: USD 107.0。", raw_data)

    assert output.fallback_used is True
    assert output.fallback_reason is not None
    assert "_fetch_with_stooq_price" in output.fallback_reason
    assert "降级" in output.fallback_reason
    # 降级后置信度下调
    assert output.confidence == 0.5


def test_price_agent_keeps_existing_fallback_reason():
    """若 AgentOutput 已因其他原因带 reason，tool 层降级不覆盖（已有优先）。"""
    agent = PriceAgent(None, _Cache(), _ToolsWithDegradedFetchInfo())
    agent._current_ticker = "AAPL"

    # dict 分支：raw_data 本身已标记 fallback 且带 error → 产生原始 reason
    raw_data = {
        "ticker": "AAPL",
        "price": 107.0,
        "currency": "USD",
        "source": "yfinance",
        "fallback_used": True,
        "error": "upstream_rate_limited",
    }
    output = agent._format_output("AAPL 当前价格: USD 107.0。", raw_data)

    assert output.fallback_used is True
    # 原始 reason（来自 raw_data.error）应被保留，不被 tool 层降级原因覆盖（已有优先）
    assert output.fallback_reason == "upstream_rate_limited"


def test_price_agent_no_tool_fallback_when_not_degraded():
    """tool 层未降级时，不应凭空标记 fallback。"""

    class _ToolsNotDegraded:
        def get_last_fetch_info(self, ticker: str):
            del ticker
            return {"source": "_fetch_yahoo_api_v8", "attempt": 1, "is_degraded": False}

    agent = PriceAgent(None, _Cache(), _ToolsNotDegraded())
    agent._current_ticker = "AAPL"

    raw_data = {"ticker": "AAPL", "price": 107.0, "currency": "USD", "source": "yfinance"}
    output = agent._format_output("AAPL 当前价格: USD 107.0。", raw_data)

    assert output.fallback_used is False
    assert output.fallback_reason is None

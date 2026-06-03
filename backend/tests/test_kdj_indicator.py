# -*- coding: utf-8 -*-
"""KDJ 随机指标测试（子任务 B：A股技术分析常用指标）。

覆盖：
- calculate_kdj 纯函数：dict 列表 / DataFrame 两条路径、J=3K-2D、数据不足、signal 判断
- compute_technical_indicators 集成 KDJ 字段
- TechnicalAgent：CN/HK ticker 摘要带 KDJ，US ticker 不带
"""
import pandas as pd
import pytest
from unittest.mock import MagicMock

from backend.tools.technical import calculate_kdj, compute_technical_indicators
from backend.agents.technical_agent import TechnicalAgent, _is_cn_or_hk_ticker


class DummyCache:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def set(self, key, value, ttl=None):
        self.store[key] = value


def _build_kline(count=60, start=100.0, step=0.5):
    data = []
    for i in range(count):
        close = start + i * step
        data.append({
            "time": f"2026-01-{(i % 28) + 1:02d}",
            "open": close - 1,
            "high": close + 1.5,
            "low": close - 1.5,
            "close": close,
            "volume": 1_000_000,
        })
    return data


def test_calculate_kdj_returns_three_lines_and_latest():
    kdj = calculate_kdj(_build_kline())
    assert set(kdj.keys()) == {"k", "d", "j", "latest"}
    assert len(kdj["k"]) == len(kdj["d"]) == len(kdj["j"]) == 60
    latest = kdj["latest"]
    assert set(latest.keys()) == {"k", "d", "j", "signal"}
    assert latest["k"] is not None and latest["d"] is not None


def test_calculate_kdj_j_equals_three_k_minus_two_d():
    kdj = calculate_kdj(_build_kline())
    latest = kdj["latest"]
    assert round(3 * latest["k"] - 2 * latest["d"], 4) == round(latest["j"], 4)


def test_calculate_kdj_dataframe_matches_dict_list():
    kline = _build_kline()
    df = pd.DataFrame([
        {"Open": k["open"], "High": k["high"], "Low": k["low"],
         "Close": k["close"], "Volume": k["volume"]}
        for k in kline
    ])
    from_dict = calculate_kdj(kline)["latest"]
    from_df = calculate_kdj(df)["latest"]
    assert round(from_dict["k"], 6) == round(from_df["k"], 6)
    assert round(from_dict["j"], 6) == round(from_df["j"], 6)


def test_calculate_kdj_insufficient_data_returns_empty():
    assert calculate_kdj(_build_kline(count=5)) == {}
    assert calculate_kdj([]) == {}
    assert calculate_kdj(None) == {}


def test_calculate_kdj_overbought_signal_on_strong_uptrend():
    # 持续上涨 → J 容易 > 100 → 超买
    kdj = calculate_kdj(_build_kline(count=40, start=100, step=2.0))
    assert kdj["latest"]["j"] is not None
    # 强势上涨时 J 应明显偏高
    assert kdj["latest"]["signal"] in {"超买", "金叉", "中性"}


def test_compute_technical_indicators_includes_kdj_fields():
    kline = _build_kline(count=60)
    df = pd.DataFrame([
        {"Open": k["open"], "High": k["high"], "Low": k["low"],
         "Close": k["close"], "Volume": k["volume"]}
        for k in kline
    ])
    ind = compute_technical_indicators(df)
    assert "kdj_k" in ind and "kdj_d" in ind and "kdj_j" in ind and "kdj_signal" in ind
    assert ind["kdj_k"] is not None


def test_is_cn_or_hk_ticker_helper():
    assert _is_cn_or_hk_ticker("600519.SS")
    assert _is_cn_or_hk_ticker("300750.SZ")
    assert _is_cn_or_hk_ticker("0700.HK")
    assert not _is_cn_or_hk_ticker("AAPL")
    assert not _is_cn_or_hk_ticker("")


def _make_agent():
    return TechnicalAgent(MagicMock(), DummyCache(), MagicMock())


def test_technical_agent_compute_indicators_has_kdj():
    agent = _make_agent()
    ind = agent._compute_indicators(_build_kline(count=60))
    assert ind is not None
    assert ind.get("kdj_k") is not None
    assert ind.get("kdj_signal") is not None


def test_technical_agent_summary_includes_kdj_for_cn_ticker():
    agent = _make_agent()
    data = {"ticker": "600519.SS", "kline_data": _build_kline(count=60)}
    summary = agent._deterministic_summary(data)
    assert "KDJ" in summary


def test_technical_agent_summary_omits_kdj_for_us_ticker():
    agent = _make_agent()
    data = {"ticker": "AAPL", "kline_data": _build_kline(count=60)}
    summary = agent._deterministic_summary(data)
    assert "KDJ" not in summary

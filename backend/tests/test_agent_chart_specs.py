# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.agents.chart_specs_extra import (
    build_deepsearch_chart_specs,
    build_macro_chart_specs,
    build_risk_chart_specs,
    build_technical_chart_specs,
)
from backend.agents.risk_agent import RiskAgent, RiskSignal
from backend.agents.technical_agent import TechnicalAgent


class _Cache:
    def get(self, key: str):
        return None

    def set(self, key: str, value, ttl=None) -> None:
        del key, value, ttl


class _Tools:
    pass


def _history_rows(prefix: str, base: float) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for index in range(1, 8):
        close = base + index
        rows.append(
            {
                "time": f"2026-05-{index:02d}",
                "open": close - 0.5,
                "high": close + 1.5,
                "low": close - 1.0,
                "close": close,
                "volume": 1_000_000 + index * 10_000,
                "symbol": prefix,
            }
        )
    return rows


# --- P2-8: technical / macro / risk chart specs ---


def _long_kline(base: float, points: int = 60) -> list[dict[str, object]]:
    """生成足够点数(>=30)的 K 线数据，价格缓慢上行以保证指标可算。"""
    rows: list[dict[str, object]] = []
    for index in range(1, points + 1):
        close = base + index * 0.5
        rows.append(
            {
                "time": f"2026-{((index - 1) // 28) + 1:02d}-{((index - 1) % 28) + 1:02d}",
                "open": close - 0.3,
                "high": close + 0.8,
                "low": close - 0.6,
                "close": close,
                "volume": 1_000_000 + index * 5_000,
            }
        )
    return rows


def test_build_technical_chart_specs_full_data_returns_candlestick_bar_gauge() -> None:
    raw_data = {"ticker": "AAPL", "source": "kline", "kline_data": _long_kline(100.0, 60)}
    specs = build_technical_chart_specs("AAPL", raw_data)

    types = [item["type"] for item in specs]
    assert "candlestick" in types
    assert "bar" in types  # 收盘价 vs 均线对比
    assert "gauge" in types  # RSI(14)

    candle = next(item for item in specs if item["type"] == "candlestick")
    assert len(candle["data"]["ohlc"]) == len(candle["data"]["labels"])
    assert all(len(row) == 4 for row in candle["data"]["ohlc"])

    bar = next(item for item in specs if item["type"] == "bar")
    assert bar["data"]["labels"][0] == "Close"
    assert "MA20" in bar["data"]["labels"]

    gauge = next(item for item in specs if item["type"] == "gauge")
    assert gauge["data"]["labels"] == ["RSI(14)"]
    assert 0.0 <= gauge["data"]["values"][0] <= 100.0


def test_build_technical_chart_specs_insufficient_data_returns_empty() -> None:
    # 无 kline_data
    assert build_technical_chart_specs("AAPL", {"ticker": "AAPL"}) == []
    # 点数太少：能出 candlestick 但出不了指标(bar/gauge)
    short = {"ticker": "AAPL", "kline_data": _long_kline(100.0, 5)}
    specs = build_technical_chart_specs("AAPL", short)
    assert all(item["type"] == "candlestick" for item in specs)
    assert not any(item["type"] in ("bar", "gauge") for item in specs)


def test_technical_agent_format_output_attaches_chart_specs() -> None:
    agent = TechnicalAgent(None, _Cache(), _Tools())
    raw_data = {"ticker": "AAPL", "source": "kline", "kline_data": _long_kline(100.0, 60)}
    output = agent._format_output("技术摘要", raw_data)
    types = [item["type"] for item in output.chart_specs]
    assert "candlestick" in types and "gauge" in types


def test_build_macro_chart_specs_returns_bar() -> None:
    snapshot = {
        "status": "success",
        "indicators": [
            {"key": "fed_rate", "name": "Federal funds rate", "value": 4.5, "unit": "%", "source": "fred"},
            {"key": "cpi", "name": "CPI inflation", "value": 3.1, "unit": "%", "source": "fred"},
            {"key": "unemployment", "name": "Unemployment rate", "value": 4.0, "unit": "%", "source": "fred"},
            {"key": "gdp_growth", "name": "GDP growth", "value": None, "unit": "%", "source": "fred"},
        ],
    }
    specs = build_macro_chart_specs(snapshot)
    assert len(specs) == 1
    assert specs[0]["type"] == "bar"
    assert specs[0]["data"]["labels"] == [
        "Federal funds rate",
        "CPI inflation",
        "Unemployment rate",
    ]
    assert specs[0]["data"]["values"] == [4.5, 3.1, 4.0]
    assert specs[0]["data"]["unit"] == "%"


def test_build_macro_chart_specs_insufficient_returns_empty() -> None:
    assert build_macro_chart_specs({}) == []
    assert build_macro_chart_specs({"indicators": []}) == []
    # 只有 1 个有效指标，不足以画对比柱状图
    one = {"indicators": [{"name": "CPI", "value": 3.0, "unit": "%"}]}
    assert build_macro_chart_specs(one) == []


def test_build_risk_chart_specs_returns_radar_and_gauge() -> None:
    dimension_scores = {
        "technical": 70.0,
        "fundamental": 55.0,
        "macro": 40.0,
        "news": 30.0,
        "data_quality": 10.0,
    }
    specs = build_risk_chart_specs("TSLA", 62.5, "high", dimension_scores)
    types = [item["type"] for item in specs]
    assert types == ["radar", "gauge"]

    radar = specs[0]
    assert len(radar["data"]["labels"]) == 5
    assert len(radar["data"]["values"]) == 5

    gauge = specs[1]
    assert gauge["data"]["labels"] == ["high"]
    assert gauge["data"]["values"] == [62.5]


def test_build_risk_chart_specs_insufficient_dimensions_skips_radar() -> None:
    # 只有 2 个非零维度 -> 雷达图不画，但综合分仍出 gauge
    specs = build_risk_chart_specs(
        "TSLA",
        20.0,
        "low",
        {"technical": 30.0, "fundamental": 0.0, "macro": 0.0, "news": 0.0, "data_quality": 0.0},
    )
    types = [item["type"] for item in specs]
    assert "radar" not in types
    assert types == ["gauge"]


def test_build_risk_chart_specs_no_data_returns_empty() -> None:
    assert build_risk_chart_specs("TSLA", None, None, None) == []


def test_risk_agent_dimension_scores_normalization() -> None:
    signals = [
        RiskSignal(source_agent="risk_agent", category="technical", description="x", severity=0.9),
        RiskSignal(source_agent="risk_agent", category="technical", description="y", severity=0.6),
        RiskSignal(source_agent="risk_agent", category="news", description="z", severity=0.5),
    ]
    scores = RiskAgent._dimension_scores(signals)
    # technical: 0.9+0.6=1.5 capped 1.0 -> 100
    assert scores["technical"] == 100.0
    assert scores["news"] == 50.0
    assert scores["macro"] == 0.0
    assert set(scores.keys()) == set(RiskAgent.CATEGORY_WEIGHTS.keys())


# --- deep_search：时间分布(bar) + 来源分布(pie) chart specs ---


def _deep_docs() -> list[dict[str, object]]:
    """3 个文档、2 个来源(reuters x2 / bloomberg x1)、3 个不同日期。"""
    return [
        {
            "title": "Apple Q2 beats",
            "url": "https://reuters.com/a",
            "snippet": "...",
            "source": "reuters",
            "published_date": "2026-05-01T08:00:00Z",
        },
        {
            "title": "Apple services growth",
            "url": "https://reuters.com/b",
            "snippet": "...",
            "source": "reuters",
            "published_date": "2026-05-02",
        },
        {
            "title": "Apple supply chain note",
            "url": "https://bloomberg.com/c",
            "snippet": "...",
            "source": "bloomberg",
            "published_date": "2026-05-03T12:30:00+00:00",
        },
    ]


def test_build_deepsearch_chart_specs_full_data_returns_bar_and_pie() -> None:
    # 正常 docs：3 文档 / 2 来源 / 3 个不同日期 -> bar + pie 两张图
    specs = build_deepsearch_chart_specs(_deep_docs(), query="AAPL earnings")
    types = [item["type"] for item in specs]
    assert types == ["bar", "pie"]

    bar = specs[0]
    # query 非空时标题拼上 query
    assert bar["title"] == "搜索结果时间分布 · AAPL earnings"
    # 三个日期升序、每个计数为 1
    assert bar["data"]["labels"] == ["2026-05-01", "2026-05-02", "2026-05-03"]
    assert bar["data"]["values"] == [1, 1, 1]

    pie = specs[1]
    assert pie["title"] == "信息来源分布"
    # reuters(2) 计数高于 bloomberg(1)，降序在前
    assert pie["data"]["labels"] == ["reuters", "bloomberg"]
    assert pie["data"]["values"] == [2, 1]


def test_build_deepsearch_chart_specs_single_source_skips_pie() -> None:
    # 仅 1 个来源 -> 只有 bar，没有 pie
    docs = [
        {"source": "reuters", "published_date": "2026-05-01"},
        {"source": "reuters", "published_date": "2026-05-02"},
    ]
    specs = build_deepsearch_chart_specs(docs)
    types = [item["type"] for item in specs]
    assert types == ["bar"]
    assert "pie" not in types
    # query 为空 -> 标题不拼 query
    assert specs[0]["title"] == "搜索结果时间分布"


def test_build_deepsearch_chart_specs_empty_or_none_returns_empty() -> None:
    # 空列表 / None / 全部非 dict -> []
    assert build_deepsearch_chart_specs([]) == []
    assert build_deepsearch_chart_specs(None) == []
    assert build_deepsearch_chart_specs(["not-a-dict", 123]) == []


def test_build_deepsearch_chart_specs_missing_or_bad_date_does_not_crash() -> None:
    # 文档缺 published_date / 日期无法解析：不崩溃；全部未知日期则不出 bar
    docs = [
        {"source": "reuters"},  # 缺 published_date
        {"source": "bloomberg", "published_date": "not-a-date"},  # 无法解析
    ]
    specs = build_deepsearch_chart_specs(docs)
    types = [item["type"] for item in specs]
    # 全部未知日期 -> 不画 bar；但 2 个来源 -> 仍出 pie
    assert "bar" not in types
    assert types == ["pie"]


def test_build_deepsearch_chart_specs_mixed_known_and_unknown_date() -> None:
    # 部分可解析 + 部分未知：bar 末尾补「未知日期」组
    docs = [
        {"source": "reuters", "published_date": "2026-05-01"},
        {"source": "reuters", "published_date": None},
        {"source": "reuters", "published_date": "bad"},
    ]
    specs = build_deepsearch_chart_specs(docs)
    bar = next(item for item in specs if item["type"] == "bar")
    assert bar["data"]["labels"] == ["2026-05-01", "未知日期"]
    assert bar["data"]["values"] == [1, 2]

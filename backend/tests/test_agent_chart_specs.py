# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.agents.chart_specs_extra import (
    build_macro_chart_specs,
    build_risk_chart_specs,
    build_technical_chart_specs,
)
from backend.agents.fundamental_agent import FundamentalAgent
from backend.agents.macro_agent import MacroAgent
from backend.agents.news_agent import NewsAgent, NewsSentimentSnapshot
from backend.agents.price_agent import PriceAgent
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


def test_price_agent_snapshot_output_contains_smart_chart_specs() -> None:
    agent = PriceAgent(None, _Cache(), _Tools())
    snapshot = {
        "snapshot_type": "PriceBehaviorSnapshot",
        "ticker": "AAPL",
        "as_of": "2026-05-31T00:00:00Z",
        "quote": {"ticker": "AAPL", "price": 107.0, "currency": "USD", "source": "fixture"},
        "trend": {"returns": {"1mo": 4.2}, "direction": "uptrend"},
        "momentum": {},
        "volume_price": {},
        "relative_strength": {"benchmarks": {"SPY": {"rs_1mo": 1.1}, "QQQ": {"rs_1mo": 0.8}}},
        "volatility_structure": {},
        "key_levels": {},
        "raw": {
            "history": {"source": "fixture_history", "kline_data": _history_rows("AAPL", 100.0)},
            "benchmarks": {
                "SPY": {"source": "fixture_history", "kline_data": _history_rows("SPY", 80.0)},
                "QQQ": {"source": "fixture_history", "kline_data": _history_rows("QQQ", 90.0)},
            },
        },
        "sources": ["fixture"],
    }

    output = agent._format_snapshot_output("", snapshot)

    specs = output.chart_specs
    assert [item["type"] for item in specs] == ["candlestick", "price_volume", "rs_line"]
    assert specs[0]["data"]["ohlc"][0] == [100.5, 101.0, 100.0, 102.5]
    assert len(specs[1]["data"]["volume"]) == len(specs[1]["data"]["labels"])
    assert [series["name"] for series in specs[2]["data"]["series"]] == ["AAPL", "SPY", "QQQ"]


def test_news_agent_sentiment_snapshot_output_contains_pie_and_line_specs() -> None:
    agent = NewsAgent(None, _Cache(), _Tools())
    agent._last_sentiment_snapshot = NewsSentimentSnapshot(
        ticker="AAPL",
        as_of="2026-05-31T00:00:00Z",
        sentiment_bias={
            "label": "bullish",
            "average_score": 0.24,
            "positive_count": 3,
            "negative_count": 1,
            "neutral_count": 2,
            "positive_ratio": 0.5,
            "negative_ratio": 0.1667,
            "neutral_ratio": 0.3333,
            "sample_size": 6,
            "confidence": 0.75,
        },
        sentiment_trend={
            "direction": "improving",
            "recent_average": 0.32,
            "previous_average": 0.05,
            "delta": 0.27,
        },
        heat={"level": "active", "news_count": 6, "event_count": 1},
        catalyst_events={"count": 1, "events": []},
        price_transmission={"status": "resonance"},
    )

    output = agent._format_output("summary", [{"headline": "Apple services revenue beats", "source": "Reuters"}])

    specs = output.chart_specs
    assert [item["type"] for item in specs] == ["pie", "line"]
    assert specs[0]["data"] == {
        "labels": ["Positive", "Neutral", "Negative"],
        "values": [3, 2, 1],
    }
    assert specs[1]["data"]["labels"] == ["Previous", "Recent"]
    assert specs[1]["data"]["values"] == [0.05, 0.32]


def test_fundamental_agent_output_contains_bar_and_waterfall_specs() -> None:
    agent = FundamentalAgent(None, _Cache(), _Tools())
    normalized = {
        "period_context": {"latest_period": "2026-03-31", "period_type": "quarterly"},
        "metrics": {
            "revenue": {"label": "营收", "latest": 92_000_000_000, "yoy": 0.08, "latest_period": "2026-03-31"},
            "net_income": {"label": "净利润", "latest": 24_000_000_000, "yoy": 0.04, "latest_period": "2026-03-31"},
            "operating_cash_flow": {"label": "经营现金流", "latest": 28_000_000_000, "yoy": 0.12, "latest_period": "2026-03-31"},
        },
    }

    output = agent._format_output(
        "summary",
        {"ticker": "AAPL", "financials": {}, "normalized_metrics": normalized},
    )

    specs = output.chart_specs
    assert [item["type"] for item in specs] == ["bar", "waterfall"]
    assert specs[0]["data"]["labels"] == ["营收", "净利润", "经营现金流"]
    assert specs[0]["data"]["unit"] == "$B"
    assert specs[1]["data"]["labels"] == ["营收 YoY", "净利润 YoY", "经营现金流 YoY"]
    assert specs[1]["data"]["values"] == [8.0, 4.0, 12.0]


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


def test_macro_agent_format_output_attaches_chart_specs() -> None:
    agent = MacroAgent(None, _Cache(), _Tools())
    raw_data = {
        "status": "success",
        "used_sources": ["fred"],
        "indicators": [
            {"key": "fed_rate", "name": "Federal funds rate", "value": 4.5, "unit": "%", "source": "fred"},
            {"key": "cpi", "name": "CPI inflation", "value": 3.1, "unit": "%", "source": "fred"},
        ],
    }
    output = agent._format_output("macro summary", raw_data)
    assert len(output.chart_specs) == 1
    assert output.chart_specs[0]["type"] == "bar"


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

# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.agents.fundamental_agent import FundamentalAgent
from backend.agents.news_agent import NewsAgent, NewsSentimentSnapshot
from backend.agents.price_agent import PriceAgent


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

# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from backend.api.backtest_prefill import build_backtest_prefill


@pytest.mark.parametrize(
    ("stance", "expected_strategy"),
    [
        ("bullish", "buy_and_hold"),
        ("neutral", "ma_cross"),
        ("bearish", "ma_cross"),
        ("BUY", "buy_and_hold"),
        ("强烈买入", "buy_and_hold"),
    ],
)
def test_build_backtest_prefill_maps_report_stance(stance: str, expected_strategy: str) -> None:
    result = build_backtest_prefill(
        {
            "report_id": "rpt-1",
            "title": "Apple research",
            "ticker": " aapl ",
            "generated_at": "2026-07-11T08:30:00+00:00",
            "stance": stance,
        }
    )

    assert result["config"] == {
        "tickers": ["AAPL"],
        "strategy": expected_strategy,
        "start": "2025-07-11",
        "end": "2026-07-11",
        "rationale": f"由报告《Apple research》生成：主标的 AAPL，观点 {stance}",
    }
    assert result["warnings"] == []


def test_build_backtest_prefill_defaults_missing_stance_and_normalizes_tickers() -> None:
    result = build_backtest_prefill(
        {
            "report_id": "rpt-2",
            "title": "Multi asset",
            "tickers": ["msft", "AAPL", "msft", ""],
            "generated_at": "2024-02-29T12:00:00Z",
        }
    )

    assert result["config"]["tickers"] == ["MSFT", "AAPL"]
    assert result["config"]["strategy"] == "buy_and_hold"
    assert result["config"]["start"] == "2023-02-28"
    assert result["config"]["end"] == "2024-02-29"
    assert result["warnings"] == ["报告缺少明确观点，已默认使用买入并持有策略"]


def test_build_backtest_prefill_prefers_recommendation_over_default_neutral_sentiment() -> None:
    result = build_backtest_prefill(
        {
            "report_id": "rpt-2b",
            "ticker": "NVDA",
            "generated_at": "2026-07-11",
            "sentiment": "neutral",
            "recommendation": "BUY",
        }
    )

    assert result["config"]["strategy"] == "buy_and_hold"
    assert "观点 BUY" in result["config"]["rationale"]


def test_build_backtest_prefill_requires_ticker_and_date() -> None:
    with pytest.raises(ValueError, match="ticker"):
        build_backtest_prefill({"report_id": "rpt-3", "generated_at": "2026-07-11"})

    with pytest.raises(ValueError, match="generated_at"):
        build_backtest_prefill({"report_id": "rpt-3", "ticker": "AAPL"})

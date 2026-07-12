# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from backend.agents.prediction_submit import (
    evaluate_prediction_bars,
    submit_prediction_with_async_correction,
    submit_prediction,
    submit_prediction_with_correction,
    submission_allowed,
)


def _draft(**overrides):
    payload = {
        "symbol": "FORGED",
        "agent": "forged_agent",
        "direction": "long",
        "confidence": 0.8,
        "thesis": "趋势延续",
        "anchor": {"timeframe": "1h", "time": "2026-07-10", "price": 102.0},
        "entry_type": "limit",
        "entry": 101.0,
        "stop": 96.0,
        "target1": 111.0,
        "invalidation_price": 95.0,
        "scenarios": [
            {"name": "延续", "probability": 60, "invalidation": "跌破止损"},
            {"name": "失败", "probability": 40, "invalidation": "突破目标"},
        ],
    }
    payload.update(overrides)
    return payload


class RecordingStore:
    def __init__(self):
        self.saved = None

    def create(self, prediction):
        self.saved = prediction
        return prediction


def test_submit_overrides_identity_symbol_agent_run_and_anchor_from_real_bar():
    store = RecordingStore()
    result = submit_prediction(
        _draft(anchor={"timeframe": "1d", "time": "2026-07-10", "price": 103.0}),
        symbol="aapl",
        agent="technical_agent",
        user_id="alice",
        run_id="run-real",
        operation="technical",
        fetch_bars=lambda _symbol, **_kwargs: {
            "kline_data": [
                {"time": "2026-07-09", "open": 98, "high": 102, "low": 97, "close": 100},
                {"time": "2026-07-10", "open": 100, "high": 104, "low": 99, "close": 103},
            ],
            "interval": "1d",
        },
        store=store,
    )

    assert result.symbol == "AAPL"
    assert result.agent == "technical_agent"
    assert result.user_id == "alice"
    assert result.run_id == "run-real"
    assert result.anchor.time == "2026-07-10"
    assert result.anchor.price == 103.0
    assert store.saved == result


@pytest.mark.parametrize("operation", ["investment_opinion", "technical", "earnings_impact", "report_generation"])
def test_only_scoring_operations_with_concrete_ticker_are_allowed(operation: str):
    assert submission_allowed(symbol="AAPL", operation=operation)


@pytest.mark.parametrize("symbol,operation", [("", "technical"), ("UNKNOWN", "technical"), ("AAPL", "macro")])
def test_non_scoring_or_non_concrete_steps_do_not_submit(symbol: str, operation: str):
    assert not submission_allowed(symbol=symbol, operation=operation)
    with pytest.raises(ValueError):
        submit_prediction(
            _draft(), symbol=symbol, agent="technical_agent", user_id="alice", run_id="run",
            operation=operation, fetch_bars=lambda *_args, **_kwargs: {"kline_data": []}, store=RecordingStore(),
        )


@pytest.mark.parametrize("agent", ["macro_agent", "news_agent", "deep_search_agent"])
def test_non_scoring_agents_are_not_eligible(agent: str):
    assert not submission_allowed(symbol="AAPL", operation="technical", agent=agent)


def test_submit_fails_closed_when_market_anchor_is_unavailable():
    with pytest.raises(ValueError, match="真实行情锚点"):
        submit_prediction(
            _draft(), symbol="AAPL", agent="technical_agent", user_id="alice", run_id="run",
            operation="technical", fetch_bars=lambda *_args, **_kwargs: {"error": "down"}, store=RecordingStore(),
        )


@pytest.mark.parametrize("anchor", [
    {"timeframe": "1d", "time": "2026-07-09", "price": 102.0},
    {"timeframe": "1d", "time": "2026-07-10", "price": 110.0},
])
def test_submit_rejects_forged_anchor_before_server_overwrite(anchor):
    with pytest.raises(ValueError, match="anchor"):
        submit_prediction(
            _draft(anchor=anchor),
            symbol="AAPL", agent="technical_agent", user_id="alice", run_id="run",
            operation="technical",
            fetch_bars=lambda *_args, **_kwargs: {
                "kline_data": [{"time": "2026-07-10", "open": 100, "high": 103, "low": 99, "close": 102}],
                "interval": "1d",
            },
            store=RecordingStore(),
        )


def test_invalid_prediction_gets_one_correction_then_stores_or_returns_none():
    store = RecordingStore()
    attempts = []

    def corrected(feedback):
        attempts.append(feedback)
        return _draft(bars=[]) if feedback is None else _draft()

    result = submit_prediction_with_correction(
        corrected,
        symbol="AAPL", agent="technical_agent", user_id="alice", run_id="run",
        operation="technical",
        fetch_bars=lambda *_args, **_kwargs: {
            "kline_data": [{"time": "2026-07-10", "open": 100, "high": 103, "low": 99, "close": 102}],
            "interval": "1d",
        },
        store=store,
    )
    assert result is store.saved
    assert len(attempts) == 2 and attempts[1]

    never_store = RecordingStore()
    rejected = submit_prediction_with_correction(
        lambda _feedback: _draft(data=[]),
        symbol="AAPL", agent="technical_agent", user_id="alice", run_id="run",
        operation="technical",
        fetch_bars=lambda *_args, **_kwargs: {"kline_data": []},
        store=never_store,
    )
    assert rejected is None
    assert never_store.saved is None


@pytest.mark.asyncio
async def test_async_submission_returns_structured_issues_then_accepts_one_correction():
    store = RecordingStore()
    feedbacks = []

    async def generate(feedback):
        feedbacks.append(feedback)
        if feedback is None:
            return _draft(stop=105.0)
        return _draft()

    prediction, trace = await submit_prediction_with_async_correction(
        generate,
        symbol="AAPL", agent="technical_agent", user_id="alice", run_id="run",
        operation="technical",
        fetch_bars=lambda *_args, **_kwargs: {
            "kline_data": [{"time": "2026-07-10", "open": 100, "high": 103, "low": 99, "close": 102}],
            "interval": "1d",
        },
        store=store,
    )

    assert prediction is store.saved
    assert [item["ok"] for item in trace] == [False, True]
    assert trace[0]["issues"][0]["field"]
    assert feedbacks[1] == trace[0]["issues"]


def test_bar_rules_limit_market_stop_invalidation_gap_and_same_bar_conservative():
    anchor = {"time": "2026-07-10", "open": 100, "high": 103, "low": 99, "close": 102}

    market = evaluate_prediction_bars(
        _draft(entry_type="market"),
        [anchor, {"time": "2026-07-11", "open": 104, "high": 108, "low": 103, "close": 107}],
    )
    assert market.status == "open"
    assert market.entry_price == 104.0

    limit_gap = evaluate_prediction_bars(
        _draft(entry_type="limit", entry=101.0),
        [anchor, {"time": "2026-07-11", "open": 99, "high": 102, "low": 98, "close": 100}],
    )
    assert limit_gap.entry_price == 99.0

    stop_gap = evaluate_prediction_bars(
        _draft(entry_type="stop", entry=105.0, target1=115.0),
        [anchor, {"time": "2026-07-11", "open": 107, "high": 110, "low": 106, "close": 109}],
    )
    assert stop_gap.entry_price == 107.0

    invalidated = evaluate_prediction_bars(
        _draft(entry_type="limit", entry=101.0, invalidation_price=95.0),
        [anchor, {"time": "2026-07-11", "open": 97, "high": 100, "low": 94, "close": 96}],
    )
    assert invalidated.status == "invalidated"

    same_bar = evaluate_prediction_bars(
        _draft(entry_type="limit", entry=101.0, stop=96.0, target1=111.0),
        [anchor, {"time": "2026-07-11", "open": 101, "high": 112, "low": 95, "close": 108}],
    )
    assert same_bar.status == "hit_stop"

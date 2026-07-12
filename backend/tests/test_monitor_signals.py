# -*- coding: utf-8 -*-
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from backend.agents.prediction_contract import AgentPrediction
from backend.services.monitor_signals import (
    MarketSnapshot,
    detect_triggers,
    heartbeat_due,
)


NOW = datetime(2026, 7, 10, 15, 0, tzinfo=timezone.utc)


def _snapshot(**overrides) -> MarketSnapshot:
    data = {
        "symbol": "AAPL",
        "observed_at": "2026-07-10T15:00:00+00:00",
        "price": 100.0,
        "volume": 100.0,
        "average_volume20": 100.0,
        "macd_hist": -0.2,
        "flow_value": -10.0,
        "flow_peak_abs": 100.0,
        "previous_day_high": 110.0,
        "previous_day_low": 90.0,
        "levels": {"pivot": 105.0},
        "zones": {"value_zone": (98.0, 102.0)},
    }
    data.update(overrides)
    return MarketSnapshot(**data)


def _prediction(**overrides) -> AgentPrediction:
    data = {
        "id": "pred-1", "user_id": "alice", "run_id": "run-1",
        "symbol": "AAPL", "agent": "technical_agent", "direction": "long",
        "confidence": 0.8, "thesis": "突破延续",
        "anchor": {"timeframe": "1d", "time": "2026-07-09", "price": 100.0},
        "entry_type": "stop", "entry": 105.0, "stop": 95.0, "target1": 120.0,
        "target2": 130.0, "invalidation_price": 94.0,
        "status": "waiting", "created_at": NOW, "updated_at": NOW,
    }
    data.update(overrides)
    return AgentPrediction.model_validate(data)


def test_level_and_day_level_cross_details_are_deterministic():
    previous = _snapshot(price=104.0)
    current = _snapshot(price=111.0, observed_at="2026-07-10T15:01:00+00:00")
    triggers = detect_triggers(previous=previous, current=current, prediction=_prediction())

    assert [(item.kind, item.detail) for item in triggers[:3]] == [
        ("level_break", "entry 上穿：104.0000 → 111.0000，命中价位 105.0000"),
        ("level_break", "pivot 上穿：104.0000 → 111.0000，命中价位 105.0000"),
        ("day_level_break", "previous_day_high 上穿：104.0000 → 111.0000，命中价位 110.0000"),
    ]

    downward = detect_triggers(
        previous=_snapshot(price=106.0),
        current=_snapshot(price=89.0),
        prediction=None,
    )
    assert any(t.kind == "level_break" and "pivot 下穿" in t.detail for t in downward)
    assert any(t.kind == "day_level_break" and "previous_day_low 下穿" in t.detail for t in downward)


def test_zone_enter_and_exit_are_detected():
    entered = detect_triggers(
        previous=_snapshot(price=97.0),
        current=_snapshot(price=100.0),
        prediction=None,
    )
    assert any(t.kind == "zone_break" and "进入 value_zone" in t.detail for t in entered)

    exited = detect_triggers(
        previous=_snapshot(price=100.0),
        current=_snapshot(price=103.0),
        prediction=None,
    )
    assert any(t.kind == "zone_break" and "离开 value_zone" in t.detail for t in exited)


def test_macd_flow_and_volume_triggers_with_flow_jitter_suppression():
    previous = _snapshot(macd_hist=-0.01, flow_value=-20.0)
    current = _snapshot(macd_hist=0.02, flow_value=10.0, volume=301.0)
    kinds = [t.kind for t in detect_triggers(previous=previous, current=current, prediction=None)]
    assert kinds[-3:] == ["macd_cross", "flow_flip", "volume_spike"]

    jitter = detect_triggers(
        previous=_snapshot(flow_value=-20.0, flow_peak_abs=100.0),
        current=_snapshot(flow_value=4.9, flow_peak_abs=100.0),
        prediction=None,
    )
    assert not any(t.kind == "flow_flip" for t in jitter)


def test_heartbeat_boundary_is_exactly_300_seconds():
    assert not heartbeat_due(last_comment_at=NOW, now=NOW + timedelta(seconds=299))
    assert heartbeat_due(last_comment_at=NOW, now=NOW + timedelta(seconds=300))
    assert heartbeat_due(last_comment_at=None, now=NOW)


def test_missing_core_market_data_returns_data_gap_not_fake_signal():
    triggers = detect_triggers(
        previous=_snapshot(),
        current=_snapshot(price=None),
        prediction=None,
    )
    assert len(triggers) == 1
    assert triggers[0].kind == "data_gap"
    assert "price" in triggers[0].detail

    mismatch = detect_triggers(
        previous=_snapshot(symbol="MSFT"),
        current=_snapshot(symbol="AAPL"),
        prediction=None,
    )
    assert [item.kind for item in mismatch] == ["data_gap"]

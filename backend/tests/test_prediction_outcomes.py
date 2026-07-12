# -*- coding: utf-8 -*-
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from backend.agents.prediction_contract import AgentPrediction
from backend.services.prediction_outcomes import PredictionOutcomeStore, resolve_prediction_outcome, summarize_track_record


NOW = datetime(2026, 7, 10, tzinfo=timezone.utc)


def _prediction(**overrides) -> AgentPrediction:
    payload = {
        "id": "00000000-0000-0000-0000-000000000001",
        "user_id": "alice", "run_id": "run-1", "symbol": "AAPL", "agent": "technical_agent",
        "direction": "long", "confidence": 0.8, "thesis": "趋势延续",
        "anchor": {"timeframe": "1d", "time": "2026-07-10", "price": 100.0},
        "entry_type": "limit", "entry": 101.0, "stop": 96.0, "target1": 111.0,
        "invalidation_price": 95.0,
        "scenarios": [
            {"name": "延续", "probability": 60, "invalidation": "跌破止损"},
            {"name": "失败", "probability": 40, "invalidation": "突破目标"},
        ],
        "status": "waiting", "created_at": NOW, "updated_at": NOW,
    }
    payload.update(overrides)
    return AgentPrediction.model_validate(payload)


def _bar(day: int, *, open=100, high=104, low=99, close=102):
    return {"time": f"2026-07-{day:02d}", "open": open, "high": high, "low": low, "close": close}


def test_directional_outcomes_cover_waiting_triggered_open_and_terminal_states():
    prediction = _prediction()
    assert resolve_prediction_outcome(prediction, []).status == "waiting"
    assert resolve_prediction_outcome(prediction, [_bar(11, high=100, low=97)]).status == "waiting"
    assert resolve_prediction_outcome(prediction, [_bar(11, high=103, low=99)]).status == "triggered"
    assert resolve_prediction_outcome(
        prediction, [_bar(11, high=103, low=99), _bar(12, high=108, low=98)]
    ).status == "open"
    assert resolve_prediction_outcome(prediction, [_bar(11, high=112, low=99)]).status == "hit_target"
    stopped = resolve_prediction_outcome(prediction, [_bar(11, high=112, low=96)])
    assert stopped.status == "hit_stop"
    assert stopped.resolution_reason == "same_bar_conservative"
    invalidated = resolve_prediction_outcome(prediction, [_bar(11, high=100, low=94)])
    assert invalidated.status == "invalidated"


def test_neutral_uses_ten_trading_day_close_window_not_intraday_wicks():
    neutral = _prediction(
        direction="neutral", entry_type=None, entry=None, stop=None, target1=None,
        invalidation_price=None, range_low=95.0, range_high=105.0,
    )
    nine = [_bar(day, high=120, low=80, close=100) for day in range(11, 20)]
    assert resolve_prediction_outcome(neutral, nine).status == "open"
    held = resolve_prediction_outcome(neutral, nine + [_bar(20, close=104)])
    assert held.status == "held_range"
    assert held.resolution_reason == "ten_trading_days_held"
    broke = resolve_prediction_outcome(neutral, [_bar(11, close=106)])
    assert broke.status == "broke_range"
    assert broke.resolution_reason == "close_outside_range"


def test_outcome_resolution_is_idempotent_and_ignores_invalid_or_pre_anchor_bars():
    prediction = _prediction()
    bars = [
        _bar(9, high=999, low=1),
        {"time": "2026-07-11", "open": None, "high": 103, "low": 99, "close": 102},
        _bar(12, high=112, low=99, close=110),
    ]
    first = resolve_prediction_outcome(prediction, bars)
    second = resolve_prediction_outcome(prediction, list(reversed(bars)))
    assert first.model_dump() == second.model_dump()
    assert first.status == "hit_target"
    assert first.evaluated_through == "2026-07-12"


def test_track_record_excludes_invalidated_and_hides_rate_below_five_samples():
    sparse = summarize_track_record([
        {"direction": "long", "status": "hit_target", "count": 2, "latest": "2026-07-12"},
        {"direction": "long", "status": "hit_stop", "count": 1, "latest": "2026-07-13"},
        {"direction": "long", "status": "invalidated", "count": 4, "latest": "2026-07-14"},
    ])
    assert sparse["sample_count"] == 3
    assert sparse["invalidated"] == 4
    assert sparse["hit_rate"] is None
    assert sparse["sample_state"] == "样本不足"

    sufficient = summarize_track_record([
        {"direction": "long", "status": "hit_target", "count": 4},
        {"direction": "long", "status": "hit_stop", "count": 1},
    ])
    assert sufficient["hit_rate"] == 0.8


class _Result:
    def __init__(self, rows=None): self._rows = rows or []
    def mappings(self): return self
    def all(self): return self._rows


class _Connection:
    def __init__(self): self.calls = []; self.rows = []
    def execute(self, statement, params=None):
        self.calls.append((str(statement), params or {}))
        return _Result(self.rows)


class _Engine:
    def __init__(self): self.conn = _Connection()
    @contextmanager
    def begin(self): yield self.conn
    @contextmanager
    def connect(self): yield self.conn


def test_outcome_store_schema_upsert_and_queries_are_tenant_safe(monkeypatch):
    monkeypatch.setattr(
        "backend.services.agent_prediction_store.get_agent_prediction_store",
        lambda: type("S", (), {"ensure_schema": lambda self: True})(),
    )
    engine = _Engine()
    store = PredictionOutcomeStore(engine=engine)
    assert store.ensure_schema()
    schema = "\n".join(sql for sql, _ in engine.conn.calls)
    assert "PRIMARY KEY(prediction_id, user_id)" in schema
    assert "FOREIGN KEY(prediction_id, user_id)" in schema
    assert "user_id, status, updated_at DESC" in schema

    outcome = resolve_prediction_outcome(_prediction(), [_bar(11, high=112, low=99)])
    store.upsert(outcome)
    upsert_sql, first_params = engine.conn.calls[-1]
    assert "ON CONFLICT(prediction_id,user_id)" in upsert_sql
    assert "GREATEST(agent_prediction_outcomes.evaluated_through,excluded.evaluated_through)" in upsert_sql
    store.upsert(outcome)
    assert engine.conn.calls[-1][1] == first_params

    engine.conn.rows = []
    store.pending_predictions(limit=20)
    pending_sql, pending_params = engine.conn.calls[-1]
    assert "o.user_id=p.user_id" in pending_sql
    assert "o.status NOT IN" in pending_sql
    assert pending_params == {"limit": 20}

    store.track_record(user_id="alice", agent="technical_agent", days=90)
    track_sql, track_params = engine.conn.calls[-1]
    assert "o.user_id=:user_id AND p.agent=:agent" in track_sql
    assert ":days * interval '1 day'" in track_sql
    assert track_params == {"user_id": "alice", "agent": "technical_agent", "days": 90}

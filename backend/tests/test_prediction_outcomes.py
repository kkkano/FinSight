# -*- coding: utf-8 -*-
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

from backend.agents.prediction_contract import AgentPrediction
from backend.services.prediction_outcomes import (
    OUTCOME_ALGORITHM_VERSION,
    PredictionOutcomeStore,
    resolve_prediction_outcome,
    run_prediction_outcome_cycle,
    summarize_track_record,
)


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


def test_outcome_records_market_provenance_and_algorithm_version():
    outcome = resolve_prediction_outcome(
        _prediction(),
        [_bar(11, high=112, low=99)],
        market_provider="fixture-provider",
        market_as_of="2026-07-11T21:00:00Z",
    )
    assert outcome.market_provider == "fixture-provider"
    assert outcome.market_as_of == "2026-07-11T21:00:00Z"
    assert outcome.algorithm_version == OUTCOME_ALGORITHM_VERSION


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


def test_outcome_store_has_no_ddl_and_queries_are_tenant_safe():
    engine = _Engine()
    store = PredictionOutcomeStore(engine=engine)
    assert not hasattr(store, "ensure_schema")
    assert engine.conn.calls == []

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

    store.pending_predictions(
        user_id="alice",
        prediction_id="00000000-0000-0000-0000-000000000001",
        limit=7,
    )
    scoped_sql, scoped_params = engine.conn.calls[-1]
    assert "p.user_id=:user_id" in scoped_sql
    assert "p.id=CAST(:prediction_id AS uuid)" in scoped_sql
    assert scoped_params == {
        "limit": 7,
        "user_id": "alice",
        "prediction_id": "00000000-0000-0000-0000-000000000001",
    }

    store.track_record(user_id="alice", agent="technical_agent", days=90)
    track_sql, track_params = engine.conn.calls[-1]
    assert "o.user_id=:user_id AND p.agent=:agent" in track_sql
    assert ":days * interval '1 day'" in track_sql
    assert track_params == {"user_id": "alice", "agent": "technical_agent", "days": 90}


class _CycleStore:
    def __init__(self):
        self.predictions = [
            _prediction(),
            _prediction(id="00000000-0000-0000-0000-000000000002", symbol="MSFT"),
        ]
        self.pending_kwargs = None
        self.outcomes = []

    def pending_predictions(self, **kwargs):
        self.pending_kwargs = kwargs
        return self.predictions

    def upsert(self, outcome):
        self.outcomes.append(outcome)
        return outcome


class _CycleGateway:
    def __init__(self):
        self.calls = 0

    def get_kline(self, _symbol, **_kwargs):
        self.calls += 1
        if self.calls == 1:
            return {
                "quality": "trusted",
                "error_code": None,
                "provider": "fixture-provider",
                "as_of": "2026-07-11T21:00:00Z",
                "kline_data": [_bar(11, high=112, low=99)],
            }
        return {
            "quality": "degraded",
            "error_code": "market_data_unavailable",
            "provider": None,
            "as_of": None,
            "kline_data": [],
        }


def test_outcome_cycle_uses_gateway_scopes_recompute_and_writes_data_pending():
    store = _CycleStore()
    gateway = _CycleGateway()
    processed = run_prediction_outcome_cycle(
        user_id="alice",
        prediction_id="00000000-0000-0000-0000-000000000001",
        limit=10,
        store=store,
        market_gateway=gateway,
    )

    assert processed == 2
    assert store.pending_kwargs == {
        "user_id": "alice",
        "prediction_id": "00000000-0000-0000-0000-000000000001",
        "limit": 10,
    }
    assert store.outcomes[0].status == "hit_target"
    assert store.outcomes[0].market_provider == "fixture-provider"
    assert store.outcomes[1].status == "data_pending"
    assert store.outcomes[1].resolution_reason == "market_data_unavailable"
    assert all(item.algorithm_version == OUTCOME_ALGORITHM_VERSION for item in store.outcomes)

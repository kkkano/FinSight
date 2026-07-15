from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from backend.services import monitor_engine, prediction_service
from backend.services.monitor_signals import MarketSnapshot


class LeaseStore:
    def __init__(self, leases, *, acquired=True):
        self.leases = leases
        self.acquired = acquired
        self.cleaned = 0

    @contextmanager
    def realtime_tick_lock(self):
        yield self.acquired

    def cleanup_expired(self, *, now):
        del now
        self.cleaned += 1
        return 0

    def list_active(self, *, now):
        del now
        return list(self.leases)


class CommentStore:
    def __init__(self):
        self.last_comment = None
        self.last_escalation = None
        self.calls = []

    def latest_comment_at(self, **kwargs):
        self.calls.append(("comment", kwargs))
        return self.last_comment

    def latest_escalation_at(self, **kwargs):
        self.calls.append(("escalation", kwargs))
        return self.last_escalation


def _lease(symbol="AAPL", lease_id="l1"):
    return {
        "id": lease_id,
        "user_id": "alice",
        "session_id": "s1",
        "symbol": symbol,
    }


def _open_market(monkeypatch):
    monkeypatch.setattr(monitor_engine, "get_market_session", lambda *_a, **_k: "regular")


def _configure_stores(monkeypatch, leases, *, acquired=True):
    lease_store = LeaseStore(leases, acquired=acquired)
    comment_store = CommentStore()
    monkeypatch.setattr(monitor_engine, "get_monitor_lease_store", lambda: lease_store)
    monkeypatch.setattr(monitor_engine, "get_monitor_comment_store", lambda: comment_store)
    monkeypatch.setattr(monitor_engine, "_latest_prediction", lambda _target: None)
    monitor_engine._realtime_snapshots.clear()
    return lease_store, comment_store


def test_no_active_lease_stops_before_market_comment_store_or_commentary(monkeypatch):
    lease_store = LeaseStore([])
    monkeypatch.setattr(monitor_engine, "get_monitor_lease_store", lambda: lease_store)
    monkeypatch.setattr(
        monitor_engine,
        "get_monitor_comment_store",
        lambda: (_ for _ in ()).throw(AssertionError("comment store must not be resolved")),
    )
    called = {"market": 0, "comment": 0}

    result = monitor_engine.run_realtime_monitor_cycle(
        snapshot_fetcher=lambda *_a: called.__setitem__("market", called["market"] + 1),
        trigger_consumer=lambda *_a: called.__setitem__("comment", called["comment"] + 1),
    )

    assert result == 0
    assert called == {"market": 0, "comment": 0}
    assert lease_store.cleaned == 1


def test_advisory_lock_prevents_reentrant_tick(monkeypatch):
    lease_store = LeaseStore([_lease()], acquired=False)
    monkeypatch.setattr(monitor_engine, "get_monitor_lease_store", lambda: lease_store)
    assert monitor_engine.run_realtime_monitor_cycle() == 0
    assert lease_store.cleaned == 0


def test_duplicate_page_instances_share_one_symbol_tick(monkeypatch):
    _open_market(monkeypatch)
    _, comment_store = _configure_stores(
        monkeypatch,
        [_lease(lease_id="one"), _lease(lease_id="two")],
    )
    calls = []
    now = datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc)

    result = monitor_engine.run_realtime_monitor_cycle(
        now=now,
        snapshot_fetcher=lambda target, observed: MarketSnapshot(
            target.symbol, observed.isoformat(), 100.0,
        ),
        trigger_consumer=lambda target, snapshot, triggers, _prediction, escalated: (
            calls.append((target, snapshot, triggers, escalated)) or True
        ),
    )

    assert result == 1
    assert len(calls) == 1
    assert calls[0][0].symbol == "AAPL"
    assert calls[0][2][0].kind == "heartbeat"
    assert calls[0][3] is False
    assert len(comment_store.calls) == 1


def test_heartbeat_uses_persisted_comment_time_and_is_bounded(monkeypatch):
    _open_market(monkeypatch)
    _, comment_store = _configure_stores(monkeypatch, [_lease()])
    calls = []
    start = datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc)

    def consume(target, _snapshot, triggers, _prediction, _escalated):
        calls.append((target.symbol, triggers[0].kind))
        comment_store.last_comment = start if len(calls) == 1 else start + timedelta(seconds=300)
        return True

    fetcher = lambda target, observed: MarketSnapshot(
        target.symbol, observed.isoformat(), 100.0,
    )
    assert monitor_engine.run_realtime_monitor_cycle(
        now=start, snapshot_fetcher=fetcher, trigger_consumer=consume,
    ) == 1
    assert monitor_engine.run_realtime_monitor_cycle(
        now=start + timedelta(seconds=299), snapshot_fetcher=fetcher, trigger_consumer=consume,
    ) == 0
    assert monitor_engine.run_realtime_monitor_cycle(
        now=start + timedelta(seconds=300), snapshot_fetcher=fetcher, trigger_consumer=consume,
    ) == 1
    assert calls == [("AAPL", "heartbeat"), ("AAPL", "heartbeat")]


def test_default_fetcher_rejects_degraded_quote(monkeypatch):
    _open_market(monkeypatch)
    _configure_stores(monkeypatch, [_lease()])
    gateway = SimpleNamespace(
        get_quote=lambda _symbol: {
            "quality": "degraded",
            "error_code": None,
            "quote": {"price": 100.0},
        },
    )
    monkeypatch.setattr(monitor_engine, "get_market_data_gateway", lambda: gateway)

    assert monitor_engine.run_realtime_monitor_cycle(
        now=datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc),
    ) == 0


def test_prediction_level_break_queues_once_then_obeys_cooldown(monkeypatch):
    _open_market(monkeypatch)
    _, comment_store = _configure_stores(monkeypatch, [_lease()])
    now = datetime(2026, 7, 13, 14, 0, tzinfo=timezone.utc)
    key = ("alice", "s1", "AAPL")
    prediction = SimpleNamespace(
        id="11111111-1111-1111-1111-111111111111",
        symbol="AAPL",
        direction="long",
        entry=105.0,
        stop=95.0,
        target1=120.0,
        target2=None,
        invalidation_price=94.0,
        range_low=None,
        range_high=None,
    )
    monkeypatch.setattr(monitor_engine, "_latest_prediction", lambda _target: prediction)
    queued = []
    monkeypatch.setattr(
        prediction_service,
        "get_prediction_service",
        lambda: SimpleNamespace(enqueue=lambda **kwargs: queued.append(kwargs) or (object(), True)),
    )
    calls = []

    def fetcher(target, observed):
        return MarketSnapshot(target.symbol, observed.isoformat(), 106.0)

    def consume(_target, _snapshot, triggers, _prediction, escalated):
        calls.append((triggers[0].kind, escalated))
        return True

    monitor_engine._realtime_snapshots[key] = MarketSnapshot("AAPL", now.isoformat(), 100.0)
    assert monitor_engine.run_realtime_monitor_cycle(
        now=now, snapshot_fetcher=fetcher, trigger_consumer=consume,
    ) == 1
    assert queued == [{"user_id": "alice", "symbol": "AAPL", "timeframe": "1d"}]
    assert calls == [("prediction_level_break", True)]

    comment_store.last_escalation = now
    monitor_engine._realtime_snapshots[key] = MarketSnapshot("AAPL", now.isoformat(), 100.0)
    assert monitor_engine.run_realtime_monitor_cycle(
        now=now + timedelta(minutes=1), snapshot_fetcher=fetcher, trigger_consumer=consume,
    ) == 1
    assert len(queued) == 1
    assert calls[-1] == ("prediction_level_break", False)

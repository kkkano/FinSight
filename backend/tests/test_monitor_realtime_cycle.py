from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from backend.services import monitor_engine
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


def _lease(symbol="AAPL", lease_id="l1"):
    return {
        "id": lease_id,
        "user_id": "alice",
        "session_id": "s1",
        "symbol": symbol,
    }


def _open_market(monkeypatch):
    monkeypatch.setattr(monitor_engine, "get_market_session", lambda *_a, **_k: "regular")


def test_no_active_lease_stops_before_market_or_commentary(monkeypatch):
    store = LeaseStore([])
    monkeypatch.setattr(monitor_engine, "get_monitor_lease_store", lambda: store)
    called = {"market": 0, "comment": 0}

    result = monitor_engine.run_realtime_monitor_cycle(
        snapshot_fetcher=lambda *_a: called.__setitem__("market", called["market"] + 1),
        trigger_consumer=lambda *_a: called.__setitem__("comment", called["comment"] + 1),
    )

    assert result == 0
    assert called == {"market": 0, "comment": 0}
    assert store.cleaned == 1


def test_advisory_lock_prevents_reentrant_tick(monkeypatch):
    store = LeaseStore([_lease()], acquired=False)
    monkeypatch.setattr(monitor_engine, "get_monitor_lease_store", lambda: store)
    assert monitor_engine.run_realtime_monitor_cycle() == 0
    assert store.cleaned == 0


def test_duplicate_page_instances_share_one_symbol_tick(monkeypatch):
    _open_market(monkeypatch)
    store = LeaseStore([_lease(lease_id="one"), _lease(lease_id="two")])
    monkeypatch.setattr(monitor_engine, "get_monitor_lease_store", lambda: store)
    monkeypatch.setattr(monitor_engine, "get_monitor_store", lambda: type("S", (), {"list_targets": lambda *_a, **_k: []})())
    monitor_engine._realtime_snapshots.clear()
    monitor_engine._realtime_last_comment_at.clear()
    calls = []
    now = datetime(2026, 7, 11, 2, 0, tzinfo=timezone.utc)

    result = monitor_engine.run_realtime_monitor_cycle(
        now=now,
        snapshot_fetcher=lambda target, observed: MarketSnapshot(target.symbol, observed.isoformat(), 100.0),
        trigger_consumer=lambda target, snapshot, triggers: calls.append((target, snapshot, triggers)) or True,
    )

    assert result == 1
    assert len(calls) == 1
    assert calls[0][0].config == {}
    assert calls[0][2][0].kind == "heartbeat"


def test_persistent_target_config_is_inherited_and_heartbeat_is_bounded(monkeypatch):
    _open_market(monkeypatch)
    store = LeaseStore([_lease()])
    monkeypatch.setattr(monitor_engine, "get_monitor_lease_store", lambda: store)
    monkeypatch.setattr(
        monitor_engine,
        "get_monitor_store",
        lambda: type("S", (), {"list_targets": lambda *_a, **_k: [
            {"ticker": "AAPL", "enabled": True, "config": {"price_move_pct": 2.5}},
        ]})(),
    )
    monitor_engine._realtime_snapshots.clear()
    monitor_engine._realtime_last_comment_at.clear()
    calls = []
    start = datetime(2026, 7, 11, 2, 0, tzinfo=timezone.utc)
    fetcher = lambda target, observed: MarketSnapshot(target.symbol, observed.isoformat(), 100.0)
    consumer = lambda target, *_a: calls.append(target) or True

    assert monitor_engine.run_realtime_monitor_cycle(now=start, snapshot_fetcher=fetcher, trigger_consumer=consumer) == 1
    assert monitor_engine.run_realtime_monitor_cycle(now=start + timedelta(seconds=299), snapshot_fetcher=fetcher, trigger_consumer=consumer) == 0
    assert monitor_engine.run_realtime_monitor_cycle(now=start + timedelta(seconds=300), snapshot_fetcher=fetcher, trigger_consumer=consumer) == 1
    assert [call.config for call in calls] == [
        {"price_move_pct": 2.5},
        {"price_move_pct": 2.5},
    ]


def test_two_symbols_ten_minute_replay_dispatches_heartbeat_at_most_every_five_minutes(monkeypatch):
    _open_market(monkeypatch)
    store = LeaseStore([_lease("AAPL", "one"), _lease("MSFT", "two")])
    monkeypatch.setattr(monitor_engine, "get_monitor_lease_store", lambda: store)
    monkeypatch.setattr(monitor_engine, "get_monitor_store", lambda: type("S", (), {"list_targets": lambda *_a, **_k: []})())
    monitor_engine._realtime_snapshots.clear()
    monitor_engine._realtime_last_comment_at.clear()
    calls = []
    start = datetime(2026, 7, 11, 2, 0, tzinfo=timezone.utc)

    for minute in range(11):
        monitor_engine.run_realtime_monitor_cycle(
            now=start + timedelta(minutes=minute),
            snapshot_fetcher=lambda target, observed: MarketSnapshot(target.symbol, observed.isoformat(), 100.0),
            trigger_consumer=lambda target, _snapshot, triggers: calls.append((target.symbol, triggers[0].kind)) or True,
        )

    assert calls == [
        ("AAPL", "heartbeat"), ("MSFT", "heartbeat"),
        ("AAPL", "heartbeat"), ("MSFT", "heartbeat"),
        ("AAPL", "heartbeat"), ("MSFT", "heartbeat"),
    ]

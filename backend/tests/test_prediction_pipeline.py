from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from datetime import date, timedelta

import httpx
import pandas as pd
import pytest
from fastapi import FastAPI

from backend.services.prediction_calendar import iso, timestamp, window_for_date
from backend.services.prediction_market import load_bars
from backend.services.prediction_runner import collect_batch, prediction_health
from backend.services.prediction_settlement import score_window, settle_due
from backend.services.prediction_store import PredictionStore, TICKERS


@pytest.fixture
def window():
    return window_for_date(date(2026, 10, 2))


@pytest.fixture
def store(tmp_path):
    return PredictionStore(tmp_path / "predictions.db")


def snapshot(ticker, cutoff):
    return {"as_of": cutoff, "source": "test-fixture", "features": {"last_close": 100, "rsi": 50,
            "realized_vol20": .2, "max_drawdown60": .03}, "bars": []}


def predicted(agent, context, *, direction="down", event=True, issued=None):
    return {"status": "predicted", "prediction_type": "direction" if agent == "technical" else "drawdown",
            "direction": direction if agent == "technical" else None, "event_occurs": event if agent == "risk" else None,
            "reason": "固定测试样本，非真实预测", "evidence_refs": ["last_close"], "error_code": None,
            "retryable": False, "prompt_version": agent + "-fixture-v1", "issued_at": issued or context["issued_at"],
            "metadata": {"actual_model": "fixture-model", "model_confirmed": True,
                         "endpoint_alias": "private-endpoint", "api_key": "must-not-be-public"}}


async def collect(store, window, *, forecast=None, tickers=TICKERS, limit=60):
    now = timestamp(window.collection_at)
    async def successful(agent, context, data):
        return predicted(agent, context, issued=iso(now))
    return await collect_batch(store, window=window, clock=lambda: now, snapshot_loader=snapshot,
                               forecast=forecast or successful, tickers=tickers, limit=limit)


def bars_for(window, closes=(102, 101, 95, 98, 97)):
    return [{"time": day, "open": 100, "close": close, "high": 105, "low": 90, "volume": 1000}
            for day, close in zip(window.sessions, closes)]


def test_calendar_cross_year_early_close_and_dst():
    cross = window_for_date(date(2026, 12, 30))
    assert cross.sessions == ("2026-12-30", "2026-12-31", "2027-01-04", "2027-01-05", "2027-01-06")
    assert window_for_date(date(2027, 1, 1)) is None
    half = window_for_date(date(2026, 11, 20))
    assert half.window_end == "2026-11-27T18:00:00Z"
    assert window_for_date(date(2026, 3, 6)).window_start.endswith("14:30:00Z")
    assert window_for_date(date(2026, 3, 9)).window_start.endswith("13:30:00Z")


@pytest.mark.asyncio
async def test_40_successes_and_restart_do_not_reissue(store, window):
    first = await collect(store, window)
    second = await collect(PredictionStore(store.path), window)
    assert first["accepted"] == second["accepted"] == 40
    assert first["attempts"] == second["attempts"] == 40
    report = store.public_report()
    assert report["summary"]["pending"] == 40
    assert report["groups"] == []
    assert "must-not-be-public" not in json.dumps(report)
    assert "private-endpoint" not in json.dumps(report)


@pytest.mark.asyncio
async def test_retry_after_all_first_attempts_with_budget_60(store, window):
    calls = []
    identities = set()
    async def transient(agent, context, frozen):
        identity = (context["ticker"], agent)
        calls.append(identity)
        assert frozen == snapshot(context["ticker"], context["knowledge_cutoff"])
        if identity not in identities:
            identities.add(identity)
            return {"status": "failed", "retryable": True, "error_code": "timeout"}
        return predicted(agent, context, issued=window.collection_at)
    result = await collect(store, window, forecast=transient)
    assert len(set(calls[:40])) == 40
    assert len(calls) == result["attempts"] == 60
    assert result["accepted"] == 20
    await collect(store, window, forecast=transient)
    assert len(calls) == 60


@pytest.mark.asyncio
async def test_abstention_and_nonretryable_failure_do_not_reroll(store, window):
    async def no_prediction(agent, context, frozen):
        return {"status": "abstained" if agent == "risk" else "failed",
                "retryable": False, "error_code": "no_evidence"}
    result = await collect(store, window, forecast=no_prediction)
    assert result["attempts"] == 40
    assert result["accepted"] == 0
    assert result["counts"] == {"abstained": 20, "failed": 20}


@pytest.mark.asyncio
async def test_cutoff_reserves_margin_and_rejects_late_completion(store, window):
    late_start = timestamp(window.deadline_at) - timedelta(seconds=64)
    async def should_not_call(*args):
        pytest.fail("not enough time for a full attempt")
    result = await collect_batch(store, window=window, clock=lambda: late_start, snapshot_loader=snapshot, forecast=should_not_call)
    assert result["attempts"] == 0
    now = [timestamp(window.collection_at)]
    async def finishes_late(agent, context, frozen):
        now[0] = timestamp(window.deadline_at)
        return predicted(agent, context, issued=iso(now[0]))
    result = await collect_batch(store, window=window, clock=lambda: now[0], snapshot_loader=snapshot,
                                 forecast=finishes_late, tickers=TICKERS)
    assert result["accepted"] == 0
    assert result["counts"]["missed"] == 40


def test_recovery_preserves_attempt_charge(store, window):
    batch = store.ensure_batch(window, tickers=("AAPL",), now=timestamp(window.collection_at))
    rows = store.opportunities(batch)
    assert store.reserve_attempt(rows[0]["id"], now=timestamp(window.collection_at)) == 1
    restarted = PredictionStore(store.path)
    restarted.recover_interrupted()
    assert restarted.coverage(window.batch_date)["attempts"] == 1
    assert restarted.opportunities(batch)[0]["status"] == "interrupted"


@pytest.mark.asyncio
async def test_cross_day_restart_closes_every_old_uncollected_opportunity(store, window):
    batch = store.ensure_batch(window, now=timestamp(window.collection_at))
    row = store.opportunities(batch)[0]
    store.reserve_attempt(row["id"], now=timestamp(window.collection_at))
    restarted = PredictionStore(store.path)
    restarted.recover_interrupted()
    next_window = window_for_date(date(2026, 10, 5))
    await collect(restarted, next_window)
    assert restarted.coverage(window.batch_date)["counts"] == {"missed": 40}
    summary = restarted.public_report()["summary"]
    assert summary["opportunities"] == summary["pending"] + summary["missed"] == 80


@pytest.mark.asyncio
async def test_all_historical_records_are_pageable_and_abstentions_are_auditable(store, window):
    async def abstain(agent, context, frozen):
        return {"status": "abstained", "retryable": False, "error_code": None,
                "reason": "测试：信号冲突，主动弃权", "evidence_refs": ["last_close"],
                "prompt_version": "abstain-v1", "metadata": {"actual_model": "fixture", "model_confirmed": True}}
    await collect(store, window, forecast=abstain)
    for day in (5, 6, 7, 8, 9):
        await collect(store, window_for_date(date(2026, 10, day)))
    first = store.public_report(limit=200)
    second = store.public_report(limit=200, offset=200)
    assert first["pagination"]["has_more"] is True
    assert second["pagination"]["has_more"] is False
    assert len(first["records"]) + len(second["records"]) == first["summary"]["opportunities"] == 240
    assert all(row["reason"] == "测试：信号冲突，主动弃权" for row in second["records"])
    assert all(row["prompt_version"] == "abstain-v1" and row["actual_model"] == "fixture" for row in second["records"])


def test_hand_calculated_drawdown_and_direction(window):
    bars = bars_for(window)
    direction = score_window({"prediction_type": "direction", "direction": "down"}, bars, list(window.sessions))
    risk = score_window({"prediction_type": "drawdown", "event_occurs": True}, bars, list(window.sessions))
    assert direction["return_pct"] == pytest.approx(-.03)
    assert risk["max_drawdown"] == pytest.approx(1 - 95 / 102)
    assert direction["hit"] and not direction["baseline_hit"]
    assert risk["hit"] and not risk["baseline_hit"]


@pytest.mark.parametrize("end,direction", [(100.5, "flat"), (99.5, "flat"), (101, "up"), (99, "down")])
def test_direction_boundaries(window, end, direction):
    outcome = score_window({"prediction_type": "direction", "direction": direction}, bars_for(window, [100]*4+[end]), list(window.sessions))
    assert outcome["hit"]


def test_exact_risk_threshold(window):
    outcome = score_window({"prediction_type": "drawdown", "event_occurs": True}, bars_for(window, [100, 99, 95, 96, 97]), list(window.sessions))
    assert outcome["actual_event"] is True


@pytest.mark.asyncio
async def test_settlement_uses_same_window_and_survives_restart(store, window):
    await collect(store, window, tickers=("AAPL",))
    now = timestamp(window.window_end) + timedelta(minutes=21)
    loads = []
    def loader(ticker, start, end):
        loads.append(ticker)
        return bars_for(window)
    assert settle_due(store, now=now, loader=loader)["settled"] == 2
    assert loads == ["AAPL"]
    assert settle_due(PredictionStore(store.path), now=now, loader=loader)["settled"] == 0
    report = store.public_report()
    assert report["summary"]["settled"] == 2
    assert all(group["hit_rate"] == 1 and group["baseline_hit_rate"] == 0 for group in report["groups"])


@pytest.mark.asyncio
async def test_missing_price_stays_visible_then_settles(store, window):
    await collect(store, window, tickers=("AAPL",))
    now = timestamp(window.window_end) + timedelta(minutes=21)
    settle_due(store, now=now, loader=lambda *args: [])
    assert store.public_report()["summary"]["awaiting_data"] == 2
    assert store.public_report()["summary"]["settled"] == 0
    settle_due(store, now=now, loader=lambda *args: bars_for(window))
    assert store.public_report()["summary"]["settled"] == 2


@pytest.mark.parametrize("accepted,status,alert", [(38,"partial",False),(30,"partial",False),(29,"low_coverage",True)])
@pytest.mark.asyncio
async def test_health_coverage_threshold(store, window, accepted, status, alert):
    await collect(store, window, limit=accepted)
    health = prediction_health(store=store, now=timestamp(window.alert_at), is_enabled=True)
    assert health["accepted"] == accepted
    assert health["status"] == status and health["alert_required"] is alert


def test_health_missing_holiday_and_disabled(store, window):
    assert prediction_health(store=store, now=timestamp(window.alert_at), is_enabled=True)["status"] == "missing"
    assert prediction_health(store=store, now=timestamp("2027-01-01T16:00:00Z"), is_enabled=True)["status"] == "not_due"
    assert prediction_health(store=store, is_enabled=False)["status"] == "disabled"


def test_market_adapter_does_not_apply_dividend_adjustment(monkeypatch):
    import backend.tools.yfinance_client as yf_client
    options = {}
    frame = pd.DataFrame({"Open":[50,51], "High":[52,52], "Low":[49,49], "Close":[50,50],
                          "Adj Close":[49,50], "Volume":[100,100], "Dividends":[0,1], "Stock Splits":[2,0]},
                         index=pd.to_datetime(["2026-09-30", "2026-10-01"]))
    class FakeTicker:
        def history(self, **kwargs):
            options.update(kwargs)
            return frame
    monkeypatch.setattr(yf_client, "create_ticker", lambda _: FakeTicker())
    result = load_bars("AAPL", date(2026,9,30), date(2026,10,1))
    assert options["auto_adjust"] is False and options["back_adjust"] is False and options["repair"] is False
    assert result[0]["close"] == 50 and result[0]["stock_splits"] == 2
    assert result[1]["dividends"] == 1


@pytest.mark.asyncio
async def test_public_api_whitelist_and_limit(store, window, monkeypatch):
    import backend.api.prediction_router as module
    monkeypatch.setattr(module, "get_prediction_store", lambda: store)
    await collect(store, window)
    app = FastAPI()
    app.include_router(module.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/predictions/track-record?limit=2")
        assert response.status_code == 200 and len(response.json()["records"]) == 2
        for private in ("api_key", "must-not-be-public", "endpoint_alias", "context_json", "audit_json"):
            assert private not in response.text
        assert (await client.get("/api/predictions/track-record?limit=201")).status_code == 422


@pytest.mark.asyncio
async def test_market_failure_recovers_on_later_poll_with_same_cutoff(store, window):
    now = [timestamp(window.collection_at) + timedelta(minutes=1)]
    loads, calls = [], []

    def temporarily_unavailable(ticker, cutoff):
        loads.append((ticker, cutoff))
        if len(loads) <= 2:
            raise ConnectionError("fixture market outage")
        return snapshot(ticker, cutoff)

    async def successful(agent, context, frozen):
        calls.append((agent, frozen))
        return predicted(agent, context, issued=iso(now[0]))

    for minute in (1, 6):
        now[0] = timestamp(window.collection_at) + timedelta(minutes=minute)
        result = await collect_batch(store, window=window, clock=lambda: now[0],
                                     snapshot_loader=temporarily_unavailable, forecast=successful, tickers=("AAPL",))
        assert result["counts"] == {"queued": 2} and result["attempts"] == 0
        rows = store.opportunities("us20-v1:" + window.batch_date)
        assert all(row["error_code"] == "market_data_unavailable" and not row["retryable"] for row in rows)
        assert store.snapshot(rows[0]["batch_id"], "AAPL") is None
        assert not calls

    restarted = PredictionStore(store.path)
    now[0] = timestamp(window.collection_at) + timedelta(minutes=11)
    result = await collect_batch(restarted, window=window, clock=lambda: now[0],
                                 snapshot_loader=temporarily_unavailable, forecast=successful, tickers=("AAPL",))
    assert result["accepted"] == result["attempts"] == 2
    assert loads == [("AAPL", window.knowledge_cutoff)] * 3
    assert len(calls) == 2 and calls[0][1] == calls[1][1]
    assert all(row["error_code"] is None for row in restarted.opportunities(rows[0]["batch_id"]))
    await collect_batch(restarted, window=window, clock=lambda: now[0],
                        snapshot_loader=temporarily_unavailable, forecast=successful, tickers=("AAPL",))
    assert len(loads) == 3 and len(calls) == 2


@pytest.mark.asyncio
async def test_market_outage_stays_queued_until_deadline_without_llm_budget(store, window):
    loads = []

    def unavailable(ticker, cutoff):
        loads.append((ticker, cutoff))
        raise ConnectionError("fixture market outage")

    async def no_forecast(*_args):
        pytest.fail("a missing snapshot must not invoke a model")

    for minute in (1, 6, 11):
        now = timestamp(window.collection_at) + timedelta(minutes=minute)
        result = await collect_batch(store, window=window, clock=lambda: now,
                                     snapshot_loader=unavailable, forecast=no_forecast)
        assert result["counts"] == {"queued": 40} and result["attempts"] == 0
    assert len(loads) == 60  # One acquisition per ticker, shared by both agents each poll.
    assert {cutoff for _, cutoff in loads} == {window.knowledge_cutoff}
    result = await collect_batch(store, window=window, clock=lambda: timestamp(window.deadline_at),
                                 snapshot_loader=unavailable, forecast=no_forecast)
    assert result["counts"] == {"missed": 40} and result["attempts"] == 0
    assert len(loads) == 60
    with store.connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM prediction_attempts").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM prediction_snapshots").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM prediction_records").fetchone()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("budget", [40, 45, 60])
async def test_market_recovery_preserves_first_attempt_slots_without_blocking_retries(store, window, budget):
    now = [timestamp(window.collection_at) + timedelta(minutes=1)]
    unavailable = [True]
    loads, calls, seen = [], [], set()

    def loader(ticker, cutoff):
        loads.append((ticker, cutoff))
        if ticker == "AAPL" and unavailable[0]:
            raise ConnectionError("fixture market outage")
        return snapshot(ticker, cutoff)

    async def transient(agent, context, frozen):
        identity = (context["ticker"], agent)
        calls.append(identity)
        if context["ticker"] != "AAPL" and identity not in seen:
            seen.add(identity)
            return {"status": "failed", "retryable": True, "error_code": "timeout"}
        return predicted(agent, context, issued=iso(now[0]))

    retried = min(20, budget - 40)
    first = await collect_batch(store, window=window, clock=lambda: now[0], snapshot_loader=loader, forecast=transient, limit=budget)
    assert first["attempts"] == len(calls) == 38 + retried
    assert first["counts"]["queued"] == 2 and first["counts"]["failed"] == 38 - retried
    assert first["accepted"] == retried and len(set(calls[:38])) == 38
    assert all(ticker != "AAPL" for ticker, _ in calls)
    assert len(loads) == 20

    # A still-missing ticker cannot consume model attempts, and repeated polls cannot
    # let other opportunities use its two reserved first-attempt slots.
    now[0] += timedelta(minutes=5)
    waiting = await collect_batch(PredictionStore(store.path), window=window, clock=lambda: now[0],
                                  snapshot_loader=loader, forecast=transient, limit=budget)
    assert waiting["attempts"] == 38 + retried and len(calls) == 38 + retried
    assert len(loads) == 21

    unavailable[0] = False
    now[0] += timedelta(minutes=5)
    second = await collect_batch(store, window=window, clock=lambda: now[0], snapshot_loader=loader, forecast=transient, limit=budget)
    assert len(set(calls)) == 40 and second["attempts"] == len(calls) == budget
    assert set(calls[-2:]) == {("AAPL", "technical"), ("AAPL", "risk")}
    assert second["accepted"] == retried + 2 and len(loads) == 22
    rows = store.opportunities("us20-v1:" + window.batch_date)
    assert sum(row["attempts"] == 2 for row in rows) == retried
    assert all(row["attempts"] == 1 for row in rows if row["ticker"] == "AAPL")
    assert max(row["attempts"] for row in rows) <= 2
    assert {cutoff for _, cutoff in loads} == {window.knowledge_cutoff}
    await collect_batch(PredictionStore(store.path), window=window, clock=lambda: now[0],
                        snapshot_loader=loader, forecast=transient, limit=budget)
    assert len(calls) == budget and len(loads) == 22


def test_ready_first_attempt_precedes_retries_but_missing_snapshot_does_not(store, window):
    now = timestamp(window.collection_at)
    batch = store.ensure_batch(window, tickers=("AAPL", "MSFT"), now=now)
    store.freeze_snapshot(batch, "AAPL", snapshot("AAPL", window.knowledge_cutoff))
    rows = [row for row in store.opportunities(batch) if row["ticker"] == "AAPL"]
    first = store.reserve_attempt(rows[0]["id"], now=now, daily_limit=6)
    store.finish_attempt(rows[0]["id"], first, {"status": "failed", "retryable": True, "error_code": "timeout"}, now=now)
    assert store.reserve_attempt(rows[0]["id"], now=now, daily_limit=6) is None

    second = store.reserve_attempt(rows[1]["id"], now=now, daily_limit=6)
    store.finish_attempt(rows[1]["id"], second,
                         predicted(rows[1]["agent"], json.loads(rows[1]["context_json"]), issued=window.collection_at), now=now)
    assert store.reserve_attempt(rows[0]["id"], now=now, daily_limit=6) == 2


@pytest.mark.asyncio
async def test_offline_trading_days_become_missed_from_existing_first_batch(store, window):
    frozen_window = replace(window, calendar_version="fixture-original-calendar")
    batch = store.ensure_batch(frozen_window, now=timestamp(window.collection_at))
    row = store.opportunities(batch)[0]
    number = store.reserve_attempt(row["id"], now=timestamp(window.collection_at))
    store.finish_attempt(row["id"], number, predicted(row["agent"], json.loads(row["context_json"]), issued=window.collection_at),
                         now=timestamp(window.collection_at))
    frozen_snapshot = store.freeze_snapshot(batch, "AAPL", snapshot("AAPL", window.knowledge_cutoff))
    with store.connection() as conn:
        original_window = tuple(conn.execute("SELECT universe_version,window_json FROM prediction_batches WHERE id=?", (batch,)).fetchone())

    def no_market(*_args):
        pytest.fail("missed placeholders must never fetch prices")

    async def no_forecast(*_args):
        pytest.fail("missed placeholders must never issue forecasts")

    restarted = PredictionStore(store.path)
    resumed = window_for_date(date(2026, 10, 7))
    now = timestamp(resumed.collection_at) - timedelta(minutes=1)
    for _ in range(2):
        result = await collect_batch(restarted, clock=lambda: now, snapshot_loader=no_market, forecast=no_forecast)
        assert result["status"] == "not_due"
        assert restarted.registered_batch_dates() == {"2026-10-02", "2026-10-05", "2026-10-06"}
        assert restarted.coverage("2026-10-05")["counts"] == {"missed": 40}
        assert restarted.coverage("2026-10-06")["counts"] == {"missed": 40}
        report = restarted.public_report()
        assert report["summary"]["opportunities"] == 120 and report["summary"]["predictions"] == 1
        assert report["summary"]["missed"] == 119 and report["summary"]["pending"] == 1
    assert restarted.snapshot(batch, "AAPL") == frozen_snapshot
    with restarted.connection() as conn:
        assert tuple(conn.execute("SELECT universe_version,window_json FROM prediction_batches WHERE id=?", (batch,)).fetchone()) == original_window
        assert conn.execute("SELECT COUNT(*) FROM prediction_attempts").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM prediction_snapshots").fetchone()[0] == 1


@pytest.mark.asyncio
async def test_first_activation_after_deadline_only_marks_that_day_missed(store, window):
    now = timestamp(window.deadline_at) + timedelta(minutes=1)

    def no_market(*_args):
        pytest.fail("late first activation must not fetch or predict")

    result = await collect_batch(store, clock=lambda: now, snapshot_loader=no_market, forecast=no_market)
    assert result["counts"] == {"missed": 40} and result["attempts"] == 0
    assert store.registered_batch_dates() == {window.batch_date}
    with store.connection() as conn:
        state = conn.execute("SELECT start_date,first_enabled_at FROM prediction_collection_state").fetchone()
        assert tuple(state) == (window.batch_date, iso(now))
        assert conn.execute("SELECT COUNT(*) FROM prediction_records").fetchone()[0] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("first_enabled,resumed,missing_days", [
    ("2026-10-05T12:00:00Z", "2026-10-07T12:00:00Z", {"2026-10-05", "2026-10-06"}),
    ("2026-10-03T12:00:00Z", "2026-10-06T12:00:00Z", {"2026-10-05"}),
    ("2026-12-31T13:00:00Z", "2027-01-04T13:00:00Z", {"2026-12-31"}),
])
async def test_first_activation_before_collection_is_persistent_and_skips_holidays(store, first_enabled, resumed, missing_days):
    def no_market(*_args):
        pytest.fail("reconciliation must not fetch or predict")

    first = await collect_batch(store, clock=lambda: timestamp(first_enabled), snapshot_loader=no_market, forecast=no_market)
    assert first["status"] == "not_due" and store.registered_batch_dates() == set()
    restarted = PredictionStore(store.path)
    result = await collect_batch(restarted, clock=lambda: timestamp(resumed), snapshot_loader=no_market, forecast=no_market)
    assert result["status"] == "not_due" and restarted.registered_batch_dates() == missing_days
    for day in missing_days:
        coverage = restarted.coverage(day)
        assert coverage["counts"] == {"missed": 40} and coverage["attempts"] == 0
    with restarted.connection() as conn:
        assert conn.execute("SELECT first_enabled_at FROM prediction_collection_state").fetchone()[0] == first_enabled
        assert conn.execute("SELECT COUNT(*) FROM prediction_snapshots").fetchone()[0] == 0


def test_disabled_prediction_cycle_does_not_register_collection_start(monkeypatch):
    import backend.services.prediction_runner as module
    monkeypatch.delenv("PREDICTION_ENABLED", raising=False)
    monkeypatch.setattr(module, "get_prediction_store", lambda: pytest.fail("disabled cycle must not register a range"))
    module.run_prediction_cycle()

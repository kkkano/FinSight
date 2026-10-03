"""One bounded collector for the pre-registered US20 benchmark."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from datetime import datetime

from backend.services.prediction_calendar import NY, calendar, current_window, iso, timestamp, utc_now, window_for_date
from backend.services.prediction_market import build_snapshot
from backend.services.prediction_store import TICKERS, get_prediction_store

logger = logging.getLogger(__name__)
_cycle_lock = threading.Lock()


def enabled() -> bool:
    return os.getenv("PREDICTION_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def daily_limit() -> int:
    return min(60, max(0, int(os.getenv("PREDICTION_DAILY_ATTEMPTS", "60"))))


def create_forecast_llm():
    from backend.llm_config import create_llm
    from backend.services.model_selection import server_model_scope
    with server_model_scope():
        return create_llm(temperature=None, max_tokens=max(2048, int(os.getenv("PREDICTION_OUTPUT_TOKENS", "4096"))),
                          request_timeout=60, max_retries=0, preserve_output_budget=True)


async def forecast_once(agent_name: str, context: dict, snapshot: dict) -> dict:
    from backend.agents.technical_agent import TechnicalAgent
    from backend.agents.risk_agent import RiskAgent
    from backend.research.prediction_contract import ForecastContext
    llm = create_forecast_llm()
    cls = TechnicalAgent if agent_name == "technical" else RiskAgent
    result = await cls(llm, None, None).forecast(ForecastContext(**context), snapshot)
    return result.model_dump(mode="json")


def register_missing_batches(store, now: datetime) -> None:
    """Create expired opportunity placeholders only within the frozen activation range."""
    start = store.register_collection_start(now)
    today = now.astimezone(NY).date()
    if start > today:
        return
    existing = store.registered_batch_dates()
    sessions = calendar().schedule(start_date=start, end_date=today)
    for index in sessions.index:
        day = index.date()
        if day.isoformat() in existing:
            continue  # Existing universe identity and frozen window are immutable.
        missing_window = window_for_date(day)
        if missing_window is not None and now >= timestamp(missing_window.deadline_at):
            batch_id = store.ensure_batch(missing_window, now=now)
            store.expire_queued(batch_id, now)


async def collect_batch(store, *, window=None, clock=utc_now, snapshot_loader=build_snapshot,
                        forecast=forecast_once, tickers=TICKERS, limit=None) -> dict:
    now = clock()
    register_missing_batches(store, now)
    store.expire_uncollected(now)
    window = window or current_window(now)
    if window is None or now < timestamp(window.collection_at):
        return {"status": "not_due"}
    batch_id = store.ensure_batch(window, tickers=tickers, now=now)
    if now >= timestamp(window.deadline_at):
        store.expire_queued(batch_id, now)
        return store.coverage(window.batch_date)

    budget = daily_limit() if limit is None else min(60, max(0, limit))
    semaphore = asyncio.Semaphore(2)
    snapshot_tasks = {}

    async def get_snapshot(ticker):
        frozen = store.snapshot(batch_id, ticker)
        if frozen is not None:
            return frozen
        snapshot = await asyncio.to_thread(snapshot_loader, ticker, window.knowledge_cutoff)
        return store.freeze_snapshot(batch_id, ticker, snapshot)

    async def run_opportunity(row):
        async with semaphore:
            if (timestamp(window.deadline_at) - clock()).total_seconds() < 65:
                return
            ticker = row["ticker"]
            if ticker not in snapshot_tasks:
                snapshot_tasks[ticker] = asyncio.create_task(get_snapshot(ticker))
            try:
                snapshot = await snapshot_tasks[ticker]
            except Exception:
                store.fail_data(row["id"], now=clock())
                return
            attempt = store.reserve_attempt(row["id"], now=clock(), daily_limit=budget)
            if attempt is None:
                return
            context = json.loads(row["context_json"])
            try:
                result = await asyncio.wait_for(forecast(row["agent"], context, snapshot), timeout=60)
            except (asyncio.TimeoutError, TimeoutError):
                result = {"status": "failed", "retryable": True, "error_code": "timeout", "metadata": {}}
            except Exception:
                # Configuration/contract bugs are visible and never converted to a forecast.
                result = {"status": "failed", "retryable": False, "error_code": "forecast_configuration", "metadata": {}}
            store.finish_attempt(row["id"], attempt, result, now=clock())

    first = [row for row in store.opportunities(batch_id) if row["status"] == "queued" and row["attempts"] == 0]
    await asyncio.gather(*(run_opportunity(row) for row in first))
    retries = [row for row in store.opportunities(batch_id)
               if row["status"] in ("failed", "interrupted") and row["retryable"] and row["attempts"] < 2]
    await asyncio.gather(*(run_opportunity(row) for row in retries))
    store.expire_queued(batch_id, clock())
    return store.coverage(window.batch_date)


def prediction_health(*, store=None, now: datetime | None = None, is_enabled=None) -> dict:
    active = enabled() if is_enabled is None else is_enabled
    base = {"enabled": active, "status": "disabled", "batch_date": None, "latest_batch_date": None,
            "expected": 40, "accepted": 0, "attempts": 0, "counts": {}, "last_update": None,
            "deadline_at": None, "alert_at": None, "alert_required": False}
    if not active:
        return base
    now = now or utc_now()
    store = store or get_prediction_store()
    latest = store.coverage()
    base["latest_batch_date"] = latest["batch_date"]
    window = current_window(now)
    if window is None:
        return {**base, "status": "not_due"}
    coverage = store.coverage(window.batch_date)
    base.update({k: coverage[k] for k in ("batch_date", "expected", "accepted", "attempts", "counts", "last_update")})
    base.update(deadline_at=window.deadline_at, alert_at=window.alert_at)
    if now < timestamp(window.collection_at):
        base["status"] = "not_due"
    elif now < timestamp(window.alert_at):
        base["status"] = "collecting"
    elif not coverage["exists"]:
        base.update(status="missing", alert_required=True)
    elif coverage["accepted"] < 30:
        base.update(status="low_coverage", alert_required=True)
    else:
        base["status"] = "ok" if coverage["accepted"] == 40 else "partial"
    return base


def run_prediction_cycle() -> None:
    if not enabled() or not _cycle_lock.acquire(blocking=False):
        return
    try:
        from backend.services.prediction_settlement import settle_due
        store = get_prediction_store()
        result = asyncio.run(collect_batch(store))
        settled = settle_due(store)
        logger.info("[Predictions] collection=%s settlement=%s", result, settled)
    except Exception as exc:
        logger.error("[Predictions] cycle failed: %s", type(exc).__name__)
    finally:
        _cycle_lock.release()

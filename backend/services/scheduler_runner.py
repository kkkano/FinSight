"""
APScheduler runner for price_change sweep.

Design:
- Keep it framework-agnostic; main.py can call start_price_change_scheduler on startup.
- Accept injected run_fn for testability.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)





def start_price_change_scheduler(
    run_fn: Callable[[], None],
    *,
    interval_minutes: float = 15.0,
    enabled: bool = True,
) -> Optional[BackgroundScheduler]:
    """
    Start background scheduler for price_change cycle.

    Args:
        run_fn: callable without args that performs one sweep.
        interval_minutes: interval minutes between runs.
        enabled: toggle; if False, returns None.
    """
    if not enabled:
        logger.info("[Scheduler] price_change scheduler disabled (env).")
        return None

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_fn,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id="price_change_cycle",
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),  # fire once immediately
    )
    scheduler.start()
    logger.info(f"[Scheduler] price_change scheduler started: every {interval_minutes} min.")
    return scheduler
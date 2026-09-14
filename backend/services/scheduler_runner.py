"""Prediction Outcome 与页面 lease Monitor 共用的轻量定时器。"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger(__name__)

def start_interval_scheduler(
    run_fn: Callable[[], None],
    *,
    interval_minutes: float = 15.0,
    enabled: bool = True,
    job_id: str = "scheduled_cycle",
    job_label: str = "scheduled job",
) -> Optional[BackgroundScheduler]:
    """
    Start background scheduler for a generic interval job.

    Args:
        run_fn: callable without args that performs one sweep.
        interval_minutes: interval minutes between runs.
        enabled: toggle; if False, returns None.
    """
    if not enabled:
        logger.info(f"[Scheduler] {job_label} disabled (env).")
        return None

    scheduler = BackgroundScheduler()
    scheduler.add_job(
        run_fn,
        trigger=IntervalTrigger(minutes=interval_minutes),
        id=job_id,
        max_instances=1,
        coalesce=True,
        next_run_time=datetime.now(timezone.utc),  # fire once immediately
    )
    scheduler.start()
    logger.info(f"[Scheduler] {job_label} started: every {interval_minutes} min.")
    return scheduler

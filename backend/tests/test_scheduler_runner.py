# -*- coding: utf-8 -*-
"""
Smoke tests for APScheduler runner.
"""

import time
from datetime import datetime, timezone
from typing import List

from backend.services.scheduler_runner import start_price_change_scheduler


def test_scheduler_disabled_returns_none():
    scheduler = start_price_change_scheduler(lambda: None, interval_minutes=0.01, enabled=False)
    assert scheduler is None


def test_scheduler_runs_job_at_least_once():
    calls: List[datetime] = []

    def _job():
        calls.append(datetime.now(timezone.utc))

    scheduler = start_price_change_scheduler(_job, interval_minutes=0.01, enabled=True)
    assert scheduler is not None

    time.sleep(1.0)  # allow first run
    scheduler.shutdown(wait=False)

    assert len(calls) >= 1

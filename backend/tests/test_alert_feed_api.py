# -*- coding: utf-8 -*-
"""Tests for /api/alerts/feed endpoint."""

import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi.testclient import TestClient

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.api.main import app  # noqa: E402
from backend.services import subscription_service as subs  # noqa: E402


def _configure_test_storage(tmp_path: Any) -> None:
    subs.SUBSCRIPTIONS_FILE = tmp_path / "subscriptions_alert_feed_test.json"
    subs._subscription_service = None  # type: ignore[attr-defined]


def test_alert_feed_returns_events(tmp_path):
    _configure_test_storage(tmp_path)
    with TestClient(app) as client:
        service = subs.get_subscription_service()

        assert service.subscribe(email="user@example.com", ticker="AAPL")
        service.record_alert_event(
            "user@example.com",
            "AAPL",
            "price_change",
            severity="high",
            title="AAPL price move",
            message="AAPL price moved +4.2%",
        )

        response = client.get("/api/alerts/feed", params={"email": "user@example.com", "limit": 10})
        assert response.status_code == 200
        payload = response.json()
        assert payload["success"] is True
        assert payload["count"] == 1
        assert payload["events"][0]["ticker"] == "AAPL"
        assert payload["events"][0]["event_type"] == "price_change"


def test_alert_feed_respects_since_filter(tmp_path):
    _configure_test_storage(tmp_path)
    with TestClient(app) as client:
        service = subs.get_subscription_service()

        assert service.subscribe(email="user@example.com", ticker="MSFT")
        old_ts = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        service.record_alert_event(
            "user@example.com",
            "MSFT",
            "news",
            severity="medium",
            title="MSFT old event",
            message="old",
            triggered_at=old_ts,
        )
        service.record_alert_event(
            "user@example.com",
            "MSFT",
            "news",
            severity="medium",
            title="MSFT new event",
            message="new",
        )

        since = (datetime.now(timezone.utc) - timedelta(hours=12)).isoformat()
        response = client.get("/api/alerts/feed", params={"email": "user@example.com", "since": since})
        assert response.status_code == 200
        payload = response.json()
        assert payload["count"] == 1
        assert payload["events"][0]["title"] == "MSFT new event"

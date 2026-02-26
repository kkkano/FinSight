# -*- coding: utf-8 -*-
"""
P1 Alert subscription API smoke tests.
"""

import os
import sys
from typing import Any

from fastapi.testclient import TestClient


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.api.main import app  # noqa: E402
from backend.services import subscription_service as subs  # noqa: E402


def _configure_test_storage(tmp_path: Any) -> None:
    subs.SUBSCRIPTIONS_FILE = tmp_path / "subscriptions_test.json"
    subs._subscription_service = None  # type: ignore[attr-defined]


def test_subscribe_and_list_lifecycle(tmp_path):
    _configure_test_storage(tmp_path)
    with TestClient(app) as client:
        email = "user@example.com"
        ticker = "AAPL"

        resp = client.post(
            "/api/subscribe",
            json={
                "email": email,
                "ticker": ticker,
                "alert_types": ["price_change", "news"],
                "price_threshold": 5.0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        assert data.get("email") == email
        assert data.get("ticker") == ticker

        resp = client.get(f"/api/subscriptions?email={email}")
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True
        subs_list = data.get("subscriptions") or []
        assert len(subs_list) == 1
        sub = subs_list[0]
        assert sub["email"] == email
        assert sub["ticker"] == ticker
        assert sub["alert_types"] == ["price_change", "news"]
        assert sub["price_threshold"] == 5.0

        resp = client.post(
            "/api/unsubscribe",
            json={
                "email": email,
                "ticker": ticker,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("success") is True

        resp = client.get(f"/api/subscriptions?email={email}")
        assert resp.status_code == 200
        data = resp.json()
        subs_list = data.get("subscriptions") or []
        assert len(subs_list) == 0


def test_subscribe_validation_and_unsubscribe_missing(tmp_path):
    _configure_test_storage(tmp_path)
    with TestClient(app) as client:
        resp = client.post(
            "/api/subscribe",
            json={
                "ticker": "AAPL",
            },
        )
        assert resp.status_code in (400, 422)

        resp = client.post(
            "/api/unsubscribe",
            json={
                "ticker": "AAPL",
            },
        )
        assert resp.status_code in (400, 422)

        resp = client.post(
            "/api/unsubscribe",
            json={
                "email": "nobody@example.com",
                "ticker": "AAPL",
            },
        )
        assert resp.status_code == 404

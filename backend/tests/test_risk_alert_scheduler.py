# -*- coding: utf-8 -*-
"""Tests for RiskAlertScheduler."""

from __future__ import annotations

from datetime import datetime
from typing import List

import pytest

from backend.services import subscription_service as subs
from backend.services.alert_scheduler import PriceSnapshot, RiskAlertScheduler
from backend.services.subscription_service import SubscriptionService


@pytest.fixture
def subscription_service_tmp(tmp_path) -> SubscriptionService:
    original_path = subs.SUBSCRIPTIONS_FILE
    subs.SUBSCRIPTIONS_FILE = tmp_path / "subscriptions_risk_scheduler.json"
    subs._subscription_service = None  # type: ignore[attr-defined]
    service = SubscriptionService()
    try:
        yield service
    finally:
        subs._subscription_service = None  # type: ignore[attr-defined]
        subs.SUBSCRIPTIONS_FILE = original_path


class FakeEmailService:
    def __init__(self) -> None:
        self.sent: List[dict] = []

    def send_stock_alert(
        self,
        to_email: str,
        ticker: str,
        alert_type: str,
        message: str,
        current_price=None,
        change_percent=None,
    ) -> tuple[bool, str, str | None]:
        self.sent.append(
            {
                "to_email": to_email,
                "ticker": ticker,
                "alert_type": alert_type,
                "message": message,
                "current_price": current_price,
                "change_percent": change_percent,
            }
        )
        return True, "none", None


def test_risk_scheduler_ignores_non_risk_subscription(subscription_service_tmp):
    service = subscription_service_tmp
    email = FakeEmailService()

    service.subscribe(
        email="user@example.com",
        ticker="AAPL",
        alert_types=["price_change"],
        price_threshold=3.0,
    )

    scheduler = RiskAlertScheduler(
        subscription_service=service,
        email_service=email,
        price_fetcher=lambda _ticker: PriceSnapshot(ticker="AAPL", price=100.0, change_percent=-9.0),
    )
    sent = scheduler.run_once()

    assert sent == []
    assert email.sent == []


def test_risk_scheduler_sends_when_risk_meets_threshold(subscription_service_tmp):
    service = subscription_service_tmp
    email = FakeEmailService()

    service.subscribe(
        email="user@example.com",
        ticker="AAPL",
        alert_types=["risk"],
        risk_threshold="high",
    )

    scheduler = RiskAlertScheduler(
        subscription_service=service,
        email_service=email,
        price_fetcher=lambda _ticker: PriceSnapshot(ticker="AAPL", price=100.0, change_percent=-8.5),
    )
    sent = scheduler.run_once()

    assert len(sent) == 1
    assert len(email.sent) == 1
    assert sent[0]["risk_level"] in {"high", "critical"}
    assert sent[0]["risk_threshold"] == "high"

    sub = service.get_subscriptions("user@example.com")[0]
    assert sub.get("last_risk_at") is not None


def test_risk_scheduler_skips_when_below_threshold(subscription_service_tmp):
    service = subscription_service_tmp
    email = FakeEmailService()

    service.subscribe(
        email="user@example.com",
        ticker="AAPL",
        alert_types=["risk"],
        risk_threshold="high",
    )

    scheduler = RiskAlertScheduler(
        subscription_service=service,
        email_service=email,
        price_fetcher=lambda _ticker: PriceSnapshot(ticker="AAPL", price=100.0, change_percent=-1.2),
    )
    sent = scheduler.run_once()

    assert sent == []
    assert email.sent == []


def test_risk_scheduler_respects_cooldown(subscription_service_tmp, monkeypatch: pytest.MonkeyPatch):
    service = subscription_service_tmp
    email = FakeEmailService()

    service.subscribe(
        email="user@example.com",
        ticker="AAPL",
        alert_types=["risk"],
        risk_threshold="medium",
    )
    service.update_last_risk("user@example.com", "AAPL")

    monkeypatch.setenv("RISK_ALERT_COOLDOWN_MINUTES", "180")
    scheduler = RiskAlertScheduler(
        subscription_service=service,
        email_service=email,
        price_fetcher=lambda _ticker: PriceSnapshot(ticker="AAPL", price=100.0, change_percent=-9.0),
    )
    sent = scheduler.run_once()

    assert sent == []
    assert email.sent == []

    sub = service.get_subscriptions("user@example.com")[0]
    assert datetime.fromisoformat(sub["last_risk_at"]) <= datetime.now()

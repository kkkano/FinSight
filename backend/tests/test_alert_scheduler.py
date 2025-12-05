# -*- coding: utf-8 -*-
"""
P1 alert skeleton: price_change scheduler dry-run tests.
"""

from typing import List

import pytest

from backend.services import subscription_service as subs
from backend.services.alert_scheduler import PriceChangeScheduler, PriceSnapshot
from backend.services.subscription_service import SubscriptionService


@pytest.fixture
def subscription_service_tmp(tmp_path) -> SubscriptionService:
    """
    Point subscriptions to a tmp file and reset singleton for isolation.
    Restore globals after each test to avoid side effects.
    """
    original_path = subs.SUBSCRIPTIONS_FILE
    subs.SUBSCRIPTIONS_FILE = tmp_path / "subscriptions_scheduler.json"
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
    ) -> bool:
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
        return True


def test_price_change_scheduler_triggers_when_threshold_met(subscription_service_tmp):
    service = subscription_service_tmp
    email = FakeEmailService()

    service.subscribe(
        email="user@example.com",
        ticker="AAPL",
        alert_types=["price_change"],
        price_threshold=5.0,
    )

    def fake_price_fetcher(_ticker: str):
        return PriceSnapshot(ticker=_ticker, price=105.0, change_percent=6.2)

    scheduler = PriceChangeScheduler(service, email, fake_price_fetcher)
    sent = scheduler.run_once()

    assert len(sent) == 1
    assert len(email.sent) == 1
    payload = sent[0]
    assert payload["email"] == "user@example.com"
    assert payload["ticker"] == "AAPL"
    assert payload["change_percent"] == 6.2

    # last_alert_at should be updated
    subs_list = service.get_subscriptions("user@example.com")
    assert subs_list[0].get("last_alert_at") is not None


def test_price_change_scheduler_skips_when_below_threshold(subscription_service_tmp):
    service = subscription_service_tmp
    email = FakeEmailService()

    service.subscribe(
        email="user@example.com",
        ticker="MSFT",
        alert_types=["price_change"],
        price_threshold=5.0,
    )

    def fake_price_fetcher(_ticker: str):
        return PriceSnapshot(ticker=_ticker, price=305.0, change_percent=2.0)

    scheduler = PriceChangeScheduler(service, email, fake_price_fetcher)
    sent = scheduler.run_once()

    assert sent == []
    assert email.sent == []

    subs_list = service.get_subscriptions("user@example.com")
    assert subs_list[0].get("last_alert_at") is None

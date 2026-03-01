# -*- coding: utf-8 -*-
import pytest

import importlib
from backend.services.alert_scheduler import PriceSnapshot

alert_action_module = importlib.import_module("backend.graph.nodes.alert_action")


class StubSubscriptionService:
    def __init__(self):
        self._subscriptions = []
        self.last_subscribe_kwargs = None

    def get_subscriptions(self, email=None):
        if email is None:
            return list(self._subscriptions)
        return [item for item in self._subscriptions if item.get("email") == email]

    def subscribe(self, **kwargs):
        self.last_subscribe_kwargs = dict(kwargs)
        self._subscriptions = [
            item
            for item in self._subscriptions
            if not (
                str(item.get("email") or "").strip().lower() == str(kwargs.get("email") or "").strip().lower()
                and str(item.get("ticker") or "").strip().upper() == str(kwargs.get("ticker") or "").strip().upper()
            )
        ]
        self._subscriptions.append(dict(kwargs))
        return True


@pytest.mark.asyncio
async def test_alert_action_requires_email(monkeypatch):
    svc = StubSubscriptionService()
    monkeypatch.setattr(alert_action_module, "get_subscription_service", lambda: svc)
    monkeypatch.setattr(alert_action_module, "fetch_price_snapshot", lambda _ticker: PriceSnapshot(ticker=_ticker, price=100.0, change_percent=0.0))

    result = await alert_action_module.alert_action(
        {
            "alert_params": {"ticker": "AAPL", "alert_mode": "price_change_pct", "price_threshold": 3.0},
            "subject": {"tickers": ["AAPL"]},
            "ui_context": {},
        }
    )
    assert result["alert_valid"] is False
    assert "邮箱" in ((result.get("artifacts") or {}).get("draft_markdown") or "")


@pytest.mark.asyncio
async def test_alert_action_merges_alert_types_and_subscribes(monkeypatch):
    svc = StubSubscriptionService()
    svc._subscriptions.append(
        {
            "email": "user@example.com",
            "ticker": "AAPL",
            "alert_types": ["news"],
            "risk_threshold": "high",
        }
    )
    monkeypatch.setattr(alert_action_module, "get_subscription_service", lambda: svc)
    monkeypatch.setattr(alert_action_module, "fetch_price_snapshot", lambda _ticker: PriceSnapshot(ticker=_ticker, price=100.0, change_percent=0.0))

    result = await alert_action_module.alert_action(
        {
            "user_email": "user@example.com",
            "alert_params": {"ticker": "AAPL", "alert_mode": "price_change_pct", "price_threshold": 4.0},
            "subject": {"tickers": ["AAPL"]},
        }
    )

    assert result["alert_valid"] is True
    payload = svc.last_subscribe_kwargs or {}
    assert payload.get("email") == "user@example.com"
    assert payload.get("ticker") == "AAPL"
    assert sorted(payload.get("alert_types") or []) == ["news", "price_change"]


@pytest.mark.asyncio
async def test_alert_action_infers_direction_for_target_mode(monkeypatch):
    svc = StubSubscriptionService()
    monkeypatch.setattr(alert_action_module, "get_subscription_service", lambda: svc)
    monkeypatch.setattr(alert_action_module, "fetch_price_snapshot", lambda _ticker: PriceSnapshot(ticker=_ticker, price=100.0, change_percent=0.0))

    result = await alert_action_module.alert_action(
        {
            "user_email": "user@example.com",
            "alert_params": {
                "ticker": "AAPL",
                "alert_mode": "price_target",
                "price_target": 120.0,
                "direction": None,
            },
            "subject": {"tickers": ["AAPL"]},
        }
    )

    assert result["alert_valid"] is True
    payload = svc.last_subscribe_kwargs or {}
    assert payload.get("direction") == "above"

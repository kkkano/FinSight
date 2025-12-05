#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Minimal alert scheduling skeleton for price_change rule.

This keeps the logic small and testable:
- Pull subscriptions from SubscriptionService.
- For entries that opt into price_change and have a price_threshold, fetch a price snapshot.
- When absolute change_percent meets/exceeds the threshold, trigger EmailService.send_stock_alert
  and record last_alert_at.

This module is intentionally framework-light so it can later be wired to
APScheduler/Celery/async cron as needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple
import time

from backend.services.subscription_service import SubscriptionService
from backend.services.email_service import EmailService


# A lightweight data shape for the price provider result.
@dataclass
class PriceSnapshot:
    ticker: str
    price: Optional[float]
    change_percent: Optional[float]


class PriceChangeScheduler:
    """
    Execute price_change alerts once.
    Provide dependencies so tests can inject fakes:
    - subscription_service: manages subscriptions storage.
    - email_service: sends email alerts.
    - price_fetcher: callable(ticker) -> PriceSnapshot|None.
    """

    def __init__(
        self,
        subscription_service: SubscriptionService,
        email_service: EmailService,
        price_fetcher: Callable[[str], Optional[PriceSnapshot]],
    ) -> None:
        self.subscription_service = subscription_service
        self.email_service = email_service
        self.price_fetcher = price_fetcher

    def run_once(self) -> List[Dict]:
        """
        Iterate subscriptions and send alerts when price_change rule is satisfied.
        Returns a list of alert payloads for observability/testing.
        """
        sent: List[Dict] = []
        subscriptions = self.subscription_service.get_subscriptions()

        for sub in subscriptions:
            alert_types = sub.get("alert_types") or []
            if "price_change" not in alert_types:
                continue

            threshold = sub.get("price_threshold")
            if threshold is None:
                continue

            snapshot = self.price_fetcher(sub["ticker"])
            if snapshot is None or snapshot.change_percent is None:
                continue

            if abs(snapshot.change_percent) < threshold:
                continue

            # Build message and send email.
            message = (
                f"{sub['ticker']} price moved {snapshot.change_percent:+.2f}% "
                f"(threshold {threshold:.2f}%)."
            )

            self.email_service.send_stock_alert(
                to_email=sub["email"],
                ticker=sub["ticker"],
                alert_type="price_change",
                message=message,
                current_price=snapshot.price,
                change_percent=snapshot.change_percent,
            )
            self.subscription_service.update_last_alert(sub["email"], sub["ticker"])

            sent.append(
                {
                    "email": sub["email"],
                    "ticker": sub["ticker"],
                    "change_percent": snapshot.change_percent,
                    "threshold": threshold,
                    "message": message,
                }
            )

        return sent


# --- Convenience helpers ---

def fetch_price_snapshot(ticker: str) -> Optional[PriceSnapshot]:
    """
    Lightweight price fetcher with multi-source free fallbacks (no API key required):
    优先免封锁的 stooq，再尝试 yfinance/Yahoo。
    """
    snap = _get_cached_snapshot(ticker)
    if snap:
        return snap

    fetchers = (
        _fetch_with_stooq,
        _fetch_with_yfinance,
        _fetch_with_yahoo_quote,
        _fetch_with_yahoo_chart,
    )

    for fetcher in fetchers:
        snapshot = fetcher(ticker)
        if snapshot:
            _set_cache_snapshot(ticker, snapshot)
            return snapshot
    return None


def _fetch_with_yfinance(ticker: str) -> Optional[PriceSnapshot]:
    try:
        import yfinance as yf  # type: ignore

        t = yf.Ticker(ticker)
        info = getattr(t, "fast_info", {}) or {}
        price = info.get("last_price") or info.get("last_close") or info.get("lastClose")
        prev_close = info.get("previous_close") or info.get("previousClose") or info.get("regularMarketPreviousClose")

        change_percent = None
        if price is not None and prev_close:
            change_percent = (price - prev_close) / prev_close * 100.0

        return PriceSnapshot(ticker=ticker, price=price, change_percent=change_percent)
    except Exception:
        return None


def _fetch_with_yahoo_quote(ticker: str) -> Optional[PriceSnapshot]:
    """
    Hit Yahoo quote endpoint (no key). Provides regularMarketPrice + regularMarketPreviousClose.
    """
    try:
        import requests  # type: ignore

        url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={ticker}"
        headers = {"User-Agent": "Mozilla/5.0 (FinSightBot)"}
        resp = requests.get(url, timeout=8, headers=headers)
        if resp.status_code != 200:
            return None
        data = resp.json().get("quoteResponse", {}).get("result", [])
        if not data:
            return None
        item = data[0]
        price = item.get("regularMarketPrice")
        prev_close = item.get("regularMarketPreviousClose")
        change_percent = None
        if price is not None and prev_close not in (None, 0):
            change_percent = (price - prev_close) / prev_close * 100.0
        return PriceSnapshot(ticker=ticker, price=price, change_percent=change_percent)
    except Exception:
        return None


def _fetch_with_stooq(ticker: str) -> Optional[PriceSnapshot]:
    """
    Free source: stooq.pl (no key). Uses open vs close to approximate change.
    """
    try:
        import requests  # type: ignore

        # stooq ticker needs .us suffix for US stocks
        symbol = f"{ticker.lower()}.us"
        url = f"https://stooq.pl/q/l/?s={symbol}&f=sd2t2ohlcv&h&e=json"
        resp = requests.get(url, timeout=8)
        if resp.status_code != 200:
            return None
        data = (resp.json() or {}).get("symbols") or []
        if not data:
            return None
        item = data[0]
        # 'close' and 'open' are strings
        close = item.get("close")
        open_ = item.get("open")
        if close in (None, "N/D") or open_ in (None, "N/D"):
            return None
        price = float(close)
        prev = float(open_) if open_ not in (None, "N/D") else None
        change_percent = None
        if prev and prev != 0:
            change_percent = (price - prev) / prev * 100.0
        return PriceSnapshot(ticker=ticker, price=price, change_percent=change_percent)
    except Exception:
        return None


def _fetch_with_yahoo_chart(ticker: str) -> Optional[PriceSnapshot]:
    """
    Use Yahoo chart endpoint (2d range, 1d interval) to derive last close and previous close.
    """
    try:
        import requests  # type: ignore

        url = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=2d&interval=1d"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return None
        chart = resp.json().get("chart", {})
        result = (chart.get("result") or [None])[0] or {}
        closes = (result.get("indicators", {}).get("quote") or [{}])[0].get("close") or []
        if len(closes) < 2:
            return None
        prev_close, price = closes[-2], closes[-1]
        if price is None or prev_close in (None, 0):
            return None
        change_percent = (price - prev_close) / prev_close * 100.0
        return PriceSnapshot(ticker=ticker, price=price, change_percent=change_percent)
    except Exception:
        return None


# --- Simple in-process cache to reduce rate hitting free sources ---
_PRICE_CACHE: Dict[str, Tuple[PriceSnapshot, float]] = {}
_CACHE_TTL = 300  # seconds


def _get_cached_snapshot(ticker: str) -> Optional[PriceSnapshot]:
    now = time.time()
    snap_ts = _PRICE_CACHE.get(ticker.upper())
    if not snap_ts:
        return None
    snap, ts = snap_ts
    if now - ts <= _CACHE_TTL:
        return snap
    _PRICE_CACHE.pop(ticker.upper(), None)
    return None


def _set_cache_snapshot(ticker: str, snapshot: PriceSnapshot) -> None:
    _PRICE_CACHE[ticker.upper()] = (snapshot, time.time())


def run_price_change_cycle() -> List[Dict]:
    """
    One-shot price_change sweep using default services and fetcher.
    This can be hooked to APScheduler/cron; kept synchronous for simplicity.
    """
    from backend.services.subscription_service import get_subscription_service
    from backend.services.email_service import get_email_service

    scheduler = PriceChangeScheduler(
        subscription_service=get_subscription_service(),
        email_service=get_email_service(),
        price_fetcher=fetch_price_snapshot,
    )
    return scheduler.run_once()

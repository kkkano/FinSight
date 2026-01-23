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

import logging
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple
import time
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import datetime, timedelta

from backend.services.subscription_service import SubscriptionService
from backend.services.email_service import EmailService

logger = logging.getLogger(__name__)





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
        checked = 0

        for sub in subscriptions:
            if sub.get("disabled"):
                continue
            alert_types = sub.get("alert_types") or []
            if "price_change" not in alert_types:
                continue
            checked += 1

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

            if not self.subscription_service.is_valid_email(sub.get("email", "")):
                self.subscription_service.record_alert_attempt(
                    sub["email"],
                    sub["ticker"],
                    success=False,
                    error="invalid_email",
                    disable=True,
                )
                continue

            success = self.email_service.send_stock_alert(
                to_email=sub["email"],
                ticker=sub["ticker"],
                alert_type="price_change",
                message=message,
                current_price=snapshot.price,
                change_percent=snapshot.change_percent,
            )
            # Only update last_alert_at if email was actually sent
            if not success:
                logger.warning("Email send failed for %s -> %s, skipping last_alert update", sub["ticker"], sub["email"])
                self.subscription_service.record_alert_attempt(
                    sub["email"],
                    sub["ticker"],
                    success=False,
                    error="send_failed",
                )
                continue
            self.subscription_service.record_alert_attempt(sub["email"], sub["ticker"], success=True)

            sent.append(
                {
                    "email": sub["email"],
                    "ticker": sub["ticker"],
                    "change_percent": snapshot.change_percent,
                    "threshold": threshold,
                    "message": message,
                }
            )

        logger.info(
            "price_change run completed: checked=%s, sent=%s",
            checked,
            len(sent),
        )
        return sent


class NewsAlertScheduler:
    """
    News alert: fetch recent articles and notify when related to subscribed ticker.
    """

    def __init__(
        self,
        subscription_service: SubscriptionService,
        email_service: EmailService,
        news_fetcher: Callable[[str], List[Dict]],
    ) -> None:
        self.subscription_service = subscription_service
        self.email_service = email_service
        self.news_fetcher = news_fetcher

    def run_once(self) -> List[Dict]:
        sent: List[Dict] = []
        subs = self.subscription_service.get_subscriptions()
        now = datetime.utcnow()
        lookback = now - timedelta(hours=24)
        checked = 0

        for sub in subs:
            if sub.get("disabled"):
                continue
            alert_types = sub.get("alert_types") or []
            if "news" not in alert_types:
                continue
            checked += 1

            last_news_at = sub.get("last_news_at")
            last_dt = datetime.fromisoformat(last_news_at) if last_news_at else None

            articles = self.news_fetcher(sub["ticker"])
            if not articles:
                continue

            # 相关性：优先 related_tickers 命中，其次标题包含 TICKER
            related: List[Dict] = []
            for art in articles:
                pub_dt = art.get("published_at")
                if isinstance(pub_dt, str):
                    try:
                        pub_dt = datetime.fromisoformat(pub_dt)
                    except Exception:
                        pub_dt = None
                if not pub_dt or pub_dt < lookback:
                    continue
                if last_dt and pub_dt <= last_dt:
                    continue

                rel = art.get("related_tickers") or []
                title = art.get("title", "")
                if sub["ticker"].upper() in rel or sub["ticker"].upper() in title.upper():
                    related.append({**art, "published_at": pub_dt})

            if not related:
                continue

            # 取最新几条组成邮件
            related = sorted(related, key=lambda x: x["published_at"], reverse=True)[:3]
            lines = []
            for art in related:
                ts = art["published_at"].strftime("%Y-%m-%d %H:%M")
                lines.append(f"[{ts}] {art.get('title','')} ({art.get('source','')}) {art.get('url','')}")
            message = "\n".join(lines)

            success = self.email_service.send_stock_alert(
                to_email=sub["email"],
                ticker=sub["ticker"],
                alert_type="news",
                message=message,
                current_price=None,
                change_percent=None,
            )
            # Only update last_news_at if email was actually sent
            if not success:
                logger.warning("News email send failed for %s -> %s, skipping last_news update", sub["ticker"], sub["email"])
                continue
            self.subscription_service.update_last_news(sub["email"], sub["ticker"])

            sent.append(
                {
                    "email": sub["email"],
                    "ticker": sub["ticker"],
                    "articles": lines,
                }
            )

        logger.info(
            "news run completed: checked=%s, sent=%s",
            checked,
            len(sent),
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


def fetch_news_articles(ticker: str) -> List[Dict]:
    """
    Fetch recent news for ticker. Uses yfinance news; filters to last 48h and attaches related tickers if provided.
    """
    articles: List[Dict] = []
    cutoff = datetime.utcnow() - timedelta(hours=48)
    ticker_up = ticker.upper()

    def _add_article(title: str, url: str, source: str, published_at: datetime, related: List[str] | None = None):
        if not published_at or published_at < cutoff:
            return
        articles.append(
            {
                "title": title,
                "url": url,
                "source": source,
                "published_at": published_at,
                "related_tickers": [r.upper() for r in (related or []) if isinstance(r, str)],
            }
        )

    try:
        import yfinance as yf  # type: ignore

        t = yf.Ticker(ticker)
        news = getattr(t, "news", []) or []
        for item in news:
            title = item.get("title", "")
            link = item.get("link") or item.get("url")
            pub_ts = item.get("providerPublishTime") or item.get("pubDate")
            pub_dt = None
            try:
                if pub_ts:
                    pub_dt = datetime.fromtimestamp(float(pub_ts))
            except Exception:
                pub_dt = None
            if not pub_dt or pub_dt < cutoff:
                continue
            related = item.get("relatedTickers") or item.get("tickers") or []
            _add_article(title, link, item.get("publisher") or item.get("source") or "", pub_dt, related)
    except Exception as e:
        logger.info(f"[NewsFetcher] yfinance news failed for {ticker}: {e}")

    # Finnhub fallback
    if not articles:
        key = os.getenv("FINNHUB_API_KEY")
        if key:
            try:
                import requests  # type: ignore

                to_date = datetime.utcnow().date()
                from_date = to_date - timedelta(days=2)
                url = "https://finnhub.io/api/v1/company-news"
                params = {
                    "symbol": ticker_up,
                    "from": from_date.isoformat(),
                    "to": to_date.isoformat(),
                    "token": key,
                }
                resp = requests.get(url, params=params, timeout=8)
                if resp.status_code == 200:
                    for item in resp.json() or []:
                        title = item.get("headline", "")
                        link = item.get("url", "")
                        source = item.get("source", "")
                        ts = item.get("datetime")
                        pub_dt = datetime.fromtimestamp(ts) if ts else None
                        related = item.get("related", "").split(",") if item.get("related") else [ticker_up]
                        _add_article(title, link, source, pub_dt, related)
            except Exception as e:
                logger.info(f"[NewsFetcher] finnhub news failed for {ticker}: {e}")

    # Alpha Vantage fallback
    if not articles:
        key = os.getenv("ALPHA_VANTAGE_API_KEY")
        if key:
            try:
                import requests  # type: ignore

                url = "https://www.alphavantage.co/query"
                params = {"function": "NEWS_SENTIMENT", "tickers": ticker_up, "limit": 10, "apikey": key}
                resp = requests.get(url, params=params, timeout=8)
                data = resp.json()
                feed = data.get("feed") or []
                for item in feed:
                    title = item.get("title", "")
                    link = item.get("url") or item.get("link", "")
                    source = item.get("source", "")
                    ts_str = item.get("time_published", "")
                    pub_dt = None
                    if ts_str:
                        try:
                            pub_dt = datetime.strptime(ts_str[:12], "%Y%m%d%H%M")
                        except Exception:
                            pub_dt = None
                    related = item.get("ticker_sentiment", [])
                    rel_codes = [r.get("ticker") for r in related if isinstance(r, dict) and r.get("ticker")]
                    _add_article(title, link, source, pub_dt, rel_codes or [ticker_up])
            except Exception as e:
                logger.info(f"[NewsFetcher] alpha vantage news failed for {ticker}: {e}")

    return articles


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
    res = scheduler.run_once()
    return res


def run_news_alert_cycle() -> List[Dict]:
    """
    One-shot news sweep using default services and fetcher.
    """
    from backend.services.subscription_service import get_subscription_service
    from backend.services.email_service import get_email_service

    scheduler = NewsAlertScheduler(
        subscription_service=get_subscription_service(),
        email_service=get_email_service(),
        news_fetcher=fetch_news_articles,
    )
    res = scheduler.run_once()
    return res
LOG_DIR = Path(os.getenv("ALERT_LOG_DIR", Path(__file__).resolve().parent.parent.parent / "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

def _get_logger() -> logging.Logger:
    logger = logging.getLogger("alerts")
    if logger.handlers:
        return logger
    logger.setLevel(logging.INFO)
    log_path = LOG_DIR / "alerts.log"
    handler = RotatingFileHandler(log_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    # also console friendly
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    return logger

logger = _get_logger()

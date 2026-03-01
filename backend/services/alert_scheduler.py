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
from datetime import datetime, timedelta, timezone

from backend.agents.risk_agent import RiskAgent, RiskLevel
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
    Execute price alerts once.
    Supports:
    - price_change_pct: abs(change_percent) threshold with cooldown.
    - price_target: one-shot absolute price target trigger.
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

    @staticmethod
    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    def _is_cooling_down(self, sub: dict) -> bool:
        cooldown_minutes = max(1, int(os.getenv("PRICE_ALERT_COOLDOWN_MINUTES", "60")))
        last_alert_at = self._parse_dt(sub.get("last_alert_at"))
        if last_alert_at is None:
            return False
        return (datetime.now(last_alert_at.tzinfo) - last_alert_at) < timedelta(minutes=cooldown_minutes)

    def run_once(self) -> List[Dict]:
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

            alert_mode = str(sub.get("alert_mode") or "price_change_pct").strip().lower()
            snapshot = self.price_fetcher(sub["ticker"])
            if snapshot is None:
                continue

            threshold_payload: Optional[float] = None
            price_target_payload: Optional[float] = None
            direction_payload: Optional[str] = None

            if alert_mode == "price_target":
                if bool(sub.get("price_target_fired")):
                    continue
                price_target = sub.get("price_target")
                if price_target is None or snapshot.price is None:
                    continue
                try:
                    price_target_payload = float(price_target)
                except Exception:
                    continue
                direction_payload = str(sub.get("direction") or "").strip().lower()
                if direction_payload == "below":
                    triggered = snapshot.price <= price_target_payload
                else:
                    direction_payload = "above"
                    triggered = snapshot.price >= price_target_payload
                if not triggered:
                    continue
                message = (
                    f"{sub['ticker']} reached target price {price_target_payload:.2f} "
                    f"({direction_payload}), current={snapshot.price:.2f}."
                )
            else:
                threshold = sub.get("price_threshold")
                if threshold is None:
                    continue
                try:
                    threshold_payload = float(threshold)
                except Exception:
                    continue
                if self._is_cooling_down(sub):
                    continue
                if snapshot.change_percent is None:
                    continue
                if abs(snapshot.change_percent) < threshold_payload:
                    continue
                message = (
                    f"{sub['ticker']} price moved {snapshot.change_percent:+.2f}% "
                    f"(threshold {threshold_payload:.2f}%)."
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

            result = self.email_service.send_stock_alert(
                to_email=sub["email"],
                ticker=sub["ticker"],
                alert_type="price_target" if alert_mode == "price_target" else "price_change",
                message=message,
                current_price=snapshot.price,
                change_percent=snapshot.change_percent,
            )
            if isinstance(result, tuple):
                success, error_type, error_msg = result
            else:
                success, error_type, error_msg = result, "unknown", None

            if not success:
                logger.warning("Email send failed for %s -> %s: %s (%s)", sub["ticker"], sub["email"], error_msg, error_type)
                self.subscription_service.record_alert_attempt(
                    sub["email"],
                    sub["ticker"],
                    success=False,
                    error=error_msg or "send_failed",
                    is_transient_error=(error_type == "transient"),
                )
                continue

            self.subscription_service.record_alert_attempt(sub["email"], sub["ticker"], success=True)
            if alert_mode == "price_target":
                self.subscription_service.set_price_target_fired(sub["email"], sub["ticker"])

            severity = "medium"
            if alert_mode != "price_target" and threshold_payload is not None and snapshot.change_percent is not None:
                severity = "high" if abs(snapshot.change_percent) >= threshold_payload * 2 else "medium"

            self.subscription_service.record_alert_event(
                sub["email"],
                sub["ticker"],
                "price_target" if alert_mode == "price_target" else "price_change",
                severity=severity,
                title=(
                    f"{sub['ticker']} 到价触发 {snapshot.price:.2f}"
                    if alert_mode == "price_target"
                    else f"{sub['ticker']} 价格异动 {snapshot.change_percent:+.2f}%"
                ),
                message=message,
                metadata={
                    "alert_mode": alert_mode,
                    "threshold": threshold_payload,
                    "price_target": price_target_payload,
                    "direction": direction_payload,
                    "change_percent": snapshot.change_percent,
                    "current_price": snapshot.price,
                },
            )

            sent.append(
                {
                    "email": sub["email"],
                    "ticker": sub["ticker"],
                    "alert_mode": alert_mode,
                    "change_percent": snapshot.change_percent,
                    "threshold": threshold_payload,
                    "price_target": price_target_payload,
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
        now = datetime.now(timezone.utc).replace(tzinfo=None)
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

            # 鐩稿叧鎬э細浼樺厛 related_tickers 鍛戒腑锛屽叾娆℃爣棰樺寘鍚?TICKER
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

            # Keep only the latest three related articles for one digest email.
            related = sorted(related, key=lambda x: x["published_at"], reverse=True)[:3]
            lines = []
            for art in related:
                ts = art["published_at"].strftime("%Y-%m-%d %H:%M")
                lines.append(f"[{ts}] {art.get('title','')} ({art.get('source','')}) {art.get('url','')}")
            message = "\n".join(lines)

            result = self.email_service.send_stock_alert(
                to_email=sub["email"],
                ticker=sub["ticker"],
                alert_type="news",
                message=message,
                current_price=None,
                change_percent=None,
            )
            
            if isinstance(result, tuple):
                success, error_type, error_msg = result
            else:
                success, error_type, error_msg = result, 'unknown', None

            # Only update last_news_at if email was actually sent
            if not success:
                logger.warning("News email send failed for %s -> %s: %s", sub["ticker"], sub["email"], error_msg)
                self.subscription_service.record_alert_attempt(
                    sub["email"],
                    sub["ticker"],
                    success=False,
                    error=error_msg or "send_failed",
                    is_transient_error=(error_type == 'transient')
                )
                continue
            self.subscription_service.update_last_news(sub["email"], sub["ticker"])
            self.subscription_service.record_alert_event(
                sub["email"],
                sub["ticker"],
                "news",
                severity="high" if len(related) >= 2 else "medium",
                title=f"{sub['ticker']} 鐩稿叧鏂伴椈瑙﹀彂 ({len(related)} 鏉?",
                message=message,
                metadata={
                    "article_count": len(related),
                    "latest_article": related[0].get("title") if related else "",
                },
            )

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


class RiskAlertScheduler:
    """Execute risk alerts once with dependency injection."""

    _RISK_LEVEL_ORDER: dict[RiskLevel, int] = {
        RiskLevel.LOW: 1,
        RiskLevel.MEDIUM: 2,
        RiskLevel.HIGH: 3,
        RiskLevel.CRITICAL: 4,
    }

    def __init__(
        self,
        subscription_service: SubscriptionService,
        email_service: EmailService,
        price_fetcher: Callable[[str], Optional[PriceSnapshot]],
    ) -> None:
        self.subscription_service = subscription_service
        self.email_service = email_service
        self.price_fetcher = price_fetcher

    @staticmethod
    def _parse_dt(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    @classmethod
    def _normalize_threshold(cls, value: Optional[str]) -> RiskLevel:
        raw = str(value or "high").strip().lower()
        try:
            return RiskLevel(raw)
        except Exception:
            return RiskLevel.HIGH

    @classmethod
    def _meets_threshold(cls, actual: RiskLevel, threshold: RiskLevel) -> bool:
        return cls._RISK_LEVEL_ORDER[actual] >= cls._RISK_LEVEL_ORDER[threshold]

    def _is_cooling_down(self, sub: dict) -> bool:
        cooldown_minutes = max(1, int(os.getenv("RISK_ALERT_COOLDOWN_MINUTES", "180")))
        last_risk_at = self._parse_dt(sub.get("last_risk_at"))
        if last_risk_at is None:
            return False
        return (datetime.now(last_risk_at.tzinfo) - last_risk_at) < timedelta(minutes=cooldown_minutes)

    def run_once(self) -> List[Dict]:
        sent: List[Dict] = []
        subscriptions = self.subscription_service.get_subscriptions()
        checked = 0

        for sub in subscriptions:
            if sub.get("disabled"):
                continue

            alert_types = sub.get("alert_types") or []
            if "risk" not in alert_types:
                continue
            checked += 1

            if self._is_cooling_down(sub):
                continue

            snapshot = self.price_fetcher(sub["ticker"])
            if snapshot is None:
                continue

            assessment = RiskAgent.evaluate_ticker_risk_lightweight(
                str(sub["ticker"]).strip().upper(),
                snapshot,
            )
            threshold = self._normalize_threshold(sub.get("risk_threshold"))

            if not self._meets_threshold(assessment.risk_level, threshold):
                continue

            message = (
                f"{assessment.ticker} risk score {assessment.risk_score:.1f}/100, "
                f"level {assessment.risk_level.value}. {assessment.summary}"
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

            result = self.email_service.send_stock_alert(
                to_email=sub["email"],
                ticker=sub["ticker"],
                alert_type="risk",
                message=message,
                current_price=snapshot.price,
                change_percent=snapshot.change_percent,
            )

            if isinstance(result, tuple):
                success, error_type, error_msg = result
            else:
                success, error_type, error_msg = result, "unknown", None

            if not success:
                logger.warning(
                    "Risk email send failed for %s -> %s: %s (%s)",
                    sub["ticker"],
                    sub["email"],
                    error_msg,
                    error_type,
                )
                self.subscription_service.record_alert_attempt(
                    sub["email"],
                    sub["ticker"],
                    success=False,
                    error=error_msg or "send_failed",
                    is_transient_error=(error_type == "transient"),
                )
                continue

            self.subscription_service.record_alert_attempt(sub["email"], sub["ticker"], success=True)
            self.subscription_service.update_last_risk(sub["email"], sub["ticker"])
            self.subscription_service.record_alert_event(
                sub["email"],
                sub["ticker"],
                "risk",
                severity=assessment.risk_level.value,
                title=f"{assessment.ticker} 椋庨櫓绛夌骇 {assessment.risk_level.value}",
                message=message,
                metadata={
                    "risk_score": assessment.risk_score,
                    "risk_level": assessment.risk_level.value,
                    "risk_threshold": threshold.value,
                    "change_percent": snapshot.change_percent,
                },
            )

            sent.append(
                {
                    "email": sub["email"],
                    "ticker": sub["ticker"],
                    "risk_score": assessment.risk_score,
                    "risk_level": assessment.risk_level.value,
                    "risk_threshold": threshold.value,
                    "message": message,
                }
            )

        logger.info("risk run completed: checked=%s, sent=%s", checked, len(sent))
        return sent


# --- Convenience helpers ---

def fetch_price_snapshot(ticker: str) -> Optional[PriceSnapshot]:
    """
    Lightweight price fetcher with multi-source free fallbacks (no API key required):
    浼樺厛鍏嶅皝閿佺殑 stooq锛屽啀灏濊瘯 yfinance/Yahoo銆?    """
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
    cutoff = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(hours=48)
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

                to_date = datetime.now(timezone.utc).date()
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


def run_risk_alert_cycle() -> List[Dict]:
    """One-shot risk sweep using default services and price fetcher."""
    from backend.services.subscription_service import get_subscription_service
    from backend.services.email_service import get_email_service

    scheduler = RiskAlertScheduler(
        subscription_service=get_subscription_service(),
        email_service=get_email_service(),
        price_fetcher=fetch_price_snapshot,
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
    logger.propagate = False
    log_path = LOG_DIR / "alerts.log"
    handler = RotatingFileHandler(log_path, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    if str(os.getenv("ALERT_LOG_STDOUT_ENABLED", "false")).strip().lower() in {"1", "true", "yes", "on"}:
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        logger.addHandler(stream_handler)
    return logger

logger = _get_logger()


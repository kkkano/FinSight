# -*- coding: utf-8 -*-
"""可信行情网关：固定 primary/secondary、统一校验、来源与降级合同。"""

from __future__ import annotations

import copy
import logging
import math
import os
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse


logger = logging.getLogger(__name__)

MARKET_DATA_UNAVAILABLE = "market_data_unavailable"
KlineProvider = Callable[[str, str, str], Mapping[str, Any] | None]
QuoteProvider = Callable[[str], Any]
NewsProvider = Callable[[str, int], Any]
FinancialProvider = Callable[[str], Any]


class MarketDataValidationError(ValueError):
    """供应商响应不满足真实 OHLCV 合同时抛出。"""


def _parse_bar_time(value: Any) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise MarketDataValidationError("K 线缺少 time")
    normalized = text.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise MarketDataValidationError("K 线 time 不是 ISO-8601") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _parse_event_time(value: Any) -> datetime:
    if isinstance(value, bool) or value is None:
        raise MarketDataValidationError("数据缺少有效 as_of")
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=UTC)
        except (OSError, OverflowError, ValueError) as exc:
            raise MarketDataValidationError("数据 as_of 不是有效时间") from exc
    return _parse_bar_time(value)


def _finite_number(value: Any, *, field: str, positive: bool) -> float:
    if isinstance(value, bool):
        raise MarketDataValidationError(f"K 线 {field} 不是有效数值")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MarketDataValidationError(f"K 线 {field} 不是有效数值") from exc
    if not math.isfinite(number):
        raise MarketDataValidationError(f"K 线 {field} 不是有限数值")
    if positive and number <= 0:
        raise MarketDataValidationError(f"K 线 {field} 必须为正数")
    if not positive and number < 0:
        raise MarketDataValidationError(f"K 线 {field} 不得为负数")
    return number


def _signed_finite_number(value: Any, *, field: str) -> float:
    if isinstance(value, bool):
        raise MarketDataValidationError(f"{field} 不是有效数值")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise MarketDataValidationError(f"{field} 不是有效数值") from exc
    if not math.isfinite(number):
        raise MarketDataValidationError(f"{field} 不是有限数值")
    return number


def validate_kline_bars(raw_bars: Any) -> list[dict[str, Any]]:
    """校验并规范化真实 K 线，拒绝乱序、重复和非法 OHLCV。"""
    if not isinstance(raw_bars, Sequence) or isinstance(raw_bars, (str, bytes)) or not raw_bars:
        raise MarketDataValidationError("K 线数据为空")

    normalized: list[dict[str, Any]] = []
    previous_time: datetime | None = None
    for raw in raw_bars:
        if not isinstance(raw, Mapping):
            raise MarketDataValidationError("K 线 bar 必须是对象")
        bar_time = _parse_bar_time(raw.get("time"))
        if previous_time is not None and bar_time <= previous_time:
            raise MarketDataValidationError("K 线时间必须严格递增且不得重复")
        previous_time = bar_time

        open_price = _finite_number(raw.get("open"), field="open", positive=True)
        high_price = _finite_number(raw.get("high"), field="high", positive=True)
        low_price = _finite_number(raw.get("low"), field="low", positive=True)
        close_price = _finite_number(raw.get("close"), field="close", positive=True)
        volume = _finite_number(raw.get("volume", 0), field="volume", positive=False)
        if high_price < max(open_price, low_price, close_price):
            raise MarketDataValidationError("K 线 high 小于 open/low/close")
        if low_price > min(open_price, high_price, close_price):
            raise MarketDataValidationError("K 线 low 大于 open/high/close")

        normalized.append(
            {
                "time": str(raw["time"]),
                "open": open_price,
                "high": high_price,
                "low": low_price,
                "close": close_price,
                "volume": volume,
            }
        )
    return normalized


def validate_quote_payload(raw: Any) -> tuple[dict[str, float | None], datetime]:
    """规范化最新价，拒绝非正价格和非有限涨跌数据。"""
    from backend.utils.quote import parse_quote_payload

    parsed = parse_quote_payload(raw)
    if not parsed:
        raise MarketDataValidationError("Quote 数据为空或格式非法")
    price = _finite_number(parsed.get("price"), field="price", positive=True)
    change = parsed.get("change")
    change_percent = parsed.get("change_percent")
    normalized = {
        "price": price,
        "change": None if change is None else _signed_finite_number(change, field="change"),
        "change_percent": (
            None
            if change_percent is None
            else _signed_finite_number(change_percent, field="change_percent")
        ),
    }
    payload = raw if isinstance(raw, Mapping) else {}
    as_of_value = payload.get("as_of") or payload.get("timestamp")
    as_of = _parse_event_time(as_of_value) if as_of_value else datetime.now(UTC)
    return normalized, as_of


def validate_news_items(raw: Any) -> tuple[list[dict[str, Any]], datetime]:
    """规范化新闻证据，只接受有来源、可访问 URL 和发布时间的真实条目。"""
    payload = raw if isinstance(raw, Mapping) else {}
    items = payload.get("data") if isinstance(payload.get("data"), list) else raw
    if not isinstance(items, Sequence) or isinstance(items, (str, bytes)):
        raise MarketDataValidationError("News 数据不是列表")

    normalized: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    newest: datetime | None = None
    for item in items:
        if not isinstance(item, Mapping):
            continue
        title = str(item.get("title") or item.get("headline") or "").strip()
        source = str(item.get("source") or item.get("publisher") or "").strip()
        url = str(item.get("url") or item.get("link") or "").strip()
        published_value = item.get("published_at") or item.get("datetime")
        try:
            published = _parse_event_time(published_value)
        except MarketDataValidationError:
            continue
        parsed_url = urlparse(url)
        if not title or not source or parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
            continue
        if url in seen_urls:
            continue
        seen_urls.add(url)
        newest = published if newest is None or published > newest else newest
        normalized.append(
            {
                "headline": title,
                "title": title,
                "url": url,
                "source": source,
                "snippet": str(item.get("snippet") or item.get("summary") or "").strip(),
                "published_at": published.isoformat().replace("+00:00", "Z"),
                "datetime": published.isoformat().replace("+00:00", "Z"),
                "ticker": item.get("ticker"),
                "confidence": item.get("confidence"),
                "tags": list(item.get("tags") or []),
            }
        )
    if not normalized or newest is None:
        raise MarketDataValidationError("News 没有可追溯的有效条目")
    return normalized, newest


def validate_financial_payload(raw: Any) -> tuple[dict[str, Any], datetime]:
    """校验财报表合同，至少要求损益、资产负债或现金流中的一张真实表。"""
    payload = raw.get("data") if isinstance(raw, Mapping) and isinstance(raw.get("data"), Mapping) else raw
    if not isinstance(payload, Mapping) or payload.get("error"):
        raise MarketDataValidationError("Financial 数据为空或供应商返回错误")
    if not any(payload.get(key) for key in ("financials", "balance_sheet", "cashflow")):
        raise MarketDataValidationError("Financial 没有有效报表")
    normalized = dict(payload)
    as_of_value = normalized.get("as_of") or normalized.get("timestamp")
    as_of = _parse_event_time(as_of_value) if as_of_value else datetime.now(UTC)
    return normalized, as_of


def _as_of_from_payload(payload: Mapping[str, Any], bars: Sequence[Mapping[str, Any]]) -> datetime:
    configured = payload.get("as_of")
    if configured:
        try:
            return _parse_bar_time(configured)
        except MarketDataValidationError:
            pass
    return _parse_bar_time(bars[-1]["time"])


def _normalize_symbol_for_yahoo(symbol: str) -> str:
    from backend.tools.price import _is_china_ticker, _to_yahoo_cn_symbol

    return _to_yahoo_cn_symbol(symbol) if _is_china_ticker(symbol) else symbol


def _fetch_yfinance(symbol: str, period: str, interval: str) -> Mapping[str, Any] | None:
    from backend.tools.yfinance_client import create_ticker

    normalized_symbol = _normalize_symbol_for_yahoo(symbol)
    frame = create_ticker(normalized_symbol, session=None).history(
        period=period,
        interval=interval,
        timeout=20,
        raise_errors=True,
    )
    if frame is None or frame.empty:
        return None
    include_time = interval.endswith("h") or interval.endswith("m")
    rows: list[dict[str, Any]] = []
    for index, row in frame.iterrows():
        if include_time and hasattr(index, "to_pydatetime"):
            time_value = index.to_pydatetime().isoformat()
        elif hasattr(index, "strftime"):
            time_value = f"{index.strftime('%Y-%m-%d')} 00:00"
        else:
            time_value = str(index)
        rows.append(
            {
                "time": time_value,
                "open": row["Open"],
                "high": row["High"],
                "low": row["Low"],
                "close": row["Close"],
                "volume": row.get("Volume", 0),
            }
        )
    return {
        "kline_data": rows,
        "period": period,
        "interval": interval,
        "source": "yfinance",
    }


def _daily_legacy_provider(function_name: str) -> KlineProvider:
    def fetch(symbol: str, period: str, interval: str) -> Mapping[str, Any] | None:
        if interval != "1d":
            return None
        from backend.tools import price

        function = getattr(price, function_name)
        return function(symbol, period)

    return fetch


def _fetch_stooq(symbol: str, period: str, interval: str) -> Mapping[str, Any] | None:
    from backend.tools.price import _fetch_with_stooq_history

    return _fetch_with_stooq_history(symbol, period, interval)


def _quote_from_kline_provider(provider: KlineProvider) -> QuoteProvider:
    def fetch(symbol: str) -> Mapping[str, Any] | None:
        raw = provider(symbol, "5d", "1d")
        if not isinstance(raw, Mapping):
            return None
        bars = validate_kline_bars(raw.get("kline_data"))
        latest = bars[-1]
        previous_close = bars[-2]["close"] if len(bars) > 1 else None
        change = latest["close"] - previous_close if previous_close else None
        change_percent = (change / previous_close) * 100 if change is not None and previous_close else None
        return {
            "data": {
                "price": latest["close"],
                "change": change,
                "change_percent": change_percent,
            },
            "as_of": latest["time"],
        }

    return fetch


def _fetch_finnhub_news(symbol: str, limit: int) -> Any:
    from backend.tools.news import _get_finnhub_company_news

    return _get_finnhub_company_news(symbol, limit)


def _fetch_yfinance_news(symbol: str, limit: int) -> Any:
    from backend.tools.news import _get_yfinance_company_news

    return _get_yfinance_company_news(symbol, limit)


def _fetch_yfinance_financials(symbol: str) -> Any:
    from backend.tools.financial import _fetch_financials_from_yfinance

    return _fetch_financials_from_yfinance(symbol)


def _fetch_sec_financials(symbol: str) -> Any:
    from backend.tools.financial import _fetch_financials_from_sec_companyfacts

    return _fetch_financials_from_sec_companyfacts(symbol)


DEFAULT_KLINE_PROVIDERS: dict[str, KlineProvider] = {
    "yfinance": _fetch_yfinance,
    "stooq": _fetch_stooq,
    "twelve_data": _daily_legacy_provider("_fetch_with_twelve_data"),
    "akshare": _daily_legacy_provider("_fetch_with_akshare_hist"),
    "massive": _daily_legacy_provider("_fetch_with_massive_io"),
    "tiingo": _daily_legacy_provider("_fetch_with_tiingo"),
}

DEFAULT_QUOTE_PROVIDERS: dict[str, QuoteProvider] = {
    name: _quote_from_kline_provider(provider)
    for name, provider in DEFAULT_KLINE_PROVIDERS.items()
}

DEFAULT_NEWS_PROVIDERS: dict[str, NewsProvider] = {
    "finnhub": _fetch_finnhub_news,
    "yfinance": _fetch_yfinance_news,
}

DEFAULT_FINANCIAL_PROVIDERS: dict[str, FinancialProvider] = {
    "yfinance": _fetch_yfinance_financials,
    "sec_companyfacts": _fetch_sec_financials,
}


@dataclass
class _CacheEntry:
    expires_at: float
    payload: dict[str, Any]


@dataclass(frozen=True)
class _CapabilityConfig:
    providers: Mapping[str, Callable[..., Any]]
    primary_provider: str
    secondary_provider: str
    trusted_providers: frozenset[str]
    cache_ttl_seconds: int


class MarketDataGateway:
    """每次能力调用只允许一个 primary 和一个 secondary。"""

    def __init__(
        self,
        *,
        providers: Mapping[str, KlineProvider],
        primary_provider: str,
        secondary_provider: str | None = None,
        trusted_providers: set[str] | None = None,
        cache_ttl_seconds: int = 60,
        quote_providers: Mapping[str, QuoteProvider] | None = None,
        quote_primary_provider: str | None = None,
        quote_secondary_provider: str | None = None,
        quote_trusted_providers: set[str] | None = None,
        quote_cache_ttl_seconds: int = 30,
        news_providers: Mapping[str, NewsProvider] | None = None,
        news_primary_provider: str | None = None,
        news_secondary_provider: str | None = None,
        news_trusted_providers: set[str] | None = None,
        news_cache_ttl_seconds: int = 300,
        financial_providers: Mapping[str, FinancialProvider] | None = None,
        financial_primary_provider: str | None = None,
        financial_secondary_provider: str | None = None,
        financial_trusted_providers: set[str] | None = None,
        financial_cache_ttl_seconds: int = 3600,
    ) -> None:
        self._configs: dict[str, _CapabilityConfig] = {
            "kline": self._make_config(
                providers,
                primary_provider,
                secondary_provider,
                trusted_providers,
                cache_ttl_seconds,
            )
        }
        optional_configs = (
            (
                "quote",
                quote_providers,
                quote_primary_provider,
                quote_secondary_provider,
                quote_trusted_providers,
                quote_cache_ttl_seconds,
            ),
            (
                "news",
                news_providers,
                news_primary_provider,
                news_secondary_provider,
                news_trusted_providers,
                news_cache_ttl_seconds,
            ),
            (
                "financial",
                financial_providers,
                financial_primary_provider,
                financial_secondary_provider,
                financial_trusted_providers,
                financial_cache_ttl_seconds,
            ),
        )
        for capability, provider_map, primary, secondary, trusted, ttl in optional_configs:
            if provider_map is not None:
                self._configs[capability] = self._make_config(provider_map, primary, secondary, trusted, ttl)

        self._cache: dict[tuple[str, ...], _CacheEntry] = {}
        self._lock = threading.Lock()
        self._health: dict[str, dict[str, dict[str, int]]] = {}

    @staticmethod
    def _make_config(
        providers: Mapping[str, Callable[..., Any]],
        primary_provider: str | None,
        secondary_provider: str | None,
        trusted_providers: set[str] | None,
        cache_ttl_seconds: int,
    ) -> _CapabilityConfig:
        return _CapabilityConfig(
            providers=dict(providers),
            primary_provider=str(primary_provider or "").strip(),
            secondary_provider=str(secondary_provider or "").strip(),
            trusted_providers=frozenset(trusted_providers or set()),
            cache_ttl_seconds=max(0, int(cache_ttl_seconds)),
        )

    @staticmethod
    def _provider_order(config: _CapabilityConfig) -> list[str]:
        order: list[str] = []
        for name in (config.primary_provider, config.secondary_provider):
            if name and name not in order:
                order.append(name)
        return order[:2]

    def _record(self, capability: str, provider: str, outcome: str) -> None:
        with self._lock:
            capability_bucket = self._health.setdefault(capability, {})
            bucket = capability_bucket.setdefault(provider, {"success": 0, "failure": 0})
            bucket[outcome] += 1

    def health_snapshot(self) -> dict[str, dict[str, dict[str, int]]]:
        with self._lock:
            return copy.deepcopy(self._health)

    def _cached(self, key: tuple[str, ...], ttl_seconds: int) -> dict[str, Any] | None:
        if ttl_seconds <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            entry = self._cache.get(key)
            if entry is None or entry.expires_at <= now:
                self._cache.pop(key, None)
                return None
            result = copy.deepcopy(entry.payload)
        result["cached"] = True
        return result

    def _store_cache(self, key: tuple[str, ...], payload: dict[str, Any], ttl_seconds: int) -> None:
        if ttl_seconds <= 0:
            return
        with self._lock:
            self._cache[key] = _CacheEntry(
                expires_at=time.monotonic() + ttl_seconds,
                payload=copy.deepcopy(payload),
            )

    def _request(
        self,
        *,
        capability: str,
        symbol: str,
        cache_parts: tuple[str, ...],
        invoke: Callable[[Callable[..., Any]], Any],
        normalize: Callable[[Any], tuple[Any, datetime]],
        success_aliases: Callable[[Any], Mapping[str, Any]],
        error_aliases: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized_symbol = str(symbol or "").strip().upper()
        config = self._configs.get(capability)
        key = (capability, normalized_symbol, *cache_parts)
        if config is not None:
            cached = self._cached(key, config.cache_ttl_seconds)
            if cached is not None:
                return cached

        attempted: list[str] = []
        failures: list[str] = []
        if config is not None:
            for index, provider_name in enumerate(self._provider_order(config)):
                attempted.append(provider_name)
                provider = config.providers.get(provider_name)
                if provider is None:
                    failures.append("provider_not_configured")
                    self._record(capability, provider_name, "failure")
                    continue
                try:
                    data, as_of = normalize(invoke(provider))
                except MarketDataValidationError:
                    failures.append("invalid_provider_data")
                    self._record(capability, provider_name, "failure")
                    logger.warning(
                        "market data validation failed capability=%s provider=%s symbol=%s",
                        capability,
                        provider_name,
                        normalized_symbol,
                    )
                    continue
                except Exception as exc:
                    failures.append("provider_request_failed")
                    self._record(capability, provider_name, "failure")
                    logger.warning(
                        "market data provider failed capability=%s provider=%s symbol=%s error_type=%s",
                        capability,
                        provider_name,
                        normalized_symbol,
                        type(exc).__name__,
                    )
                    continue

                quality = "trusted" if provider_name in config.trusted_providers else "degraded"
                payload: dict[str, Any] = {
                    "data": data,
                    "capability": capability,
                    "provider": provider_name,
                    "source": provider_name,
                    "as_of": as_of.isoformat().replace("+00:00", "Z"),
                    "freshness_seconds": max(0, int((datetime.now(UTC) - as_of).total_seconds())),
                    "quality": quality,
                    "degraded": index > 0 or quality != "trusted",
                    "error_code": None,
                    "attempted_providers": list(attempted),
                    "cached": False,
                }
                payload.update(success_aliases(data))
                self._record(capability, provider_name, "success")
                self._store_cache(key, payload, config.cache_ttl_seconds)
                return payload

        return {
            "data": error_aliases.get("data"),
            "capability": capability,
            "provider": None,
            "source": None,
            "as_of": None,
            "freshness_seconds": None,
            "quality": "degraded",
            "degraded": True,
            "error_code": MARKET_DATA_UNAVAILABLE,
            "error": MARKET_DATA_UNAVAILABLE,
            "attempted_providers": attempted,
            "provider_failures": failures,
            "cached": False,
            **{key: value for key, value in error_aliases.items() if key != "data"},
        }

    def get_kline(self, symbol: str, *, period: str = "1y", interval: str = "1d") -> dict[str, Any]:
        def normalize(raw: Any) -> tuple[list[dict[str, Any]], datetime]:
            if not isinstance(raw, Mapping):
                raise MarketDataValidationError("供应商没有返回 K 线")
            returned_interval = str(raw.get("interval") or interval)
            if returned_interval != interval:
                raise MarketDataValidationError("供应商返回周期与请求不一致")
            bars = validate_kline_bars(raw.get("kline_data"))
            return bars, _as_of_from_payload(raw, bars)

        return self._request(
            capability="kline",
            symbol=symbol,
            cache_parts=(period, interval),
            invoke=lambda provider: provider(str(symbol or "").strip().upper(), period, interval),
            normalize=normalize,
            success_aliases=lambda bars: {"kline_data": bars, "period": period, "interval": interval},
            error_aliases={"data": [], "kline_data": [], "period": period, "interval": interval},
        )

    def get_quote(self, symbol: str) -> dict[str, Any]:
        return self._request(
            capability="quote",
            symbol=symbol,
            cache_parts=(),
            invoke=lambda provider: provider(str(symbol or "").strip().upper()),
            normalize=validate_quote_payload,
            success_aliases=lambda quote: {"quote": quote},
            error_aliases={"data": {}, "quote": None},
        )

    def get_news(self, symbol: str, *, limit: int = 5) -> dict[str, Any]:
        normalized_limit = max(1, min(int(limit), 20))
        return self._request(
            capability="news",
            symbol=symbol,
            cache_parts=(str(normalized_limit),),
            invoke=lambda provider: provider(str(symbol or "").strip().upper(), normalized_limit),
            normalize=validate_news_items,
            success_aliases=lambda items: {"news": items},
            error_aliases={"data": [], "news": []},
        )

    def get_financials(self, symbol: str) -> dict[str, Any]:
        return self._request(
            capability="financial",
            symbol=symbol,
            cache_parts=(),
            invoke=lambda provider: provider(str(symbol or "").strip().upper()),
            normalize=validate_financial_payload,
            success_aliases=lambda _financials: {},
            error_aliases={"data": {}},
        )


def _env_names(name: str, default: str) -> set[str]:
    raw = os.getenv(name, default)
    return {item.strip() for item in raw.split(",") if item.strip()}


def _capability_trusted_names(capability: str, default: str) -> set[str]:
    specific_name = f"MARKET_{capability.upper()}_TRUSTED_PROVIDERS"
    specific = str(os.getenv(specific_name, "")).strip()
    if specific:
        return {item.strip() for item in specific.split(",") if item.strip()}
    return _env_names("MARKET_DATA_TRUSTED_PROVIDERS", default)


def _build_default_gateway() -> MarketDataGateway:
    return MarketDataGateway(
        providers=DEFAULT_KLINE_PROVIDERS,
        primary_provider=os.getenv("MARKET_KLINE_PRIMARY_PROVIDER", "yfinance"),
        secondary_provider=os.getenv("MARKET_KLINE_SECONDARY_PROVIDER", "stooq"),
        trusted_providers=_capability_trusted_names("kline", "twelve_data,akshare,massive,tiingo"),
        cache_ttl_seconds=int(os.getenv("MARKET_KLINE_CACHE_TTL_SECONDS", "60")),
        quote_providers=DEFAULT_QUOTE_PROVIDERS,
        quote_primary_provider=os.getenv("MARKET_QUOTE_PRIMARY_PROVIDER", "yfinance"),
        quote_secondary_provider=os.getenv("MARKET_QUOTE_SECONDARY_PROVIDER", "stooq"),
        quote_trusted_providers=_capability_trusted_names("quote", "twelve_data,massive,tiingo"),
        quote_cache_ttl_seconds=int(os.getenv("MARKET_QUOTE_CACHE_TTL_SECONDS", "30")),
        news_providers=DEFAULT_NEWS_PROVIDERS,
        news_primary_provider=os.getenv("MARKET_NEWS_PRIMARY_PROVIDER", "finnhub"),
        news_secondary_provider=os.getenv("MARKET_NEWS_SECONDARY_PROVIDER", "yfinance"),
        news_trusted_providers=_capability_trusted_names("news", "finnhub"),
        news_cache_ttl_seconds=int(os.getenv("MARKET_NEWS_CACHE_TTL_SECONDS", "300")),
        financial_providers=DEFAULT_FINANCIAL_PROVIDERS,
        financial_primary_provider=os.getenv("MARKET_FINANCIAL_PRIMARY_PROVIDER", "yfinance"),
        financial_secondary_provider=os.getenv("MARKET_FINANCIAL_SECONDARY_PROVIDER", "sec_companyfacts"),
        financial_trusted_providers=_capability_trusted_names("financial", "sec_companyfacts"),
        financial_cache_ttl_seconds=int(os.getenv("MARKET_FINANCIAL_CACHE_TTL_SECONDS", "3600")),
    )


_gateway: MarketDataGateway | None = None
_gateway_lock = threading.Lock()


def get_market_data_gateway() -> MarketDataGateway:
    global _gateway
    if _gateway is not None:
        return _gateway
    with _gateway_lock:
        if _gateway is None:
            _gateway = _build_default_gateway()
    return _gateway


def reset_market_data_gateway() -> None:
    """测试和配置重载时清除进程内 singleton/cache。"""
    global _gateway
    with _gateway_lock:
        _gateway = None


__all__ = [
    "MARKET_DATA_UNAVAILABLE",
    "MarketDataGateway",
    "MarketDataValidationError",
    "get_market_data_gateway",
    "reset_market_data_gateway",
    "validate_financial_payload",
    "validate_kline_bars",
    "validate_news_items",
    "validate_quote_payload",
]

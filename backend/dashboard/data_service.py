"""Dashboard data service helpers.

This module consolidates market/snapshot/news data retrieval and lightweight
normalization for Dashboard API responses.
"""

from __future__ import annotations

import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

import pandas as pd

from backend.dashboard.cache import dashboard_cache
from backend.utils.quote import safe_float

logger = logging.getLogger(__name__)


_SOURCE_RELIABILITY_WEIGHTS = {
    "reuters": 0.95,
    "bloomberg": 0.95,
    "wall street journal": 0.9,
    "wsj": 0.9,
    "financial times": 0.9,
    "fitch": 0.88,
    "moody": 0.88,
    "s&p global": 0.88,
    "sec": 0.86,
    "cnbc": 0.82,
    "marketwatch": 0.8,
    "yahoo": 0.72,
    "finnhub": 0.72,
    "alpha vantage": 0.68,
}

_HIGH_IMPACT_KEYWORDS = {
    "earnings",
    "guidance",
    "merger",
    "acquisition",
    "lawsuit",
    "investigation",
    "downgrade",
    "upgrade",
    "layoff",
    "default",
    "bankruptcy",
    "rate hike",
    "rate cut",
    "cpi",
    "inflation",
    "tariff",
}

_MEDIUM_IMPACT_KEYWORDS = {
    "forecast",
    "estimate",
    "partnership",
    "supply",
    "demand",
    "regulation",
    "approval",
    "launch",
    "product",
    "guidance update",
}

_ASSET_ALIAS_WEIGHTS = {
    "GOOGL": {"google", "alphabet"},
    "GOOG": {"google", "alphabet"},
    "META": {"meta", "facebook"},
    "MSFT": {"microsoft"},
    "AAPL": {"apple"},
    "TSLA": {"tesla"},
    "NVDA": {"nvidia"},
    "AMZN": {"amazon"},
}

_NEWS_RANKING_WEIGHTS: dict[str, dict[str, float]] = {
    "market": {
        "time_decay": 0.45,
        "source_reliability": 0.25,
        "impact_score": 0.2,
        "asset_relevance": 0.1,
    },
    "impact": {
        "time_decay": 0.35,
        "source_reliability": 0.2,
        "impact_score": 0.25,
        "asset_relevance": 0.2,
    },
}

_NEWS_RANKING_HALF_LIFE_HOURS = {
    "market": 24.0,
    "impact": 36.0,
}


_FEAR_GREED_PATTERN = re.compile(
    r"(?:fear\s*&?\s*greed(?:\s*index)?|恐惧贪婪指数)[^0-9]{0,20}([0-9]{1,3}(?:\.\d+)?)",
    re.IGNORECASE,
)


def _label_fear_greed(value: float) -> str:
    score = max(0.0, min(100.0, float(value)))
    if score <= 20:
        return "extreme_fear"
    if score <= 40:
        return "fear"
    if score <= 60:
        return "neutral"
    if score <= 80:
        return "greed"
    return "extreme_greed"


def _parse_fear_greed_value(text: str) -> Optional[float]:
    if not isinstance(text, str) or not text.strip():
        return None
    m = _FEAR_GREED_PATTERN.search(text)
    if not m:
        return None
    try:
        value = float(m.group(1))
    except Exception:
        return None
    return max(0.0, min(100.0, value))


def fetch_macro_snapshot() -> dict[str, Any]:
    """
    Build a lightweight macro snapshot for dashboard first paint.

    Data sources:
    - get_market_sentiment(): CNN Fear & Greed text
    - get_fred_data(): macro fundamentals (rates, CPI, unemployment, etc.)
    """
    snapshot: dict[str, Any] = {
        "fear_greed_index": None,
        "fear_greed_label": "",
        "sentiment_text": "",
        "fed_rate": None,
        "cpi": None,
        "unemployment": None,
        "gdp_growth": None,
        "treasury_10y": None,
        "yield_spread": None,
        "source": "macro_tools",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "status": "unavailable",
    }

    has_fear_greed = False
    has_fred = False

    try:
        from backend.tools.macro import get_market_sentiment

        sentiment_text = str(get_market_sentiment() or "").strip()
        if sentiment_text:
            snapshot["sentiment_text"] = sentiment_text
            fear_greed_value = _parse_fear_greed_value(sentiment_text)
            if fear_greed_value is not None:
                snapshot["fear_greed_index"] = fear_greed_value
                snapshot["fear_greed_label"] = _label_fear_greed(fear_greed_value)
                has_fear_greed = True
    except Exception as exc:
        logger.info("[DataService] fetch_macro_snapshot sentiment failed: %s", exc)

    try:
        from backend.tools.macro import get_fred_data

        fred_payload = get_fred_data()
        if isinstance(fred_payload, dict):
            for key in ("fed_rate", "cpi", "unemployment", "gdp_growth", "treasury_10y", "yield_spread"):
                value = safe_float(fred_payload.get(key))
                if value is not None:
                    snapshot[key] = value
                    has_fred = True
            fred_as_of = str(fred_payload.get("as_of") or "").strip()
            if fred_as_of:
                snapshot["as_of"] = fred_as_of
    except Exception as exc:
        logger.info("[DataService] fetch_macro_snapshot FRED failed: %s", exc)

    if has_fear_greed and has_fred:
        snapshot["status"] = "ok"
    elif has_fear_greed or has_fred:
        snapshot["status"] = "partial"

    return snapshot


def _ts_seconds(ts: Any) -> Optional[int]:
    if ts is None:
        return None
    try:
        if isinstance(ts, (int, float)):
            return int(ts)
        if isinstance(ts, pd.Timestamp):
            return int(ts.to_pydatetime().timestamp())
        if isinstance(ts, datetime):
            dt = ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
        if isinstance(ts, str):
            raw = ts.strip()
            if not raw:
                return None
            iso = raw.replace("Z", "+00:00")
            try:
                return int(datetime.fromisoformat(iso).timestamp())
            except ValueError:
                for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
                    try:
                        return int(datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc).timestamp())
                    except ValueError:
                        continue
    except Exception:
        return None
    return None


def _parse_time_to_unix(time_value: Any) -> Optional[int]:
    return _ts_seconds(time_value)


def fetch_market_chart(symbol: str, period: str = "1y", interval: str = "1d") -> list[dict[str, Any]]:
    try:
        from backend.tools.price import get_stock_historical_data

        result = get_stock_historical_data(symbol, period=period, interval=interval)
        if not isinstance(result, dict) or result.get("error"):
            return []

        rows = result.get("kline_data") or []
        output: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ts = _parse_time_to_unix(row.get("time"))
            if ts is None:
                continue
            output.append(
                {
                    "time": ts,
                    "open": safe_float(row.get("open")),
                    "high": safe_float(row.get("high")),
                    "low": safe_float(row.get("low")),
                    "close": safe_float(row.get("close")),
                    "volume": safe_float(row.get("volume")) or 0,
                }
            )
        return output
    except Exception as exc:
        logger.info("[DataService] fetch_market_chart failed for %s: %s", symbol, exc)
        return []


def fetch_snapshot(symbol: str, asset_type: str) -> dict[str, Any]:
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        info: dict[str, Any] = {}
        try:
            info = getattr(ticker, "info", {}) or {}
        except Exception:
            info = {}

        last_close = None
        try:
            hist = ticker.history(period="5d", interval="1d")
            if hist is not None and not hist.empty:
                last_close = safe_float(hist["Close"].iloc[-1])
        except Exception:
            last_close = None

        output: dict[str, Any] = {}
        if asset_type == "equity":
            output.update(
                {
                    "revenue": safe_float(info.get("totalRevenue")),
                    "eps": safe_float(info.get("trailingEps") or info.get("forwardEps")),
                    "gross_margin": safe_float(info.get("grossMargins")),
                    "fcf": safe_float(info.get("freeCashflow")),
                }
            )
        elif asset_type in {"index", "crypto"}:
            if last_close is not None:
                output["index_level"] = last_close
        elif asset_type == "etf":
            nav = safe_float(info.get("navPrice"))
            output["nav"] = nav if nav is not None else last_close

        return output
    except Exception as exc:
        logger.info("[DataService] fetch_snapshot failed for %s: %s", symbol, exc)
        return {}


def fetch_revenue_trend(symbol: str) -> list[dict[str, Any]]:
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        financials = getattr(ticker, "quarterly_income_stmt", None)
        if financials is None or (hasattr(financials, "empty") and financials.empty):
            financials = getattr(ticker, "quarterly_financials", None)
        if financials is None or (hasattr(financials, "empty") and financials.empty):
            return []

        revenue_row = None
        for key in ("Total Revenue", "Revenue", "Net Sales", "Operating Revenue"):
            if key in financials.index:
                revenue_row = financials.loc[key]
                break
        if revenue_row is None:
            return []

        output: list[dict[str, Any]] = []
        for col in revenue_row.index:
            value = safe_float(revenue_row[col])
            if value is None:
                continue
            if isinstance(col, pd.Timestamp):
                period = f"{col.year} Q{(col.month - 1) // 3 + 1}"
            else:
                period = str(col)[:10]
            output.append({"period": period, "value": value, "name": period})

        output.reverse()
        return output[-8:]
    except Exception as exc:
        logger.info("[DataService] fetch_revenue_trend failed for %s: %s", symbol, exc)
        return []


def fetch_segment_mix(symbol: str) -> list[dict[str, Any]]:
    try:
        from backend.tools.fmp import get_revenue_product_segmentation

        rows = get_revenue_product_segmentation(symbol)
        if not rows:
            return []
        return [
            {
                "name": row.get("segment", "Unknown"),
                "value": row.get("revenue", 0),
                "weight": row.get("percentage", 0) / 100,
            }
            for row in rows
        ]
    except Exception:
        return []


def _resolve_source_reliability(source: str) -> float:
    text = (source or "").strip().lower()
    if not text:
        return 0.6
    for key, score in _SOURCE_RELIABILITY_WEIGHTS.items():
        if key in text:
            return score
    return 0.65


def _estimate_impact_score(title: str, summary: str) -> float:
    content = f"{title or ''} {summary or ''}".lower()
    high_hits = sum(1 for token in _HIGH_IMPACT_KEYWORDS if token in content)
    medium_hits = sum(1 for token in _MEDIUM_IMPACT_KEYWORDS if token in content)
    score = 0.45 + min(0.35, high_hits * 0.15) + min(0.2, medium_hits * 0.06)
    return max(0.0, min(1.0, score))


def _calculate_time_decay(ts_iso: str, *, half_life_hours: float = 36.0) -> float:
    if not ts_iso:
        return 0.5
    try:
        dt = datetime.fromisoformat(str(ts_iso).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        age_hours = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 3600)
        safe_half_life = max(1.0, float(half_life_hours))
        return math.exp(-age_hours / safe_half_life)
    except Exception:
        return 0.5


def _build_asset_tokens(symbol: str) -> set[str]:
    normalized_symbol = (symbol or "").strip().upper()
    if not normalized_symbol:
        return set()

    tokens: set[str] = {
        normalized_symbol.lower(),
        normalized_symbol.replace(".", "").lower(),
        normalized_symbol.replace("-", "").lower(),
    }
    tokens.update(_ASSET_ALIAS_WEIGHTS.get(normalized_symbol, set()))
    return {token.strip().lower() for token in tokens if token and token.strip()}


def _estimate_asset_relevance(symbol: str, mode: str, title: str, summary: str) -> float:
    content = f"{title or ''} {summary or ''}".lower()
    if not content:
        return 0.35 if mode == "impact" else 0.4

    tokens = _build_asset_tokens(symbol)
    mention_hits = sum(1 for token in tokens if token in content)

    high_hits = sum(1 for token in _HIGH_IMPACT_KEYWORDS if token in content)
    medium_hits = sum(1 for token in _MEDIUM_IMPACT_KEYWORDS if token in content)

    base = 0.35 if mode == "impact" else 0.4
    mention_boost = min(0.4, mention_hits * (0.2 if mode == "impact" else 0.12))
    keyword_boost = min(0.25, high_hits * 0.05 + medium_hits * 0.02)
    score = base + mention_boost + keyword_boost
    return max(0.0, min(1.0, score))


def _calculate_source_penalty(source: str, source_counts: dict[str, int]) -> float:
    normalized_source = (source or "").strip().lower()
    if not normalized_source:
        return 0.0
    duplicate_count = max(0, source_counts.get(normalized_source, 0) - 1)
    if duplicate_count == 0:
        return 0.0
    return min(0.08, duplicate_count * 0.02)


def _build_ranking_reason(weighted_components: dict[str, float], source_penalty: float) -> str:
    ordered = sorted(weighted_components.items(), key=lambda kv: kv[1], reverse=True)
    dominant = [f"{key}={value:.2f}" for key, value in ordered[:2] if value > 0]
    if source_penalty > 0:
        dominant.append(f"source_penalty=-{source_penalty:.2f}")
    if not dominant:
        return "fallback_scoring"
    return ", ".join(dominant)


def _score_news_item(
    item: dict[str, Any],
    *,
    symbol: str,
    mode: str,
    source_counts: dict[str, int],
) -> dict[str, Any]:
    title = str(item.get("title") or "")
    summary = str(item.get("summary") or "")
    source = str(item.get("source") or "")
    ts = str(item.get("ts") or "")

    weights = _NEWS_RANKING_WEIGHTS.get(mode, _NEWS_RANKING_WEIGHTS["market"])
    half_life_hours = _NEWS_RANKING_HALF_LIFE_HOURS.get(mode, 36.0)

    time_decay = _calculate_time_decay(ts, half_life_hours=half_life_hours)
    source_reliability = _resolve_source_reliability(source)
    impact_score = _estimate_impact_score(title, summary)
    asset_relevance = _estimate_asset_relevance(symbol, mode, title, summary)
    source_penalty = _calculate_source_penalty(source, source_counts)

    weighted_components = {
        "time_decay": time_decay * weights["time_decay"],
        "source_reliability": source_reliability * weights["source_reliability"],
        "impact_score": impact_score * weights["impact_score"],
        "asset_relevance": asset_relevance * weights["asset_relevance"],
    }
    ranking_score = max(0.0, min(1.0, sum(weighted_components.values()) - source_penalty))

    result = dict(item)
    result.update(
        {
            "time_decay": round(time_decay, 6),
            "source_reliability": round(source_reliability, 6),
            "impact_score": round(impact_score, 6),
            "asset_relevance": round(asset_relevance, 6),
            "source_penalty": round(source_penalty, 6),
            "ranking_score": round(ranking_score, 6),
            "ranking_reason": _build_ranking_reason(weighted_components, source_penalty),
            "ranking_factors": {
                "mode": mode,
                "half_life_hours": half_life_hours,
                "weights": {key: round(value, 6) for key, value in weights.items()},
                "weighted": {key: round(value, 6) for key, value in weighted_components.items()},
            },
        }
    )
    return result


def _rank_news_items(items: list[dict[str, Any]], limit: int, *, symbol: str, mode: str) -> list[dict[str, Any]]:
    source_counts: dict[str, int] = {}
    for item in items:
        source_key = str(item.get("source") or "").strip().lower()
        if source_key:
            source_counts[source_key] = source_counts.get(source_key, 0) + 1

    scored = [_score_news_item(item, symbol=symbol, mode=mode, source_counts=source_counts) for item in items]
    scored.sort(
        key=lambda item: (
            -float(item.get("ranking_score") or 0.0),
            -(float(_ts_seconds(item.get("ts")) or 0.0)),
            -float(item.get("impact_score") or 0.0),
            -float(item.get("asset_relevance") or 0.0),
            str(item.get("title") or "").lower(),
            str(item.get("source") or "").lower(),
        )
    )
    return scored[:limit]


def _to_news_item(item: Any) -> dict[str, Any]:
    if isinstance(item, dict):
        title = item.get("title") or item.get("headline") or ""
        url = item.get("url") or item.get("link") or ""
        source = item.get("source") or item.get("publisher") or ""
        ts = item.get("ts") or item.get("published_at") or item.get("datetime") or ""
        summary = item.get("summary") or item.get("snippet") or item.get("content") or ""
        tags = item.get("tags")  # Phase H: pass through server-computed tags

        if isinstance(ts, (int, float)):
            try:
                ts = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
            except Exception:
                ts = ""
        elif not isinstance(ts, str):
            ts = str(ts) if ts else ""

        result: dict[str, Any] = {
            "title": str(title).strip(),
            "url": str(url).strip(),
            "source": str(source).strip(),
            "ts": ts,
            "summary": str(summary).strip(),
        }
        # Attach tags if present (Phase H)
        if tags and isinstance(tags, list):
            result["tags"] = tags
        return result

    text = str(item).strip() if item is not None else ""
    return {"title": text, "url": "", "source": "", "ts": "", "summary": ""}


def _parse_news_text(text: str) -> list[dict[str, Any]]:
    """Parse formatted headline text returned by get_market_news_headlines().

    Expected line formats:
      1. [2026-02-10] [Tag] [Title](url) (Source) - Snippet
      2. [2026-02-10] Title (Source) - Snippet
      3. plain title text
    """
    import re as _re

    rows: list[dict[str, Any]] = []
    if not text:
        return rows

    # Patterns for structured extraction
    date_pat = _re.compile(r"\[(\d{4}-\d{2}-\d{2})\]")
    link_pat = _re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
    source_pat = _re.compile(r"\(([A-Za-z][A-Za-z0-9 .&'-]{0,40})\)")

    for line in text.strip().splitlines():
        stripped = line.strip()
        # Skip header lines and very short lines
        if not stripped or len(stripped) < 12:
            continue
        # Skip header-like lines (e.g. "最近48小时市场要闻(RSS):")
        if stripped.endswith(":") and ("要闻" in stripped or "热点" in stripped):
            continue
        # Remove leading numbering "1. ", "2. " etc.
        stripped = _re.sub(r"^\d+\.\s*", "", stripped).strip()
        if not stripped:
            continue

        # Extract date
        ts = ""
        dm = date_pat.search(stripped)
        if dm:
            ts = dm.group(1)

        # Extract markdown link [title](url)
        title = ""
        url = ""
        lm = link_pat.search(stripped)
        if lm:
            title = lm.group(1).strip()
            url = lm.group(2).strip()

        # Extract source (word in parentheses, not a URL)
        source = ""
        for sm in source_pat.finditer(stripped):
            candidate = sm.group(1).strip()
            # Skip if it looks like a URL or is a date
            if "http" in candidate or _re.match(r"^\d{4}-", candidate):
                continue
            source = candidate
            break

        # Extract snippet (text after " - ")
        summary = ""
        dash_idx = stripped.find(" - ", (lm.end() if lm else 0))
        if dash_idx > 0:
            summary = stripped[dash_idx + 3:].strip()

        # Fallback title: use the whole line (cleaned)
        if not title:
            # Remove date bracket, tags, source
            fallback = stripped
            fallback = date_pat.sub("", fallback)
            fallback = _re.sub(r"\[[A-Za-z/]+\]\s*", "", fallback)
            fallback = source_pat.sub("", fallback)
            fallback = fallback.strip(" -")
            title = fallback[:160] if fallback else stripped[:160]

        if title:
            rows.append({
                "title": title,
                "url": url,
                "source": source,
                "ts": ts,
                "summary": summary[:200],
            })
    return rows


def fetch_news(symbol: str, limit: int = 20) -> dict[str, Any]:
    try:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
        from backend.tools.news import get_company_news, get_market_news_headlines

        impact_items: list[Any] = []
        market_items: list[Any] = []

        # Parallel fetch: company news + market headlines
        with ThreadPoolExecutor(max_workers=2) as pool:
            f_impact = pool.submit(get_company_news, symbol, limit)
            f_market = pool.submit(get_market_news_headlines, limit)

            try:
                raw_impact = f_impact.result(timeout=30)
                if isinstance(raw_impact, list):
                    impact_items = raw_impact
                elif isinstance(raw_impact, str):
                    impact_items = _parse_news_text(raw_impact)
            except (FuturesTimeout, Exception) as exc:
                logger.info("[DataService] get_company_news failed for %s: %s", symbol, exc)

            try:
                raw_market = f_market.result(timeout=30)
                if isinstance(raw_market, list):
                    market_items = raw_market
                elif isinstance(raw_market, str):
                    market_items = _parse_news_text(raw_market)
            except (FuturesTimeout, Exception) as exc:
                logger.info("[DataService] get_market_news_headlines failed: %s", exc)

        market_raw = [_to_news_item(item) for item in market_items[:limit]]
        impact_raw = [_to_news_item(item) for item in impact_items[:limit]]

        result = {
            "market": _rank_news_items(market_raw, limit, symbol=symbol, mode="market"),
            "impact": _rank_news_items(impact_raw, limit, symbol=symbol, mode="impact"),
            "market_raw": market_raw,
            "impact_raw": impact_raw,
            "ranking_meta": {
                "version": "v2",
                "formula": "sum(weight_i * factor_i) - source_penalty",
                "weights": _NEWS_RANKING_WEIGHTS,
                "half_life_hours": _NEWS_RANKING_HALF_LIFE_HOURS,
                "notes": [
                    "ranked by recency, source reliability, impact, and asset relevance",
                    "duplicate-source penalty improves feed diversity",
                ],
            },
        }
        return result
    except Exception as exc:
        logger.info("[DataService] fetch_news failed for %s: %s", symbol, exc)
        return {
            "market": [],
            "impact": [],
            "market_raw": [],
            "impact_raw": [],
            "ranking_meta": {
                "version": "v2",
                "formula": "sum(weight_i * factor_i) - source_penalty",
                "weights": _NEWS_RANKING_WEIGHTS,
                "half_life_hours": _NEWS_RANKING_HALF_LIFE_HOURS,
                "notes": [
                    "ranked by recency, source reliability, impact, and asset relevance",
                    "duplicate-source penalty improves feed diversity",
                ],
            },
        }


def fetch_sector_weights(symbol: str, asset_type: str) -> list[dict[str, Any]]:
    if asset_type not in {"etf", "index"}:
        return []
    try:
        from backend.tools.fmp import get_etf_sector_weights

        rows = get_etf_sector_weights(symbol)
        if not rows:
            return []
        return [
            {"name": row.get("sector", "Unknown"), "weight": row.get("weight", 0) / 100}
            for row in rows
        ]
    except Exception:
        return []


def fetch_top_constituents(symbol: str, asset_type: str, limit: int = 10) -> list[dict[str, Any]]:
    if asset_type != "index":
        return []
    try:
        from backend.tools.fmp import get_index_constituents

        rows = get_index_constituents(symbol)
        if not rows:
            return []
        return [
            {
                "symbol": row.get("symbol", ""),
                "name": row.get("name", ""),
                "weight": row.get("weight", 0),
            }
            for row in rows[:limit]
        ]
    except Exception:
        return []


def fetch_holdings(symbol: str, asset_type: str, limit: int = 50) -> list[dict[str, Any]]:
    if asset_type not in {"etf", "portfolio"}:
        return []
    try:
        from backend.tools.fmp import get_etf_holdings

        rows = get_etf_holdings(symbol, limit=limit)
        if not rows:
            return []
        return [
            {
                "symbol": row.get("symbol", ""),
                "name": row.get("name", ""),
                "weight": row.get("weight", 0),
                "shares": row.get("shares", 0),
                "value": row.get("value", 0),
            }
            for row in rows[:limit]
        ]
    except Exception:
        return []


# ══════════════════════════════════════════════════════════════════════════════
# v2 data fetch functions (equity only)
# ══════════════════════════════════════════════════════════════════════════════
# Performance budget (Gate-4):
# ┌──────────────┬─────────┬───────────┬──────────┬───────────────────┐
# │ Source       │ Timeout │ Cache TTL │ Max Par  │ fallback          │
# ├──────────────┼─────────┼───────────┼──────────┼───────────────────┤
# │ valuation    │ 5s      │ 300s(5m)  │ 1        │ return None       │
# │ financials   │ 8s      │ 3600s(1h) │ 1        │ return None       │
# │ technicals   │ 5s      │ 60s       │ 1        │ return None       │
# │ peers        │ 10s     │ 3600s(1h) │ 3(batch) │ return None       │
# └──────────────┴─────────┴───────────┴──────────┴───────────────────┘


def _infer_equity_market(symbol: str) -> str:
    ticker = str(symbol or "").strip().upper()
    if ticker.endswith((".SS", ".SZ", ".BJ")):
        return "CN"
    if ticker.endswith(".HK"):
        return "HK"
    return "US"


def _build_ohlcv_frame_from_rows(rows: list[dict[str, Any]]) -> Optional[pd.DataFrame]:
    records: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        dt = pd.to_datetime(row.get("time"), errors="coerce")
        if pd.isna(dt):
            continue
        records.append(
            {
                "Date": dt,
                "Open": safe_float(row.get("open")),
                "High": safe_float(row.get("high")),
                "Low": safe_float(row.get("low")),
                "Close": safe_float(row.get("close")),
                "Volume": safe_float(row.get("volume")) or 0.0,
            }
        )
    if not records:
        return None
    frame = pd.DataFrame.from_records(records)
    frame = frame.dropna(subset=["Date", "Open", "High", "Low", "Close"])
    if frame.empty:
        return None
    return frame.sort_values("Date").set_index("Date")


def _load_ohlcv_frame(symbol: str, period: str = "1y", interval: str = "1d") -> Optional[pd.DataFrame]:
    """Load OHLCV frame with yfinance primary + shared multi-source fallback."""
    market = _infer_equity_market(symbol)
    if market in {"CN", "HK"}:
        try:
            from backend.tools.cn_hk_market import fetch_cn_hk_kline

            cn_hk_rows = fetch_cn_hk_kline(symbol, limit=300)
            frame = _build_ohlcv_frame_from_rows(cn_hk_rows)
            if frame is not None and not frame.empty:
                return frame
        except Exception as exc:
            logger.info("[DataService] CN/HK OHLCV fallback failed for %s: %s", symbol, exc)

    try:
        import yfinance as yf

        hist = yf.Ticker(symbol).history(period=period, interval=interval)
        if hist is not None and not hist.empty:
            return hist
    except Exception as exc:
        logger.info("[DataService] yfinance OHLCV failed for %s: %s", symbol, exc)

    # Fast fallback: Stooq is usually quicker than the full multi-source pipeline
    # and helps avoid technical tab timeouts when yfinance is rate-limited.
    try:
        from backend.tools.price import _fetch_with_stooq_history

        payload = _fetch_with_stooq_history(symbol, period=period, interval=interval)
        if isinstance(payload, dict):
            rows = payload.get("kline_data") or []
            frame = _build_ohlcv_frame_from_rows(rows)
            if frame is not None and not frame.empty:
                logger.info(
                    "[DataService] OHLCV fallback hit for %s via Stooq (%s rows)",
                    symbol,
                    len(frame),
                )
                return frame
    except Exception as exc:
        logger.info("[DataService] Stooq OHLCV fallback failed for %s: %s", symbol, exc)

    try:
        from backend.tools.price import get_stock_historical_data

        payload = get_stock_historical_data(symbol, period=period, interval=interval)
        if not isinstance(payload, dict):
            return None
        rows = payload.get("kline_data") or []
        if not isinstance(rows, list) or not rows:
            return None

        frame = _build_ohlcv_frame_from_rows(rows)
        if frame is None or frame.empty:
            return None
        logger.info(
            "[DataService] OHLCV fallback hit for %s via price pipeline (%s rows)",
            symbol,
            len(frame),
        )
        return frame
    except Exception as exc:
        logger.info("[DataService] fallback OHLCV failed for %s: %s", symbol, exc)
        return None


_FINNHUB_BASE_URL = "https://finnhub.io/api/v1"


def _finnhub_request(path: str, params: Optional[dict[str, Any]] = None) -> Any | None:
    """Best-effort Finnhub request helper."""
    try:
        from backend.tools.env import FINNHUB_API_KEY
        from backend.tools.http import _http_get

        token = str(FINNHUB_API_KEY or "").strip()
        if not token:
            return None
        query = dict(params or {})
        query["token"] = token
        url = f"{_FINNHUB_BASE_URL}/{path.lstrip('/')}"
        resp = _http_get(url, params=query, timeout=12)
        if getattr(resp, "status_code", 0) != 200:
            return None
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("error"):
            return None
        return payload
    except Exception as exc:
        logger.info("[DataService] Finnhub request failed for %s: %s", path, exc)
        return None


def _finnhub_percent_to_ratio(value: Any) -> Optional[float]:
    """Convert Finnhub percentage-like values into decimal ratio."""
    number = safe_float(value)
    if number is None:
        return None
    return number / 100.0


def _finnhub_market_cap_to_usd(value: Any) -> Optional[float]:
    """Finnhub marketCapitalization is in millions of USD."""
    number = safe_float(value)
    if number is None:
        return None
    return number * 1_000_000.0


def _fetch_valuation_from_finnhub(symbol: str) -> dict[str, Any] | None:
    """Fallback valuation fetcher using Finnhub free endpoints."""
    profile = _finnhub_request("stock/profile2", {"symbol": symbol})
    metric_payload = _finnhub_request("stock/metric", {"symbol": symbol, "metric": "all"})
    metric = metric_payload.get("metric") if isinstance(metric_payload, dict) else {}
    if not isinstance(metric, dict):
        metric = {}

    result = {
        "market_cap": _finnhub_market_cap_to_usd(
            (profile or {}).get("marketCapitalization") if isinstance(profile, dict) else metric.get("marketCapitalization")
        ),
        "trailing_pe": safe_float(metric.get("peTTM") or metric.get("peBasicExclExtraTTM")),
        "forward_pe": safe_float(metric.get("forwardPE") or metric.get("peExclExtraAnnual")),
        "price_to_book": safe_float(metric.get("pbQuarterly")),
        "price_to_sales": safe_float(metric.get("psTTM")),
        "ev_to_ebitda": safe_float(metric.get("evEbitdaTTM")),
        "dividend_yield": _finnhub_percent_to_ratio(metric.get("dividendYieldIndicatedAnnual")),
        "beta": safe_float(metric.get("beta")),
        "week52_high": safe_float(metric.get("52WeekHigh")),
        "week52_low": safe_float(metric.get("52WeekLow")),
    }
    if all(v is None for v in result.values()):
        return None
    return result


def _fetch_valuation_from_cn_hk_market(symbol: str) -> dict[str, Any] | None:
    try:
        from backend.tools.cn_hk_market import fetch_cn_hk_quote_metrics

        payload = fetch_cn_hk_quote_metrics(symbol)
        if not isinstance(payload, dict):
            return None
        result = {
            "market_cap": safe_float(payload.get("market_cap")),
            "trailing_pe": safe_float(payload.get("trailing_pe")),
            "forward_pe": safe_float(payload.get("forward_pe")),
            "price_to_book": safe_float(payload.get("price_to_book")),
            "price_to_sales": safe_float(payload.get("price_to_sales")),
            "ev_to_ebitda": safe_float(payload.get("ev_to_ebitda")),
            "dividend_yield": safe_float(payload.get("dividend_yield")),
            "beta": safe_float(payload.get("beta")),
            "week52_high": safe_float(payload.get("week52_high")),
            "week52_low": safe_float(payload.get("week52_low")),
        }
        if all(v is None for v in result.values()):
            return None
        return result
    except Exception as exc:
        logger.info("[DataService] CN/HK valuation fallback failed for %s: %s", symbol, exc)
        return None


def _match_report_value(
    rows: list[dict[str, Any]],
    *,
    label_terms: tuple[str, ...] = (),
    concept_terms: tuple[str, ...] = (),
) -> Optional[float]:
    for row in rows:
        if not isinstance(row, dict):
            continue
        label = str(row.get("label") or "").strip().lower()
        concept = str(row.get("concept") or "").strip().lower()
        value = safe_float(row.get("value"))
        if value is None:
            continue
        if label_terms and any(term in label for term in label_terms):
            return value
        if concept_terms and any(term in concept for term in concept_terms):
            return value
    return None


def _fetch_financial_statements_from_sec_companyfacts(symbol: str, periods: int = 8) -> dict[str, Any] | None:
    try:
        from backend.tools.sec import get_sec_company_facts_quarterly

        payload = get_sec_company_facts_quarterly(symbol, limit=periods)
        if not isinstance(payload, dict) or payload.get("error"):
            return None
        result = {
            "periods": payload.get("periods") or [],
            "revenue": payload.get("revenue") or [],
            "gross_profit": payload.get("gross_profit") or [],
            "operating_income": payload.get("operating_income") or [],
            "net_income": payload.get("net_income") or [],
            "eps": payload.get("eps") or [],
            "total_assets": payload.get("total_assets") or [],
            "total_liabilities": payload.get("total_liabilities") or [],
            "operating_cash_flow": payload.get("operating_cash_flow") or [],
            "free_cash_flow": payload.get("free_cash_flow") or [],
        }
        metric_fields = [
            "revenue",
            "gross_profit",
            "operating_income",
            "net_income",
            "eps",
            "total_assets",
            "total_liabilities",
            "operating_cash_flow",
            "free_cash_flow",
        ]
        has_any_value = any(
            any(value is not None for value in (result.get(field) or []))
            for field in metric_fields
        )
        return result if has_any_value else None
    except Exception as exc:
        logger.info("[DataService] SEC companyfacts fallback failed for %s: %s", symbol, exc)
        return None


def _fetch_financial_statements_from_cn_hk_market(symbol: str, periods: int = 8) -> dict[str, Any] | None:
    try:
        from backend.tools.cn_hk_market import fetch_cn_hk_financial_statements

        payload = fetch_cn_hk_financial_statements(symbol, periods=periods)
        if not isinstance(payload, dict):
            return None
        result = {
            "periods": payload.get("periods") or [],
            "revenue": payload.get("revenue") or [],
            "gross_profit": payload.get("gross_profit") or [],
            "operating_income": payload.get("operating_income") or [],
            "net_income": payload.get("net_income") or [],
            "eps": payload.get("eps") or [],
            "total_assets": payload.get("total_assets") or [],
            "total_liabilities": payload.get("total_liabilities") or [],
            "operating_cash_flow": payload.get("operating_cash_flow") or [],
            "free_cash_flow": payload.get("free_cash_flow") or [],
        }
        metric_fields = [
            "revenue",
            "gross_profit",
            "operating_income",
            "net_income",
            "eps",
            "total_assets",
            "total_liabilities",
            "operating_cash_flow",
            "free_cash_flow",
        ]
        has_any_value = any(
            any(value is not None for value in (result.get(field) or []))
            for field in metric_fields
        )
        return result if has_any_value else None
    except Exception as exc:
        logger.info("[DataService] CN/HK financials fallback failed for %s: %s", symbol, exc)
        return None


def _fetch_financial_statements_from_finnhub(symbol: str, periods: int = 8) -> dict[str, Any] | None:
    """Fallback quarterly statements fetch using Finnhub financial reports."""
    payload = _finnhub_request("stock/financials-reported", {"symbol": symbol})
    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or not rows:
        return None

    parsed: list[dict[str, Any]] = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        report = item.get("report")
        if not isinstance(report, dict):
            continue
        year = int(item.get("year") or 0)
        quarter = int(item.get("quarter") or 0)
        if year <= 0:
            continue
        label = f"{year}Q{quarter}" if quarter > 0 else f"{year}FY"
        parsed.append(
            {
                "period": label,
                "year": year,
                "quarter": quarter,
                "report": report,
            }
        )

    if not parsed:
        return None

    quarterly = [entry for entry in parsed if entry["quarter"] > 0]
    selected_source = quarterly if quarterly else parsed
    selected_source = sorted(
        selected_source,
        key=lambda entry: (entry["year"], entry["quarter"]),
        reverse=True,
    )

    deduped: list[dict[str, Any]] = []
    seen_periods: set[str] = set()
    for entry in selected_source:
        period = entry["period"]
        if period in seen_periods:
            continue
        seen_periods.add(period)
        deduped.append(entry)
        if len(deduped) >= max(1, periods):
            break

    if not deduped:
        return None

    period_labels: list[str] = []
    revenue: list[Optional[float]] = []
    gross_profit: list[Optional[float]] = []
    operating_income: list[Optional[float]] = []
    net_income: list[Optional[float]] = []
    eps: list[Optional[float]] = []
    total_assets: list[Optional[float]] = []
    total_liabilities: list[Optional[float]] = []
    operating_cash_flow: list[Optional[float]] = []
    free_cash_flow: list[Optional[float]] = []

    for entry in deduped:
        report = entry["report"]
        ic_rows = report.get("ic") if isinstance(report.get("ic"), list) else []
        bs_rows = report.get("bs") if isinstance(report.get("bs"), list) else []
        cf_rows = report.get("cf") if isinstance(report.get("cf"), list) else []

        period_labels.append(entry["period"])

        revenue.append(
            _match_report_value(
                ic_rows,
                label_terms=("net sales", "total revenue", "revenue"),
                concept_terms=("revenue", "salesrevenue"),
            )
        )
        gross_profit.append(
            _match_report_value(
                ic_rows,
                label_terms=("gross profit",),
                concept_terms=("grossprofit",),
            )
        )
        operating_income.append(
            _match_report_value(
                ic_rows,
                label_terms=("operating income",),
                concept_terms=("operatingincomeloss",),
            )
        )
        net_income.append(
            _match_report_value(
                ic_rows,
                label_terms=("net income",),
                concept_terms=("netincomeloss",),
            )
        )
        eps.append(
            _match_report_value(
                ic_rows,
                label_terms=("diluted earnings per share", "basic earnings per share", "earnings per share"),
                concept_terms=("earningspersharediluted", "earningspersharebasic"),
            )
        )
        total_assets.append(
            _match_report_value(
                bs_rows,
                label_terms=("total assets",),
                concept_terms=("assets",),
            )
        )
        total_liabilities.append(
            _match_report_value(
                bs_rows,
                label_terms=("total liabilities",),
                concept_terms=("liabilities",),
            )
        )

        ocf_value = _match_report_value(
            cf_rows,
            label_terms=(
                "net cash provided by operating activities",
                "net cash from operating activities",
                "cash generated by operating activities",
            ),
            concept_terms=(
                "netcashprovidedbyusedinoperatingactivities",
                "netcashprovidedbyusedinoperatingactivitiescontinuingoperations",
            ),
        )
        operating_cash_flow.append(ocf_value)

        fcf_value = _match_report_value(
            cf_rows,
            label_terms=("free cash flow",),
            concept_terms=("freecashflow",),
        )
        if fcf_value is None:
            capex = _match_report_value(
                cf_rows,
                label_terms=(
                    "payments to acquire property, plant and equipment",
                    "capital expenditures",
                    "purchase of property and equipment",
                ),
                concept_terms=(
                    "paymentstoacquirepropertyplantandequipment",
                    "capitalexpenditures",
                ),
            )
            if ocf_value is not None and capex is not None:
                fcf_value = ocf_value + capex if capex < 0 else ocf_value - capex
        free_cash_flow.append(fcf_value)

    result: dict[str, Any] = {
        "periods": period_labels,
        "revenue": revenue,
        "gross_profit": gross_profit,
        "operating_income": operating_income,
        "net_income": net_income,
        "eps": eps,
        "total_assets": total_assets,
        "total_liabilities": total_liabilities,
        "operating_cash_flow": operating_cash_flow,
        "free_cash_flow": free_cash_flow,
    }
    metric_fields = [
        "revenue",
        "gross_profit",
        "operating_income",
        "net_income",
        "eps",
        "total_assets",
        "total_liabilities",
        "operating_cash_flow",
        "free_cash_flow",
    ]
    has_any_value = any(
        any(value is not None for value in (result.get(field) or []))
        for field in metric_fields
    )
    return result if has_any_value else None


def fetch_valuation(symbol: str) -> dict[str, Any] | None:
    """Fetch valuation metrics from yfinance Ticker.info.

    Returns a dict matching the ValuationData schema fields, or None on
    failure.
    """
    market = _infer_equity_market(symbol)
    if market in {"CN", "HK"}:
        cn_hk_fallback = _fetch_valuation_from_cn_hk_market(symbol)
        if cn_hk_fallback:
            logger.info("[DataService] valuation fallback via CN/HK source for %s", symbol)
            return cn_hk_fallback

    try:
        import yfinance as yf

        info = yf.Ticker(symbol).info or {}
        result = {
            "market_cap": safe_float(info.get("marketCap")),
            "trailing_pe": safe_float(info.get("trailingPE")),
            "forward_pe": safe_float(info.get("forwardPE")),
            "price_to_book": safe_float(info.get("priceToBook")),
            "price_to_sales": safe_float(info.get("priceToSalesTrailing12Months")),
            "ev_to_ebitda": safe_float(info.get("enterpriseToEbitda")),
            "dividend_yield": safe_float(info.get("dividendYield")),
            "beta": safe_float(info.get("beta")),
            "week52_high": safe_float(info.get("fiftyTwoWeekHigh")),
            "week52_low": safe_float(info.get("fiftyTwoWeekLow")),
        }
        if any(v is not None for v in result.values()):
            return result
    except Exception as exc:
        logger.info("[DataService] fetch_valuation failed for %s: %s", symbol, exc)

    fallback = _fetch_valuation_from_finnhub(symbol)
    if fallback:
        logger.info("[DataService] valuation fallback via Finnhub for %s", symbol)
        return fallback

    if market in {"CN", "HK"}:
        cn_hk_fallback = _fetch_valuation_from_cn_hk_market(symbol)
        if cn_hk_fallback:
            logger.info("[DataService] valuation late fallback via CN/HK source for %s", symbol)
            return cn_hk_fallback
    return None


def fetch_financial_statements(symbol: str, periods: int = 8) -> dict[str, Any] | None:
    """Fetch quarterly financial statements from yfinance.

    Returns a dict matching the FinancialStatement schema, or None on
    failure.
    """
    market = _infer_equity_market(symbol)
    if market in {"CN", "HK"}:
        cn_hk_payload = _fetch_financial_statements_from_cn_hk_market(symbol, periods=periods)
        if cn_hk_payload:
            logger.info("[DataService] financials fallback via CN/HK source for %s", symbol)
            return cn_hk_payload

    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)

        def _period_label(col: Any) -> str:
            if isinstance(col, pd.Timestamp):
                return f"{col.year}Q{(col.month - 1) // 3 + 1}"
            text = str(col).strip()
            if len(text) >= 10 and text[4] == "-" and text[7] == "-":
                try:
                    dt = pd.to_datetime(text)
                    return f"{dt.year}Q{(dt.month - 1) // 3 + 1}"
                except Exception:
                    return text[:10]
            return text[:10]

        def _valid_frame(frame: Optional[pd.DataFrame]) -> bool:
            return frame is not None and hasattr(frame, "empty") and not frame.empty

        def _build_label_map(frame: Optional[pd.DataFrame]) -> dict[str, Any]:
            if not _valid_frame(frame):
                return {}
            mapping: dict[str, Any] = {}
            for col in frame.columns:
                label = _period_label(col)
                if label and label not in mapping:
                    mapping[label] = col
            return mapping

        def _locate_row(frame: Optional[pd.DataFrame], candidates: list[str]) -> Optional[pd.Series]:
            if not _valid_frame(frame):
                return None
            index_lookup = {str(idx).strip().lower(): idx for idx in frame.index}
            for candidate in candidates:
                key = candidate.strip().lower()
                if key in index_lookup:
                    return frame.loc[index_lookup[key]]
            return None

        def _extract_series(frame: Optional[pd.DataFrame], candidates: list[str], labels: list[str]) -> list[Optional[float]]:
            if not labels:
                return []
            row = _locate_row(frame, candidates)
            if row is None:
                return [None for _ in labels]
            label_map = _build_label_map(frame)
            output: list[Optional[float]] = []
            for label in labels:
                col = label_map.get(label)
                output.append(safe_float(row.get(col)) if col is not None else None)
            return output

        income = getattr(ticker, "quarterly_income_stmt", None)
        if income is None or (hasattr(income, "empty") and income.empty):
            income = getattr(ticker, "quarterly_financials", None)
        balance = getattr(ticker, "quarterly_balance_sheet", None)
        cashflow = getattr(ticker, "quarterly_cashflow", None)

        label_candidates: list[str] = []
        for frame in (income, balance, cashflow):
            for label in _build_label_map(frame).keys():
                if label not in label_candidates:
                    label_candidates.append(label)

        period_labels = label_candidates[:periods]
        if not period_labels:
            sec_fallback = _fetch_financial_statements_from_sec_companyfacts(symbol, periods=periods)
            if sec_fallback:
                logger.info("[DataService] financials fallback via SEC companyfacts for %s", symbol)
                return sec_fallback
            fallback = _fetch_financial_statements_from_finnhub(symbol, periods=periods)
            if fallback:
                logger.info("[DataService] financials fallback via Finnhub for %s", symbol)
                return fallback
            return None

        result: dict[str, Any] = {
            "periods": period_labels,
            "revenue": _extract_series(income, ["Total Revenue", "Revenue", "Net Sales", "Operating Revenue"], period_labels),
            "gross_profit": _extract_series(income, ["Gross Profit"], period_labels),
            "operating_income": _extract_series(income, ["Operating Income", "Operating Income Loss"], period_labels),
            "net_income": _extract_series(income, ["Net Income", "Net Income Common Stockholders"], period_labels),
            "eps": _extract_series(income, ["Basic EPS", "Diluted EPS"], period_labels),
            "total_assets": _extract_series(balance, ["Total Assets", "Total Asset"], period_labels),
            "total_liabilities": _extract_series(
                balance,
                ["Total Liabilities Net Minority Interest", "Total Liabilities", "Total Liab", "Liabilities"],
                period_labels,
            ),
            "operating_cash_flow": _extract_series(
                cashflow,
                ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities", "Operating Cash Flow"],
                period_labels,
            ),
            "free_cash_flow": _extract_series(cashflow, ["Free Cash Flow"], period_labels),
        }
        metric_fields = [
            "revenue",
            "gross_profit",
            "operating_income",
            "net_income",
            "eps",
            "total_assets",
            "total_liabilities",
            "operating_cash_flow",
            "free_cash_flow",
        ]
        has_any_value = any(
            any(value is not None for value in (result.get(field) or []))
            for field in metric_fields
        )
        if has_any_value:
            return result

        sec_fallback = _fetch_financial_statements_from_sec_companyfacts(symbol, periods=periods)
        if sec_fallback:
            logger.info("[DataService] financials fallback via SEC companyfacts for %s", symbol)
            return sec_fallback

        fallback = _fetch_financial_statements_from_finnhub(symbol, periods=periods)
        if fallback:
            logger.info("[DataService] financials fallback via Finnhub for %s", symbol)
            return fallback
        return None
    except Exception as exc:
        logger.info("[DataService] fetch_financial_statements failed for %s: %s", symbol, exc)
        sec_fallback = _fetch_financial_statements_from_sec_companyfacts(symbol, periods=periods)
        if sec_fallback:
            logger.info("[DataService] financials fallback via SEC companyfacts for %s", symbol)
            return sec_fallback
        fallback = _fetch_financial_statements_from_finnhub(symbol, periods=periods)
        if fallback:
            logger.info("[DataService] financials fallback via Finnhub for %s", symbol)
            return fallback
        return None


def fetch_technical_indicators(symbol: str) -> dict[str, Any] | None:
    """Compute technical indicators for *symbol*.

    Fetches 1-year daily OHLCV via yfinance and delegates to
    :func:`backend.tools.technical.compute_technical_indicators`.
    """
    try:
        from backend.tools.technical import compute_technical_indicators

        hist = _load_ohlcv_frame(symbol, period="1y", interval="1d")
        if hist is None or hist.empty:
            return None

        result = compute_technical_indicators(hist)
        return result if result else None
    except Exception as exc:
        logger.info("[DataService] fetch_technical_indicators failed for %s: %s", symbol, exc)
        return None


def fetch_indicator_series(symbol: str, n_days: int = 120) -> dict[str, Any] | None:
    """Compute RSI/MACD/BB time series for *symbol* (Phase G2)."""
    try:
        from backend.tools.technical import compute_indicator_series

        hist = _load_ohlcv_frame(symbol, period="1y", interval="1d")
        if hist is None or hist.empty:
            return None

        result = compute_indicator_series(hist, n_days)
        return result if result else None
    except Exception as exc:
        logger.info("[DataService] fetch_indicator_series failed for %s: %s", symbol, exc)
        return None


def fetch_earnings_history(symbol: str) -> list[dict[str, Any]] | None:
    """Fetch EPS estimate vs actual history from yfinance (Phase G2)."""
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        eh = getattr(ticker, "earnings_history", None)
        if eh is None or (hasattr(eh, "empty") and eh.empty):
            return None

        # yfinance returns a DataFrame with columns like
        # 'epsEstimate', 'epsActual', 'epsDifference', 'surprisePercent'
        import pandas as pd
        if isinstance(eh, pd.DataFrame):
            entries: list[dict[str, Any]] = []
            for idx, row in eh.iterrows():
                quarter_str = str(idx) if idx is not None else ""
                if hasattr(idx, "strftime"):
                    quarter_str = idx.strftime("%Y-%m-%d")
                entries.append({
                    "quarter": quarter_str,
                    "eps_estimate": safe_float(row.get("epsEstimate")),
                    "eps_actual": safe_float(row.get("epsActual")),
                    "surprise_pct": safe_float(row.get("surprisePercent")),
                })
            return entries if entries else None
        return None
    except Exception as exc:
        logger.info("[DataService] fetch_earnings_history failed for %s: %s", symbol, exc)
        return None


def fetch_analyst_targets(symbol: str) -> dict[str, Any] | None:
    """Fetch analyst price targets from yfinance (Phase G2)."""
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        targets = getattr(ticker, "analyst_price_targets", None)
        if targets is None:
            return None

        import pandas as pd
        if isinstance(targets, pd.DataFrame):
            # Some yfinance versions return a DataFrame, others a dict
            if targets.empty:
                return None
            row = targets.iloc[0] if len(targets) > 0 else {}
            result = {
                "low": safe_float(row.get("low")),
                "current": safe_float(row.get("current")),
                "mean": safe_float(row.get("mean")),
                "median": safe_float(row.get("median")),
                "high": safe_float(row.get("high")),
            }
        elif isinstance(targets, dict):
            result = {
                "low": safe_float(targets.get("low")),
                "current": safe_float(targets.get("current")),
                "mean": safe_float(targets.get("mean")),
                "median": safe_float(targets.get("median")),
                "high": safe_float(targets.get("high")),
            }
        else:
            return None

        if all(v is None for v in result.values()):
            return None
        return result
    except Exception as exc:
        logger.info("[DataService] fetch_analyst_targets failed for %s: %s", symbol, exc)
        return None


def fetch_recommendations(symbol: str) -> dict[str, Any] | None:
    """Fetch analyst recommendation summary from yfinance (Phase G2)."""
    try:
        import yfinance as yf

        ticker = yf.Ticker(symbol)
        rec = getattr(ticker, "recommendations_summary", None)
        if rec is None:
            return None

        import pandas as pd
        if isinstance(rec, pd.DataFrame) and not rec.empty:
            # Take the most recent period row
            row = rec.iloc[0]
            result = {
                "strong_buy": int(row.get("strongBuy", 0)),
                "buy": int(row.get("buy", 0)),
                "hold": int(row.get("hold", 0)),
                "sell": int(row.get("sell", 0)),
                "strong_sell": int(row.get("strongSell", 0)),
            }
            if sum(result.values()) == 0:
                return None
            return result
        return None
    except Exception as exc:
        logger.info("[DataService] fetch_recommendations failed for %s: %s", symbol, exc)
        return None


class DashboardDataService:
    """Lightweight wrapper with cache-aware helper methods."""

    def __init__(self) -> None:
        self.cache = dashboard_cache

    def get_market_chart(self, symbol: str, period: str = "1y", interval: str = "1d", use_cache: bool = True) -> list[dict[str, Any]]:
        cache_key = f"market_chart:{period}:{interval}"
        if use_cache:
            cached = self.cache.get(symbol, cache_key)
            if cached is not None:
                return cached
        data = fetch_market_chart(symbol, period, interval)
        self.cache.set(symbol, cache_key, data, ttl=self.cache.TTL_CHARTS)
        return data

    def get_snapshot(self, symbol: str, asset_type: str, use_cache: bool = True) -> dict[str, Any]:
        if use_cache:
            cached = self.cache.get(symbol, "snapshot")
            if cached is not None:
                return cached
        data = fetch_snapshot(symbol, asset_type)
        self.cache.set(symbol, "snapshot", data, ttl=self.cache.TTL_SNAPSHOT)
        return data

    def get_revenue_trend(self, symbol: str, use_cache: bool = True) -> list[dict[str, Any]]:
        if use_cache:
            cached = self.cache.get(symbol, "revenue_trend")
            if cached is not None:
                return cached
        data = fetch_revenue_trend(symbol)
        self.cache.set(symbol, "revenue_trend", data, ttl=self.cache.TTL_CHARTS)
        return data

    def get_segment_mix(self, symbol: str, use_cache: bool = True) -> list[dict[str, Any]]:
        if use_cache:
            cached = self.cache.get(symbol, "segment_mix")
            if cached is not None:
                return cached
        data = fetch_segment_mix(symbol)
        self.cache.set(symbol, "segment_mix", data, ttl=self.cache.TTL_SEGMENT_MIX)
        return data

    def get_news(self, symbol: str, limit: int = 20, use_cache: bool = True) -> dict[str, Any]:
        if use_cache:
            cached = self.cache.get(symbol, "news")
            if cached is not None:
                return cached
        data = fetch_news(symbol, limit)
        self.cache.set(symbol, "news", data, ttl=self.cache.TTL_NEWS)
        return data

    def get_macro_snapshot(self, symbol: str, use_cache: bool = True) -> dict[str, Any]:
        if use_cache:
            cached = self.cache.get(symbol, "macro_snapshot")
            if cached is not None:
                return cached
        data = fetch_macro_snapshot()
        self.cache.set(symbol, "macro_snapshot", data, ttl=self.cache.TTL_MACRO)
        return data

    def get_sector_weights(self, symbol: str, asset_type: str, use_cache: bool = True) -> list[dict[str, Any]]:
        if use_cache:
            cached = self.cache.get(symbol, "sector_weights")
            if cached is not None:
                return cached
        data = fetch_sector_weights(symbol, asset_type)
        self.cache.set(symbol, "sector_weights", data, ttl=self.cache.TTL_SECTOR_WEIGHTS)
        return data

    def get_top_constituents(self, symbol: str, asset_type: str, limit: int = 10, use_cache: bool = True) -> list[dict[str, Any]]:
        if use_cache:
            cached = self.cache.get(symbol, "top_constituents")
            if cached is not None:
                return cached
        data = fetch_top_constituents(symbol, asset_type, limit)
        self.cache.set(symbol, "top_constituents", data, ttl=self.cache.TTL_CONSTITUENTS)
        return data

    def get_holdings(self, symbol: str, asset_type: str, limit: int = 50, use_cache: bool = True) -> list[dict[str, Any]]:
        if use_cache:
            cached = self.cache.get(symbol, "holdings")
            if cached is not None:
                return cached
        data = fetch_holdings(symbol, asset_type, limit)
        self.cache.set(symbol, "holdings", data, ttl=self.cache.TTL_HOLDINGS)
        return data

    # ── v2 data methods ────────────────────────────────────────

    def get_valuation(self, symbol: str, use_cache: bool = True) -> dict[str, Any] | None:
        if use_cache:
            cached = self.cache.get(symbol, "valuation")
            if cached is not None:
                return cached
        data = fetch_valuation(symbol)
        if data is not None:
            self.cache.set(symbol, "valuation", data, ttl=self.cache.TTL_VALUATION)
        return data

    def get_financial_statements(self, symbol: str, use_cache: bool = True) -> dict[str, Any] | None:
        if use_cache:
            cached = self.cache.get(symbol, "financials")
            if cached is not None:
                return cached
        data = fetch_financial_statements(symbol)
        if data is not None:
            self.cache.set(symbol, "financials", data, ttl=self.cache.TTL_FINANCIALS)
        return data

    def get_technical_indicators(self, symbol: str, use_cache: bool = True) -> dict[str, Any] | None:
        if use_cache:
            cached = self.cache.get(symbol, "technicals")
            if cached is not None:
                return cached
        data = fetch_technical_indicators(symbol)
        if data is not None:
            self.cache.set(symbol, "technicals", data, ttl=self.cache.TTL_TECHNICALS)
        return data

    # ── Phase G2 data methods ────────────────────────────────────

    def get_indicator_series(self, symbol: str, use_cache: bool = True) -> dict[str, Any] | None:
        if use_cache:
            cached = self.cache.get(symbol, "indicator_series")
            if cached is not None:
                return cached
        data = fetch_indicator_series(symbol)
        if data is not None:
            self.cache.set(symbol, "indicator_series", data, ttl=self.cache.TTL_TECHNICALS)
        return data

    def get_earnings_history(self, symbol: str, use_cache: bool = True) -> list[dict[str, Any]] | None:
        if use_cache:
            cached = self.cache.get(symbol, "earnings_history")
            if cached is not None:
                return cached
        data = fetch_earnings_history(symbol)
        if data is not None:
            self.cache.set(symbol, "earnings_history", data, ttl=self.cache.TTL_EARNINGS)
        return data

    def get_analyst_targets(self, symbol: str, use_cache: bool = True) -> dict[str, Any] | None:
        if use_cache:
            cached = self.cache.get(symbol, "analyst_targets")
            if cached is not None:
                return cached
        data = fetch_analyst_targets(symbol)
        if data is not None:
            self.cache.set(symbol, "analyst_targets", data, ttl=self.cache.TTL_ANALYST)
        return data

    def get_recommendations(self, symbol: str, use_cache: bool = True) -> dict[str, Any] | None:
        if use_cache:
            cached = self.cache.get(symbol, "recommendations")
            if cached is not None:
                return cached
        data = fetch_recommendations(symbol)
        if data is not None:
            self.cache.set(symbol, "recommendations", data, ttl=self.cache.TTL_ANALYST)
        return data


dashboard_data_service = DashboardDataService()

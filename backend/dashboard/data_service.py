"""Dashboard data service helpers.

This module consolidates market/snapshot/news data retrieval and lightweight
normalization for Dashboard API responses.
"""

from __future__ import annotations

import logging
import math
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

        if isinstance(ts, (int, float)):
            try:
                ts = datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
            except Exception:
                ts = ""
        elif not isinstance(ts, str):
            ts = str(ts) if ts else ""

        return {
            "title": str(title).strip(),
            "url": str(url).strip(),
            "source": str(source).strip(),
            "ts": ts,
            "summary": str(summary).strip(),
        }

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


def fetch_valuation(symbol: str) -> dict[str, Any] | None:
    """Fetch valuation metrics from yfinance Ticker.info.

    Returns a dict matching the ValuationData schema fields, or None on
    failure.
    """
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
        # Return None if every field is empty
        if all(v is None for v in result.values()):
            return None
        return result
    except Exception as exc:
        logger.info("[DataService] fetch_valuation failed for %s: %s", symbol, exc)
        return None


def fetch_financial_statements(symbol: str, periods: int = 8) -> dict[str, Any] | None:
    """Fetch quarterly financial statements from yfinance.

    Returns a dict matching the FinancialStatement schema, or None on
    failure.
    """
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
        return result
    except Exception as exc:
        logger.info("[DataService] fetch_financial_statements failed for %s: %s", symbol, exc)
        return None


def fetch_technical_indicators(symbol: str) -> dict[str, Any] | None:
    """Compute technical indicators for *symbol*.

    Fetches 1-year daily OHLCV via yfinance and delegates to
    :func:`backend.tools.technical.compute_technical_indicators`.
    """
    try:
        import yfinance as yf
        from backend.tools.technical import compute_technical_indicators

        hist = yf.Ticker(symbol).history(period="1y", interval="1d")
        if hist is None or hist.empty:
            return None

        result = compute_technical_indicators(hist)
        return result if result else None
    except Exception as exc:
        logger.info("[DataService] fetch_technical_indicators failed for %s: %s", symbol, exc)
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


dashboard_data_service = DashboardDataService()

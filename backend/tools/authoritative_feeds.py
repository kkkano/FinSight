from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import quote_plus, urlparse

from .http import _http_get

_AUTHORITATIVE_DOMAINS = frozenset({
    "reuters.com",
    "bloomberg.com",
    "wsj.com",
    "ft.com",
    "cnbc.com",
    "finance.yahoo.com",
})

_GLOBAL_FEEDS = (
    ("bloomberg", "https://feeds.bloomberg.com/markets/news.rss"),
    ("wsj", "https://feeds.a.dj.com/rss/RSSMarketsMain.xml"),
    ("cnbc", "https://www.cnbc.com/id/100003114/device/rss/rss.html"),
    ("ft", "https://www.ft.com/?format=rss"),
)

_REQUEST_TIMEOUT = int(os.getenv("AUTHORITATIVE_FEED_TIMEOUT", "10"))
_MAX_SOURCES = int(os.getenv("AUTHORITATIVE_FEED_MAX_SOURCES", "3"))


def _safe_iso8601(value: str) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return raw


def _normalize_domain(url: str) -> str:
    try:
        return urlparse(str(url or "").strip().lower()).netloc.lstrip("www.")
    except Exception:
        return ""


def _is_authoritative_domain(domain: str) -> bool:
    host = str(domain or "").strip().lower().lstrip("www.")
    if not host:
        return False
    return any(host == d or host.endswith(f".{d}") for d in _AUTHORITATIVE_DOMAINS)


def _query_tokens(query: str) -> list[str]:
    raw = str(query or "").strip()
    if not raw:
        return []
    # Keep ticker-like and topical tokens; drop very short words.
    tokens = [
        token.lower()
        for token in re.findall(r"[A-Za-z][A-Za-z0-9\.\-]{1,}|[\u4e00-\u9fff]{2,}", raw)
    ]
    stopwords = {
        "report", "analysis", "deep", "news", "today", "latest", "company", "stock",
        "研报", "深度", "分析", "新闻", "影响", "公司", "股票",
    }
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in seen or token in stopwords:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped[:8]


def _extract_tickers(query: str) -> list[str]:
    raw = str(query or "").upper()
    if not raw:
        return []
    tickers = [t for t in re.findall(r"\b[A-Z]{1,5}(?:\.[A-Z]{1,2})?\b", raw) if len(t) <= 8]
    uniq: list[str] = []
    seen: set[str] = set()
    for ticker in tickers:
        if ticker in seen:
            continue
        seen.add(ticker)
        uniq.append(ticker)
    return uniq[:2]


def _parse_feed_items(feed_name: str, xml_text: str) -> list[dict[str, Any]]:
    if not xml_text:
        return []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return []

    rows: list[dict[str, Any]] = []
    for item in root.iter("item"):
        link = str(item.findtext("link") or "").strip()
        if not link:
            continue
        domain = _normalize_domain(link)
        source = str(item.findtext("source") or "").strip() or feed_name
        row = {
            "title": str(item.findtext("title") or "").strip(),
            "url": link,
            "source": source,
            "published_date": _safe_iso8601(item.findtext("pubDate") or ""),
            "domain": domain,
            "is_authoritative": _is_authoritative_domain(domain),
            "snippet": str(item.findtext("description") or "").strip(),
        }
        rows.append(row)
    return rows


def _fetch_feed(url: str) -> str:
    try:
        resp = _http_get(
            url,
            timeout=_REQUEST_TIMEOUT,
            headers={"User-Agent": "FinSight/1.0 (+https://github.com/finsight)"},
        )
        if getattr(resp, "status_code", 0) != 200:
            return ""
        return str(getattr(resp, "text", "") or "")
    except Exception:
        return ""


def _matches_query(item: dict[str, Any], tokens: list[str]) -> bool:
    if not tokens:
        return True
    haystack = " ".join([
        str(item.get("title") or ""),
        str(item.get("snippet") or ""),
        str(item.get("url") or ""),
    ]).lower()
    return any(token in haystack for token in tokens)


def search_authoritative_feeds(
    query: str,
    *,
    max_results: int = 8,
    authoritative_only: bool = True,
) -> list[dict[str, Any]]:
    """Search free publisher RSS feeds and return normalized result rows.

    This function is best-effort and never raises.
    """
    tokens = _query_tokens(query)
    tickers = _extract_tickers(query)

    feed_urls: list[tuple[str, str]] = []
    for ticker in tickers:
        feed_urls.append(
            (
                "finance.yahoo.com",
                "https://feeds.finance.yahoo.com/rss/2.0/headline?s="
                f"{quote_plus(ticker)}&region=US&lang=en-US",
            )
        )
    feed_urls.extend(_GLOBAL_FEEDS[: max(1, _MAX_SOURCES)])

    collected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for feed_name, feed_url in feed_urls:
        xml_text = _fetch_feed(feed_url)
        if not xml_text:
            continue
        for item in _parse_feed_items(feed_name, xml_text):
            url = str(item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            if authoritative_only and not bool(item.get("is_authoritative")):
                continue
            if not _matches_query(item, tokens):
                continue
            collected.append(item)
            if len(collected) >= max_results:
                return collected

    return collected


def get_authoritative_media_news(
    query: str,
    *,
    max_results: int = 8,
    authoritative_only: bool = True,
) -> dict[str, Any]:
    """
    Structured wrapper for planner/tool pipeline.
    Returns normalized payload and never raises.
    """
    query_text = str(query or "").strip()
    limit = max(1, min(int(max_results or 8), 20))
    if not query_text:
        return {
            "query": query_text,
            "source": "authoritative_feeds",
            "articles": [],
            "error": "query_required",
        }
    try:
        rows = search_authoritative_feeds(
            query_text,
            max_results=limit,
            authoritative_only=bool(authoritative_only),
        )
        return {
            "query": query_text,
            "source": "authoritative_feeds",
            "articles": rows,
            "count": len(rows),
            "error": None,
        }
    except Exception as exc:  # pragma: no cover - best effort
        return {
            "query": query_text,
            "source": "authoritative_feeds",
            "articles": [],
            "error": f"fetch_failed:{exc.__class__.__name__}",
        }


__all__ = [
    "search_authoritative_feeds",
    "get_authoritative_media_news",
]

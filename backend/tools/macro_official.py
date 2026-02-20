from __future__ import annotations

import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse

from .http import _http_get

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT = int(os.getenv("MACRO_OFFICIAL_TIMEOUT", "12"))
_MAX_SOURCES = int(os.getenv("MACRO_OFFICIAL_MAX_SOURCES", "5"))
_USER_AGENT = os.getenv("MACRO_OFFICIAL_USER_AGENT", "FinSight/1.0")

_OFFICIAL_FEEDS: tuple[tuple[str, str, str], ...] = (
    ("federal_reserve", "Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("federal_reserve", "Federal Reserve", "https://www.federalreserve.gov/feeds/press_monetary.xml"),
    ("bls", "BLS", "https://www.bls.gov/feed/bls_latest.rss"),
    ("bls", "BLS", "https://www.bls.gov/feed/bls_news_release.rss"),
    ("bea", "BEA", "https://www.bea.gov/rss/bea_latest.xml"),
)

_OFFICIAL_DOMAINS = frozenset(
    {
        "federalreserve.gov",
        "bls.gov",
        "bea.gov",
    }
)

_DEFAULT_QUERY_HINT = "federal reserve bls bea inflation cpi payroll gdp rates"


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


def _is_official_domain(domain: str) -> bool:
    host = str(domain or "").strip().lower().lstrip("www.")
    if not host:
        return False
    return any(host == allowed or host.endswith(f".{allowed}") for allowed in _OFFICIAL_DOMAINS)


def _query_tokens(query: str) -> list[str]:
    text = str(query or "").strip().lower()
    if not text:
        text = _DEFAULT_QUERY_HINT
    tokens = re.findall(r"[a-z0-9\.\-]{3,}", text)
    stopwords = {
        "latest",
        "report",
        "analysis",
        "today",
        "update",
        "impact",
        "macro",
        "economy",
    }
    deduped: list[str] = []
    seen: set[str] = set()
    for token in tokens:
        if token in stopwords or token in seen:
            continue
        seen.add(token)
        deduped.append(token)
    return deduped[:10]


def _matches_query(item: dict[str, Any], tokens: list[str]) -> bool:
    if not tokens:
        return True
    haystack = " ".join(
        [
            str(item.get("title") or ""),
            str(item.get("snippet") or ""),
            str(item.get("url") or ""),
        ]
    ).lower()
    return any(token in haystack for token in tokens)


def _fetch_feed(url: str) -> str:
    try:
        resp = _http_get(
            url,
            timeout=_REQUEST_TIMEOUT,
            headers={"User-Agent": _USER_AGENT},
        )
        if getattr(resp, "status_code", 0) != 200:
            return ""
        return str(getattr(resp, "text", "") or "")
    except Exception:
        return ""


def _parse_rss_items(feed_key: str, source_name: str, xml_text: str) -> list[dict[str, Any]]:
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
        rows.append(
            {
                "title": str(item.findtext("title") or "").strip(),
                "url": link,
                "snippet": str(item.findtext("description") or "").strip(),
                "published_date": _safe_iso8601(item.findtext("pubDate") or ""),
                "source": source_name,
                "source_key": feed_key,
                "domain": domain,
                "is_official": _is_official_domain(domain),
                "type": "macro_release",
            }
        )

    for entry in root.findall(".//{*}entry"):
        title = str(entry.findtext("{*}title") or "").strip()
        updated = str(entry.findtext("{*}updated") or entry.findtext("{*}published") or "").strip()
        summary = str(entry.findtext("{*}summary") or entry.findtext("{*}content") or "").strip()
        link = ""
        for link_node in entry.findall("{*}link"):
            href = str(link_node.attrib.get("href") or "").strip()
            if href:
                link = href
                break
        if not link:
            continue
        domain = _normalize_domain(link)
        rows.append(
            {
                "title": title,
                "url": link,
                "snippet": summary,
                "published_date": _safe_iso8601(updated),
                "source": source_name,
                "source_key": feed_key,
                "domain": domain,
                "is_official": _is_official_domain(domain),
                "type": "macro_release",
            }
        )

    return rows


def search_official_macro_releases(query: str, *, max_results: int = 10) -> list[dict[str, Any]]:
    """Best-effort official macro release discovery from BLS/BEA/FED feeds."""
    limit = max(1, min(int(max_results or 10), 30))
    tokens = _query_tokens(query)
    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for feed_key, source_name, feed_url in _OFFICIAL_FEEDS[: max(1, _MAX_SOURCES)]:
        xml_text = _fetch_feed(feed_url)
        if not xml_text:
            continue
        for item in _parse_rss_items(feed_key, source_name, xml_text):
            url = str(item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            if not bool(item.get("is_official")):
                continue
            if not _matches_query(item, tokens):
                continue
            rows.append(item)
            if len(rows) >= limit:
                return rows
    return rows


def get_official_macro_releases(query: str = "", max_results: int = 10) -> dict[str, Any]:
    """Structured wrapper for macro official source collection. Never raises."""
    query_text = str(query or "").strip()
    limit = max(1, min(int(max_results or 10), 30))
    try:
        rows = search_official_macro_releases(query_text, max_results=limit)
        sources = sorted({str(row.get("source") or "").strip() for row in rows if row.get("source")})
        return {
            "query": query_text,
            "source": "macro_official_feeds",
            "releases": rows,
            "count": len(rows),
            "sources": sources,
            "error": None,
        }
    except Exception as exc:  # pragma: no cover - best effort
        logger.info("[MacroOfficial] fetch failed: %s", exc)
        return {
            "query": query_text,
            "source": "macro_official_feeds",
            "releases": [],
            "count": 0,
            "sources": [],
            "error": f"fetch_failed:{exc.__class__.__name__}",
        }


__all__ = ["search_official_macro_releases", "get_official_macro_releases"]

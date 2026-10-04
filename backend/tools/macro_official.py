from __future__ import annotations

import logging
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .http import _http_get
from .web import fetch_url_document

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
_FED_OFFICIAL_FALLBACKS: tuple[dict[str, Any], ...] = (
    {
        "title": "Federal Reserve official press releases index",
        "url": "https://www.federalreserve.gov/newsevents/pressreleases.htm",
        "snippet": "Official Federal Reserve press releases page. Use when RSS feeds return no matching item.",
        "published_date": None,
        "source": "Federal Reserve",
        "source_key": "federal_reserve",
        "domain": "federalreserve.gov",
        "is_official": True,
        "type": "macro_release",
        "fallback": True,
    },
    {
        "title": "Federal Reserve monetary policy releases",
        "url": "https://www.federalreserve.gov/newsevents/pressreleases/monetary.htm",
        "snippet": "Official Federal Reserve monetary policy releases page for FOMC and rate-related updates.",
        "published_date": None,
        "source": "Federal Reserve",
        "source_key": "federal_reserve",
        "domain": "federalreserve.gov",
        "is_official": True,
        "type": "macro_release",
        "fallback": True,
    },
)


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


def _is_fed_query(query: str) -> bool:
    text = str(query or "").lower()
    if not text:
        return False
    return any(
        marker in text
        for marker in (
            "fed",
            "fomc",
            "federal reserve",
            "\u7f8e\u8054\u50a8",
            "\u806f\u5132",
        )
    )


def _fallback_rows_for_query(query: str, *, limit: int) -> list[dict[str, Any]]:
    if not _is_fed_query(query):
        return []
    return [dict(row) for row in _FED_OFFICIAL_FALLBACKS[: max(1, limit)]]


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


def _read_bls_employment_release(row: dict[str, Any]) -> dict[str, Any]:
    updated = {**row, "content_read": False, "employment_report": None}
    url = str(row.get("url") or "")
    document = fetch_url_document(url, max_length=16000)
    if not document or _normalize_domain(str(document.get("final_url") or url)) != "bls.gov":
        return updated
    body = str(document.get("content") or "")
    if re.search(r"captcha|access denied|just a moment|security verification", body, re.I):
        return updated
    month = re.search(r"THE\s+EMPLOYMENT\s+SITUATION\s*[-:–—]*\s*([A-Za-z]+)\s+(20\d{2})", body, re.I)
    if not month or len(body) < 300:
        return updated
    try:
        report_month = datetime.strptime(f"{month.group(1)} {month.group(2)}", "%B %Y").strftime("%Y-%m")
    except ValueError:
        return updated
    release = re.search(r"embargoed until\s+(\d{1,2}):(\d{2})\s*([ap])\.?m\.?\s*\((?:ET|EDT|EST)\)"
        r"\s*(?:[A-Za-z]+,?\s+)?([A-Za-z]+\s+\d{1,2},\s+20\d{2})", " ".join(body[:1800].split()), re.I)
    published_at = None
    if release:
        try:
            point = datetime.strptime(release.group(4), "%B %d, %Y")
            hour = int(release.group(1)) % 12 + (12 if release.group(3).lower() == "p" else 0)
            published_at = point.replace(hour=hour, minute=int(release.group(2)), tzinfo=ZoneInfo("America/New_York")).astimezone(timezone.utc).isoformat()
        except ValueError:
            pass
    payroll = re.search(r"total\s+nonfarm\s+payroll\s+employment\s+(increased|rose|grew|declined|fell|decreased)\s+by\s+([\d,]+)", body, re.I)
    unemployment = re.search(r"unemployment\s+rate\b[^.;]{0,90}?\b(?:at|to|was)\s+(\d+(?:\.\d+)?)\s*(?:percent|%)", body, re.I)
    change = (int(payroll.group(2).replace(",", "")) * (-1 if payroll.group(1).lower() in {"declined", "fell", "decreased"} else 1)) if payroll else None
    report = {"report_month": report_month, "published_at": published_at,
        "nonfarm_payroll_change": change, "unemployment": float(unemployment.group(1)) if unemployment else None,
        "source": "BLS", "source_url": document.get("final_url") or url,
        "nonfarm_unit": "persons", "unemployment_unit": "percent", "content_read": True,
        "missing_metrics": [key for key, value in {"published_at": published_at, "nonfarm_payroll_change": change,
            "unemployment": float(unemployment.group(1)) if unemployment else None}.items() if value is None]}
    updated.update(content_read=True, body=body[:16000], snippet=body[:16000], body_truncated=len(body) > 16000,
        feed_published_at=row.get("published_date"), published_date=published_at,
        published_at=published_at, employment_report=report, source_url=report["source_url"],
        verification="official_body_read", structured_data={"body": body[:16000], "employment_report": report})
    return updated


def official_macro_query(query: str, indicators: list[str] | None = None) -> str:
    """合同指标补充官方检索主题，重复构造保持相同缓存键。"""
    text = str(query or "").strip()
    employment = bool({"nonfarm_payroll_change", "unemployment"}.intersection(indicators or []))
    if employment and "employment situation" not in text.lower():
        return f"{text} employment situation".strip()
    return text


def get_official_macro_releases(query: str = "", max_results: int = 10, include_content: bool = False) -> dict[str, Any]:
    """Structured wrapper for macro official source collection. Never raises."""
    query_text = str(query or "").strip()
    limit = max(1, min(int(max_results or 10), 30))
    try:
        employment = include_content and bool(re.search(r"employment|payroll|nonfarm|就业|非农|劳动力", query_text, re.I))
        rows = search_official_macro_releases("employment situation empsit" if employment else query_text, max_results=limit)
        if not rows:
            rows = _fallback_rows_for_query(query_text, limit=limit)
        if employment:
            rows = sorted(rows, key=lambda item: str(item.get("published_date") or ""), reverse=True)
            read = False
            for index, row in enumerate(rows):
                row["content_read"] = False
                url = str(row.get("url") or "")
                if not read and _normalize_domain(url) == "bls.gov" and re.search(r"/news\.release/(?:archives/)?empsit", url, re.I):
                    rows[index] = _read_bls_employment_release(row)
                    read = True
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


__all__ = ["search_official_macro_releases", "get_official_macro_releases", "official_macro_query"]

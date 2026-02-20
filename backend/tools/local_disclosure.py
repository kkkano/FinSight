from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

from .search import search

logger = logging.getLogger(__name__)

_LOCAL_DISCLOSURE_DOMAINS: dict[str, str] = {
    "cninfo.com.cn": "CN",
    "sse.com.cn": "CN",
    "szse.cn": "CN",
    "hkexnews.hk": "HK",
    "hkex.com.hk": "HK",
}

_URL_RE = re.compile(r"https?://[^\s\]\)\"'>]+", flags=re.IGNORECASE)


def _detect_market(ticker: str) -> str:
    raw = str(ticker or "").strip().upper()
    if raw.endswith((".SS", ".SZ", ".BJ")):
        return "CN"
    if raw.endswith(".HK"):
        return "HK"
    return "US"


def _normalize_domain(url: str) -> str:
    try:
        return urlparse(str(url or "").strip().lower()).netloc.lstrip("www.")
    except Exception:
        return ""


def _parse_search_text(raw: str) -> list[dict[str, str]]:
    text = str(raw or "")
    if not text.strip():
        return []

    rows: list[dict[str, str]] = []
    current: dict[str, str] = {"title": "", "snippet": "", "url": ""}

    def _flush() -> None:
        if current.get("url"):
            rows.append(dict(current))
        current["title"] = ""
        current["snippet"] = ""
        current["url"] = ""

    for raw_line in text.splitlines():
        line = str(raw_line or "").strip()
        if not line:
            continue

        md_match = re.search(r"\[([^\]]+)\]\((https?://[^\)]+)\)", line)
        if md_match:
            current["title"] = current.get("title") or md_match.group(1).strip()
            current["url"] = md_match.group(2).strip()
            if not current.get("snippet"):
                stripped = re.sub(r"\[[^\]]+\]\(https?://[^\)]+\)", "", line).strip(" -:;")
                current["snippet"] = stripped
            _flush()
            continue

        if re.match(r"^\d+\.\s*", line):
            if current.get("url"):
                _flush()
            current["title"] = re.sub(r"^\d+\.\s*", "", line).strip()
            continue

        urls = _URL_RE.findall(line)
        if urls:
            current["url"] = current.get("url") or urls[0].strip()
            title_guess = line
            for found in urls:
                title_guess = title_guess.replace(found, " ")
            title_guess = title_guess.strip(" -:;")
            if title_guess and not current.get("title"):
                current["title"] = title_guess
            _flush()
            continue

        if not current.get("snippet"):
            current["snippet"] = line

    if current.get("url"):
        _flush()

    deduped: list[dict[str, str]] = []
    seen_urls: set[str] = set()
    for row in rows:
        url = str(row.get("url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        deduped.append(row)
    return deduped


def _infer_form(text: str, market: str) -> str:
    lowered = str(text or "").lower()
    if market == "CN":
        if any(token in lowered for token in ("年报", "annual report")):
            return "annual_report"
        if any(token in lowered for token in ("季报", "quarterly", "q1", "q2", "q3", "中报", "半年报")):
            return "quarterly_report"
        return "announcement"

    if market == "HK":
        if any(token in lowered for token in ("annual report", "年报")):
            return "annual_report"
        if any(token in lowered for token in ("interim report", "中期报告", "quarterly", "季报")):
            return "interim_report"
        return "announcement"

    return "filing"


def _extract_date(text: str) -> str | None:
    raw = str(text or "")
    if not raw:
        return None

    iso_match = re.search(r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})", raw)
    if iso_match:
        y, m, d = iso_match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"

    cn_match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", raw)
    if cn_match:
        y, m, d = cn_match.groups()
        return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"

    return None


def _build_queries(ticker: str, market: str) -> list[str]:
    ticker_norm = str(ticker or "").strip().upper()
    if market == "CN":
        return [
            f"site:cninfo.com.cn {ticker_norm} 年报 公告",
            f"site:sse.com.cn {ticker_norm} 公告",
            f"site:szse.cn {ticker_norm} 公告",
        ]
    if market == "HK":
        return [
            f"site:hkexnews.hk {ticker_norm} annual report",
            f"site:hkexnews.hk {ticker_norm} interim report",
            f"site:hkex.com.hk {ticker_norm} announcement",
        ]
    return []


def get_local_market_filings(ticker: str, limit: int = 8) -> dict[str, Any]:
    """Fetch CN/HK local disclosure links via free search sources."""
    ticker_norm = str(ticker or "").strip().upper()
    capped_limit = max(1, min(int(limit or 8), 20))
    market = _detect_market(ticker_norm)

    if not ticker_norm:
        return {
            "ticker": ticker_norm,
            "market": market,
            "source": "local_disclosure_free",
            "filings": [],
            "count": 0,
            "error": "ticker_required",
        }

    if market not in {"CN", "HK"}:
        return {
            "ticker": ticker_norm,
            "market": market,
            "source": "local_disclosure_free",
            "filings": [],
            "count": 0,
            "error": "market_not_supported",
            "message": "Only CN/HK markets are supported for local disclosure lookup.",
        }

    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for query in _build_queries(ticker_norm, market):
        try:
            raw = search(query)
        except Exception as exc:
            logger.info("[LocalDisclosure] Search failed for %s: %s", query, exc)
            continue

        parsed = _parse_search_text(raw)
        for item in parsed:
            url = str(item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            domain = _normalize_domain(url)
            domain_market = _LOCAL_DISCLOSURE_DOMAINS.get(domain)
            if domain_market is None:
                matched = False
                for known_domain, known_market in _LOCAL_DISCLOSURE_DOMAINS.items():
                    if domain == known_domain or domain.endswith(f".{known_domain}"):
                        domain_market = known_market
                        matched = True
                        break
                if not matched:
                    continue

            if market != domain_market:
                continue

            title = str(item.get("title") or "").strip()
            snippet = str(item.get("snippet") or "").strip()
            joined_text = f"{title} {snippet} {url}"

            seen_urls.add(url)
            rows.append(
                {
                    "title": title or f"{ticker_norm} local filing",
                    "form": _infer_form(joined_text, market),
                    "filing_url": url,
                    "filing_date": _extract_date(joined_text),
                    "primary_doc_description": snippet or title,
                    "source": domain,
                    "market": market,
                    "confidence": 0.78,
                }
            )
            if len(rows) >= capped_limit:
                break
        if len(rows) >= capped_limit:
            break

    return {
        "ticker": ticker_norm,
        "market": market,
        "source": "local_disclosure_free",
        "filings": rows,
        "count": len(rows),
        "error": None,
    }


__all__ = ["get_local_market_filings"]

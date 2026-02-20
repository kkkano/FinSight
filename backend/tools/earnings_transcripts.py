from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

from .search import search

logger = logging.getLogger(__name__)

_TRANSCRIPT_DOMAIN_HINTS = (
    "fool.com",
    "seekingalpha.com",
    "finance.yahoo.com",
    "nasdaq.com",
    "marketbeat.com",
    "investing.com",
    "thestreet.com",
)

_TRANSCRIPT_QUERY_TEMPLATES = (
    "{ticker} earnings call transcript",
    "{ticker} quarterly earnings transcript",
    "{ticker} conference call transcript",
    "{ticker} prepared remarks transcript",
)

_URL_RE = re.compile(r"https?://[^\s\]\)\"'>]+", flags=re.IGNORECASE)


def _normalize_domain(url: str) -> str:
    try:
        return urlparse(str(url or "").strip().lower()).netloc.lstrip("www.")
    except Exception:
        return ""


def _normalize_ticker(ticker: str) -> str:
    return str(ticker or "").strip().upper()


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


def _looks_like_transcript(title: str, snippet: str, url: str) -> bool:
    text = " ".join((str(title or ""), str(snippet or ""), str(url or ""))).lower()
    if any(token in text for token in ("transcript", "earnings call", "conference call", "prepared remarks", "q&a")):
        return True
    return False


def _is_transcript_domain(domain: str) -> bool:
    host = str(domain or "").strip().lower()
    if not host:
        return False
    return any(host == hint or host.endswith(f".{hint}") for hint in _TRANSCRIPT_DOMAIN_HINTS)


def _maybe_enrich_snippet(url: str, snippet: str) -> str:
    use_jina = str(os.getenv("TRANSCRIPT_USE_JINA", "true")).strip().lower() in {"1", "true", "yes", "on"}
    if not use_jina:
        return snippet
    if not str(url or "").startswith(("http://", "https://")):
        return snippet
    text = str(snippet or "").strip()
    if len(text) >= 120:
        return text

    try:
        from .jina_reader import fetch_via_jina
    except Exception:
        return text

    try:
        enriched = fetch_via_jina(url)
    except Exception:
        return text
    if enriched and len(enriched) > len(text):
        return str(enriched)[:800]
    return text


def get_earnings_call_transcripts(ticker: str, limit: int = 6) -> dict[str, Any]:
    """Best-effort free transcript discovery via public web sources."""
    ticker_norm = _normalize_ticker(ticker)
    capped_limit = max(1, min(int(limit or 6), 20))
    if not ticker_norm:
        return {
            "ticker": ticker_norm,
            "source": "earnings_transcripts_free",
            "transcripts": [],
            "count": 0,
            "error": "ticker_required",
        }

    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()

    for template in _TRANSCRIPT_QUERY_TEMPLATES:
        query = template.format(ticker=ticker_norm)
        try:
            raw = search(query)
        except Exception as exc:
            logger.info("[Transcript] Search failed for %s: %s", query, exc)
            continue

        parsed = _parse_search_text(raw)
        for item in parsed:
            url = str(item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            domain = _normalize_domain(url)
            title = str(item.get("title") or "").strip()
            snippet = str(item.get("snippet") or "").strip()

            if not (_is_transcript_domain(domain) or _looks_like_transcript(title, snippet, url)):
                continue

            if not _looks_like_transcript(title, snippet, url):
                # Domain matches but content signal is weak; keep only obviously transcript-like URLs.
                if "transcript" not in url.lower() and "earnings" not in url.lower():
                    continue

            seen_urls.add(url)
            snippet = _maybe_enrich_snippet(url, snippet or title)
            rows.append(
                {
                    "title": title or f"{ticker_norm} earnings call transcript",
                    "url": url,
                    "snippet": snippet,
                    "source": domain or "transcript_search",
                    "published_date": None,
                    "domain": domain,
                    "type": "transcript",
                    "confidence": 0.78,
                }
            )
            if len(rows) >= capped_limit:
                break
        if len(rows) >= capped_limit:
            break

    return {
        "ticker": ticker_norm,
        "source": "earnings_transcripts_free",
        "transcripts": rows,
        "count": len(rows),
        "error": None,
    }


__all__ = ["get_earnings_call_transcripts"]

from __future__ import annotations

import logging
import os
import re
from typing import Any
from urllib.parse import urlparse

from .search import search

logger = logging.getLogger(__name__)

_US_TRANSCRIPT_DOMAIN_HINTS = (
    "fool.com",
    "seekingalpha.com",
    "finance.yahoo.com",
    "nasdaq.com",
    "marketbeat.com",
    "investing.com",
    "thestreet.com",
)

_CN_TRANSCRIPT_DOMAIN_HINTS = (
    "cninfo.com.cn",
    "eastmoney.com",
    "10jqka.com.cn",
    "finance.sina.com.cn",
    "stcn.com",
)

_HK_TRANSCRIPT_DOMAIN_HINTS = (
    "hkexnews.hk",
    "disclosure.hkex.com.hk",
    "irasia.com",
    "aastocks.com",
    "etnet.com.hk",
)

_TRANSCRIPT_DOMAIN_HINTS = _US_TRANSCRIPT_DOMAIN_HINTS + _CN_TRANSCRIPT_DOMAIN_HINTS + _HK_TRANSCRIPT_DOMAIN_HINTS

_TRANSCRIPT_QUERY_TEMPLATES_BY_MARKET = {
    "US": (
        "{ticker} earnings call transcript",
        "{ticker} quarterly earnings transcript",
        "{ticker} conference call transcript",
        "{ticker} prepared remarks transcript",
    ),
    "CN": (
        "{ticker} 业绩说明会 纪要",
        "{ticker} 电话会议 纪要",
        "{ticker} 投资者关系活动记录表",
        "{ticker} 业绩会 管理层问答",
    ),
    "HK": (
        "{ticker} earnings call transcript",
        "{ticker} results presentation transcript",
        "{ticker} 业绩发布会 纪要",
        "{ticker} investor relations webcast transcript",
    ),
}

_TRANSCRIPT_KEYWORDS = (
    "transcript",
    "earnings call",
    "conference call",
    "prepared remarks",
    "q&a",
    "results presentation",
    "investor relations",
    "webcast",
    "业绩说明会",
    "业绩会",
    "电话会议",
    "电话会",
    "纪要",
    "管理层问答",
    "实录",
    "投资者关系活动记录表",
)

_URL_TRANSCRIPT_HINTS = (
    "transcript",
    "earnings",
    "results",
    "presentation",
    "webcast",
    "conference-call",
    "业绩",
    "纪要",
    "说明会",
    "电话会",
)

_URL_RE = re.compile(r"https?://[^\s\]\)\"'>]+", flags=re.IGNORECASE)


def _normalize_domain(url: str) -> str:
    try:
        return urlparse(str(url or "").strip().lower()).netloc.lstrip("www.")
    except Exception:
        return ""


def _normalize_ticker(ticker: str) -> str:
    return str(ticker or "").strip().upper()


def _infer_market(ticker: str) -> str:
    symbol = _normalize_ticker(ticker)
    if symbol.endswith((".SS", ".SZ", ".BJ")):
        return "CN"
    if symbol.endswith(".HK"):
        return "HK"
    return "US"


def _build_market_queries(ticker_norm: str, market: str) -> list[str]:
    core = ticker_norm.split(".", 1)[0]
    symbols: list[str] = [ticker_norm]
    if core and core != ticker_norm:
        symbols.append(core)
    if market == "HK" and core:
        hk_short = core.lstrip("0")
        if hk_short and hk_short not in symbols:
            symbols.append(hk_short)

    templates = _TRANSCRIPT_QUERY_TEMPLATES_BY_MARKET.get(market) or _TRANSCRIPT_QUERY_TEMPLATES_BY_MARKET["US"]
    queries: list[str] = []
    seen: set[str] = set()
    for template in templates:
        for symbol in symbols[:2]:
            query = template.format(ticker=symbol).strip()
            if not query or query in seen:
                continue
            seen.add(query)
            queries.append(query)
    return queries


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
    return any(token in text for token in _TRANSCRIPT_KEYWORDS)


def _is_transcript_domain(domain: str) -> bool:
    host = str(domain or "").strip().lower()
    if not host:
        return False
    return any(host == hint or host.endswith(f".{hint}") for hint in _TRANSCRIPT_DOMAIN_HINTS)


def _has_url_transcript_hint(url: str) -> bool:
    text = str(url or "").strip().lower()
    if not text:
        return False
    return any(token in text for token in _URL_TRANSCRIPT_HINTS)


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
    market = _infer_market(ticker_norm)
    capped_limit = max(1, min(int(limit or 6), 20))
    if not ticker_norm:
        return {
            "ticker": ticker_norm,
            "market": market,
            "source": "earnings_transcripts_free",
            "transcripts": [],
            "count": 0,
            "error": "ticker_required",
        }

    rows: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    queries = _build_market_queries(ticker_norm, market)

    for query in queries:
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

            looks_like = _looks_like_transcript(title, snippet, url)
            if not (_is_transcript_domain(domain) or looks_like):
                continue
            if not looks_like and not _has_url_transcript_hint(url):
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
        "source": "earnings_transcripts_free",
        "transcripts": rows,
        "count": len(rows),
        "searched_queries": queries,
        "error": None,
    }


__all__ = ["get_earnings_call_transcripts"]

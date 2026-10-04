from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime
from typing import Any
from urllib.parse import urlparse

from .search import search
from .web import fetch_url_document
from .jina_reader import fetch_via_jina
from backend.security.ssrf import is_safe_url

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


def _fetch_transcript_document(url: str) -> dict[str, Any] | None:
    if not is_safe_url(url):
        return None
    document = fetch_url_document(url, max_length=16000)
    if document and document.get("content"):
        return {**document, "retrieval_method": "http_document"}
    if str(os.getenv("TRANSCRIPT_USE_JINA", "true")).strip().lower() not in {"1", "true", "yes", "on"}:
        return None
    body = fetch_via_jina(url, timeout=6)
    return {"content": body, "final_url": url, "retrieval_method": "jina_reader"} if body else None


def _transcript_period(text: str) -> dict[str, Any] | None:
    pattern = r"(?:fiscal\s*)?Q([1-4])\s*(?:FY\s*)?(20\d{2})|(?:FY\s*)?(20\d{2})\s*Q([1-4])"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None
    return {"fiscal_year": int(match.group(2) or match.group(3)),
        "fiscal_quarter": int(match.group(1) or match.group(4)), "label": match.group(), "calendar_aligned": False}


def _transcript_date(text: str) -> str | None:
    matches = re.findall(r"(?:Published\s*(?:Date|Time)?\s*[:：]?\s*|\b)(20\d{2}-\d{2}-\d{2})\b", text)
    if matches:
        try:
            return date.fromisoformat(matches[0]).isoformat()
        except ValueError:
            return None
    match = re.search(r"\b([A-Za-z]{3,9}\s+\d{1,2},?\s+20\d{2})\b", text)
    if match:
        for format_string in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(match.group(1), format_string).date().isoformat()
            except ValueError:
                continue
    return None


def _transcript_sort_key(item: dict[str, Any]) -> tuple[int, int, str]:
    text = f"{item.get('title', '')} {item.get('snippet', '')[:1000]}"
    period = _transcript_period(text) or {}
    return (period.get("fiscal_year", 0), period.get("fiscal_quarter", 0), _transcript_date(text) or "")


def _has_transcript_body(body: str) -> bool:
    return len(body) >= 500 and bool(re.search(
        r"(?:^|\n)\s*(?:\*\*)?(?:operator|prepared remarks|questions?\s*(?:and|&)\s*answers?|"
        r"[A-Z][a-z]+ [A-Z][a-z]+[^\n]{0,50}(?:CEO|CFO|chief|president)|主持人|管理层|董事长|问答)",
        body, re.IGNORECASE))


def _issuer_matches(ticker: str, title: str, snippet: str, url: str) -> bool:
    from backend.config.ticker_mapping import CN_TO_TICKER, COMPANY_MAP

    text = " ".join((title, snippet, url))
    core = ticker.split(".", 1)[0]
    aliases = {name for name, code in {**COMPANY_MAP, **CN_TO_TICKER}.items() if code == ticker}
    if COMPANY_MAP.get(ticker):
        aliases.add(COMPANY_MAP[ticker])
    for name in list(aliases):
        short = name.replace("港股", "")
        aliases.add(short)
        related = CN_TO_TICKER.get(short)
        if related and COMPANY_MAP.get(related):
            aliases.add(COMPANY_MAP[related])
    # 数字代码必须完整匹配，3690 不接受 3696/3697；单字母代码需交易所或括号限定。
    if core.isdigit():
        matches = re.findall(r"(?:HKG\s*[:：]\s*|/hkg/|/stocks/)(\d{3,6})", text, re.IGNORECASE)
        if any(code.lstrip("0") != core.lstrip("0") for code in matches):
            return False
        ticker_match = bool(re.search(r"(?<!\d)0*" + re.escape(core.lstrip("0")) + r"(?!\d)", text))
    else:
        listed_codes = re.findall(r"\b(?:NYSE|NASDAQ)\s*[:：]\s*([A-Z]{1,5})\b", text, re.IGNORECASE)
        if listed_codes and core not in {code.upper() for code in listed_codes}:
            return False
        ticker_match = bool(re.search(r"(?:\b(?:NYSE|NASDAQ)\s*[:：]\s*|\(|\$)" + re.escape(core) + r"\b", text, re.IGNORECASE))
        if len(core) > 1:
            ticker_match = ticker_match or bool(re.search(r"(?<![\w])" + re.escape(core) + r"(?![\w])", text, re.IGNORECASE))
    return ticker_match or any(re.search(r"(?<![A-Za-z])" + re.escape(alias) + r"(?![A-Za-z])", text, re.IGNORECASE) for alias in aliases if alias)


def _blocked_transcript(text: str) -> bool:
    return bool(re.search(r"captcha|performing security verification|verify.{0,25}(?:human|not a bot)|"
        r"just a moment|please register to access|guest registration|sign in to (?:read|continue)|"
        r"subscribe to (?:read|continue)|subscription required|enable javascript and cookies|验证码|订阅后阅读", text, re.IGNORECASE))


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
    rejected: list[dict[str, str]] = []
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
            if not _issuer_matches(ticker_norm, title, snippet, url):
                rejected.append({"url": url, "reason": "issuer_not_verified"})
                continue
            snippet = snippet or title
            if _blocked_transcript(snippet):
                rejected.append({"url": url, "reason": "blocked_content"})
                continue
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
                    "subject": ticker_norm,
                    "content_read": False,
                    "verification": "issuer_verified_discovery",
                    "meta": {"subject": ticker_norm, "content_read": False, "verification": "issuer_verified_discovery"},
                }
            )
            if len(rows) >= min(capped_limit * 3, 18):
                break
        if len(rows) >= min(capped_limit * 3, 18):
            break

    rows.sort(key=_transcript_sort_key, reverse=True)
    selected = rows[:capped_limit]
    kept = []
    for index, row in enumerate(selected):
        row["fiscal_period"] = _transcript_period(row["title"])
        if index < min(capped_limit, 2):
            document = _fetch_transcript_document(row["url"])
            if document:
                body = str(document.get("content") or "")
                if _blocked_transcript(body):
                    rejected.append({"url": row["url"], "reason": "blocked_content"})
                    continue
                header = f"{document.get('title', '')}\n{body[:1500]}"
                if not _issuer_matches(ticker_norm, "", body[:1500], ""):
                    rejected.append({"url": row["url"], "reason": "body_issuer_not_verified"})
                    continue
                if _has_transcript_body(body):
                    body_period = _transcript_period(body[:1500])
                    expected_period = row["fiscal_period"]
                    if body_period and expected_period and (body_period["fiscal_year"], body_period["fiscal_quarter"]) != (expected_period["fiscal_year"], expected_period["fiscal_quarter"]):
                        rejected.append({"url": row["url"], "reason": "fiscal_period_mismatch"})
                        continue
                    explicit_published = re.search(r"Published\s*(?:Date|Time)?\s*[:：]\s*([^\n]+)", header, re.IGNORECASE)
                    published = _transcript_date(explicit_published.group(1)) if explicit_published else None
                    row.update(content_read=True, verification="issuer_and_body_verified", body=body[:16000],
                        snippet=body[:16000], source_url=document.get("final_url") or row["url"],
                        retrieval_method=document.get("retrieval_method"), body_truncated=len(body) >= 16000,
                        fiscal_period=body_period or row["fiscal_period"],
                        published_date=published, source_date_hint=_transcript_date(header),
                        date_precision="date" if published else "unknown")
        row["meta"] = {"subject": ticker_norm, "content_read": row["content_read"],
            "verification": row["verification"], "fiscal_period": row.get("fiscal_period"),
            "source_url": row.get("source_url") or row["url"], "retrieval_method": row.get("retrieval_method")}
        if row["content_read"]:
            row["structured_data"] = {key: value for key, value in row.items() if key != "structured_data"}
        kept.append(row)

    return {
        "ticker": ticker_norm,
        "market": market,
        "source": "earnings_transcripts_free",
        "transcripts": kept,
        "count": len(kept),
        "searched_queries": queries,
        "rejected_candidates": rejected,
        "error": None,
    }


__all__ = ["get_earnings_call_transcripts"]

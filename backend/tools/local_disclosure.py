from __future__ import annotations

import logging
import re
from io import BytesIO
from typing import Any
from urllib.parse import urlparse

from backend.config.ticker_mapping import CN_TO_TICKER
from .financial_facts import fact_date, search_line_is_noise
from .http import _http_get_no_retry
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
        return str(urlparse(str(url or "").strip().lower()).hostname or "").removeprefix("www.")
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
        if search_line_is_noise(line):
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
        if re.search(r"年(?:度)?报(?:告)?|annual\s+report", lowered):
            return "annual_report"
        if any(token in lowered for token in ("季报", "quarterly", "q1", "q2", "q3", "中报", "半年报")):
            return "quarterly_report"
        return "announcement"

    if market == "HK":
        if re.search(r"annual\s+report|年(?:度)?报(?:告)?", lowered):
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
        return fact_date(f"{int(y):04d}-{int(m):02d}-{int(d):02d}")

    cn_match = re.search(r"(20\d{2})年(\d{1,2})月(\d{1,2})日", raw)
    if cn_match:
        y, m, d = cn_match.groups()
        return fact_date(f"{int(y):04d}-{int(m):02d}-{int(d):02d}")

    return None


def _build_queries(ticker: str, market: str, company_name: str = "", query: str = "") -> list[str]:
    ticker_norm = str(ticker or "").strip().upper()
    identity = f"{company_name} {ticker_norm.split('.')[0]}".strip()
    scope = str(query or "").strip() or "annual report"
    if market == "CN":
        return [
            f"site:cninfo.com.cn {identity} {scope}",
            f"site:sse.com.cn {identity} {scope}",
            f"site:szse.cn {identity} {scope}",
        ]
    if market == "HK":
        return [
            f"site:hkexnews.hk {identity} {scope}",
            f"site:hkex.com.hk {identity} {scope}",
        ]
    return []


def _issuer_identity(text: str, ticker: str, company_name: str = "") -> str | None:
    front = str(text or "")[:5000]
    requested_code = str(ticker).split(".")[0].lstrip("0")
    codes = re.findall(r"(?:证券代码|股票代码|公司代码|股份代號|股份代号|stock\s*code)\s*[:：]?\s*(\d{1,6})", front, re.IGNORECASE)
    if codes:
        return "document_stock_code" if requested_code in {code.lstrip("0") for code in codes} else None
    aliases = [name for name, symbol in CN_TO_TICKER.items() if symbol.upper() == ticker.upper() and len(name) >= 4]
    if company_name:
        aliases.append(company_name)
    aliases += {"0700.HK": ["腾讯控股", "騰訊控股", "Tencent Holdings"], "9988.HK": ["阿里巴巴集團", "Alibaba Group"]}.get(ticker.upper(), [])
    declared_name = any(
        re.search(r"(?:^|\n)\s*" + re.escape(alias) + r"[^\n]{0,30}(?:股份有限公司|有限公司|集團有限公司|集团有限公司|Limited|Ltd\.?)(?:\s|$|[，。,])", front[:1500], re.IGNORECASE)
        for alias in aliases
    )
    return "document_company_name" if declared_name else None


def _document_title(text: str, fallback: str) -> str:
    lines = [line.strip() for line in str(text or "")[:1500].splitlines()
             if line.strip() and not re.fullmatch(r"\[Page \d+\]|\d+", line.strip())]
    if not lines or not 10 <= len(lines[0]) <= 200:
        return fallback
    if len(lines) > 1 and re.search(r"20\d{2}.*(?:报告|report)", lines[1], re.IGNORECASE):
        return f"{lines[0]} {lines[1]}"
    return lines[0]


def verified_disclosure_document(text: str, url: str, ticker: str, company_name: str = "") -> str | None:
    """交易所或正文声明的发行人网站，仍须独立核对原文发行人身份。"""
    identity = _issuer_identity(text, ticker, company_name)
    if not identity:
        return None
    host = _normalize_domain(url)
    exchange = any(host == domain or host.endswith("." + domain) for domain in _LOCAL_DISCLOSURE_DOMAINS)
    declared_host = re.search(r"(?<![\w.-])(?:https?://)?(?:www\.)?" + re.escape(host) + r"(?:[/\s]|$)", text[:600000], re.IGNORECASE)
    return identity if exchange or declared_host else None


def _fetch_disclosure_text(url: str, *, full_document: bool = False) -> str:
    """只读取已核验交易所域名的原文；搜索摘要不能替代发行人身份。"""
    try:
        response = _http_get_no_retry(url, timeout=8, allow_redirects=False, stream=True)
        try:
            if response.status_code != 200:
                return ""
            chunks = []
            size = 0
            for chunk in response.iter_content(chunk_size=65536):
                size += len(chunk)
                if size > (15_000_000 if full_document else 3_000_000):
                    return ""
                chunks.append(chunk)
            content = b"".join(chunks)
        finally:
            response.close()
        if content.startswith(b"%PDF"):
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(content))
            page_limit = 400 if full_document else 3
            pages = []
            text_size = 0
            for number, page in enumerate(reader.pages[:page_limit], 1):
                body = page.extract_text() or ""
                text_size += len(body)
                if text_size > 600_000:
                    break
                pages.append(f"[Page {number}]\n{body}")
            return "\n".join(pages)
        from bs4 import BeautifulSoup

        return BeautifulSoup(content, "html.parser").get_text("\n", strip=True)
    except Exception:
        return ""


def get_local_market_filings(ticker: str, limit: int = 8, include_financial_facts: bool = False,
                             company_name: str = "", query: str = "", financial_metrics: list[str] | None = None,
                             time_scope: dict | None = None) -> dict[str, Any]:
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
    discoveries: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    verification_attempts = 0
    extraction_attempts = 0
    extracted_metrics: set[str] = set()

    for query in _build_queries(ticker_norm, market, company_name, query):
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
            issuer_method = None
            content = ""
            if verification_attempts < min(capped_limit, 3):
                verification_attempts += 1
                content = _fetch_disclosure_text(url, full_document=True) if include_financial_facts else _fetch_disclosure_text(url)
                issuer_method = _issuer_identity(content, ticker_norm, company_name)
            if not issuer_method:
                discoveries.append({"title": title, "url": url, "snippet": snippet, "issuer_verified": False, "reason": "issuer_not_verified"})
                continue
            rows.append(
                {
                    "title": _document_title(content, title or f"{ticker_norm} local filing"),
                    "form": _infer_form(content[:1500], market),
                    "filing_url": url,
                    "filing_date": _extract_date(joined_text),
                    "primary_doc_description": snippet or title,
                    "source": domain,
                    "market": market,
                    "confidence": 0.95,
                    "issuer_verified": True,
                    "issuer_ticker": ticker_norm,
                    "identity_method": issuer_method,
                    "content": content if include_financial_facts else content[:24000],
                    "content_read": True,
                }
            )
            from .disclosure_financial_facts import _METRICS, financial_metric_inputs
            wanted = set(financial_metric_inputs(financial_metrics or _METRICS)).intersection(_METRICS)
            requested_form = "annual_report" if (time_scope or {}).get("kind") == "fiscal_year" else None
            matching_form = not requested_form or rows[-1]["form"] == requested_form
            if include_financial_facts and matching_form and extraction_attempts < 2 and (not extracted_metrics or wanted - extracted_metrics):
                from .disclosure_financial_facts import extract_financial_facts

                extraction_attempts += 1
                diagnostics: dict = {}
                rows[-1]["financial_facts"] = extract_financial_facts(content, ticker_norm, url, financial_metrics,
                    time_scope=time_scope, diagnostics=diagnostics)
                from .financial_facts import derive_cash_flow_facts
                rows[-1]["financial_facts"].extend(derive_cash_flow_facts(rows[-1]["financial_facts"], financial_metrics or []))
                rows[-1]["financial_extraction"] = diagnostics
                for fact in rows[-1]["financial_facts"]:
                    fact["filed"] = rows[-1]["filing_date"]
                    fact["published_at"] = rows[-1]["filing_date"]
                extracted_metrics.update(fact["metric"] for fact in rows[-1]["financial_facts"])
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
        "discovery_candidates": discoveries[:capped_limit],
        "error": None if rows else "issuer_verified_filings_unavailable",
        "message": None if rows else "未取得可核验发行人身份的公告原文；搜索结果仅作为发现线索。",
    }


__all__ = ["get_local_market_filings"]

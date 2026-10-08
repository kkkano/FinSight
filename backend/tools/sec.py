from __future__ import annotations

import html
import json
import logging
import os
import re
import time
import posixpath
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict
from urllib.parse import unquote, urljoin, urlparse

from .financial_facts import FinancialFact, duration_frequency, fact_date, fact_number
from .http import _http_get, _http_get_no_retry

logger = logging.getLogger(__name__)

_SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
_SEC_COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
_TICKER_CACHE_TTL_SECONDS = 24 * 60 * 60
_US_TICKER_RE = re.compile(r"^[A-Z]{1,5}(?:[.-][A-Z]{1,2})?$")

_ticker_cache: dict[str, dict[str, Any]] = {}
_ticker_cache_expire_at: float = 0.0


def _detect_market(ticker: str) -> str:
    raw = str(ticker or "").strip().upper()
    if not raw:
        return "UNKNOWN"
    if raw.endswith(".SS") or raw.endswith(".SZ"):
        return "CN"
    if raw.endswith(".HK"):
        return "HK"
    if raw.endswith(".TO") or raw.endswith(".TSX"):
        return "CA"
    if _US_TICKER_RE.fullmatch(raw):
        return "US"
    return "UNKNOWN"


def _error_payload(
    ticker: str,
    *,
    error: str,
    message: str,
    market: str = "US",
    supported_market: str = "US",
) -> Dict[str, Any]:
    return {
        "ticker": str(ticker or "").upper(),
        "market": market,
        "supported_market": supported_market,
        "source": "sec_edgar",
        "error": error,
        "message": message,
    }


def _resolve_user_agent() -> str:
    return os.getenv("SEC_USER_AGENT", "").strip()


def _is_valid_user_agent(user_agent: str) -> bool:
    return bool(user_agent and "@" in user_agent and " " in user_agent)


def _sec_headers(user_agent: str) -> dict[str, str]:
    return {
        "User-Agent": user_agent,
        "Accept": "application/json, text/html;q=0.9, */*;q=0.8",
        "Accept-Encoding": "gzip, deflate",
    }


def _normalize_forms(forms: str | list[str] | tuple[str, ...] | None) -> list[str]:
    if forms is None:
        return ["10-K", "10-Q", "8-K"]
    if isinstance(forms, str):
        chunks = re.split(r"[,\s]+", forms)
    else:
        chunks = list(forms)
    normalized: list[str] = []
    for chunk in chunks:
        token = str(chunk or "").strip().upper()
        if not token:
            continue
        if token not in normalized:
            normalized.append(token)
    return normalized or ["10-K", "10-Q", "8-K"]


def _load_ticker_map(headers: dict[str, str]) -> dict[str, dict[str, Any]]:
    global _ticker_cache, _ticker_cache_expire_at
    now = time.time()
    if _ticker_cache and now < _ticker_cache_expire_at:
        return _ticker_cache

    resp = _http_get(_SEC_TICKER_MAP_URL, headers=headers, timeout=12)
    if getattr(resp, "status_code", 0) != 200:
        raise RuntimeError(f"ticker_map_http_{getattr(resp, 'status_code', 'unknown')}")
    payload = resp.json()
    rows = payload.values() if isinstance(payload, dict) else payload

    mapping: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        ticker = str(item.get("ticker") or "").strip().upper()
        cik_value = item.get("cik_str")
        if not ticker or cik_value is None:
            continue
        try:
            cik = f"{int(cik_value):010d}"
        except Exception:
            continue
        mapping[ticker] = {
            "ticker": ticker,
            "title": str(item.get("title") or ""),
            "cik": cik,
        }

    _ticker_cache = mapping
    _ticker_cache_expire_at = now + _TICKER_CACHE_TTL_SECONDS
    return mapping


def _fetch_submissions(cik: str, headers: dict[str, str]) -> dict[str, Any]:
    url = _SEC_SUBMISSIONS_URL.format(cik=cik)
    resp = _http_get(url, headers=headers, timeout=15)
    if getattr(resp, "status_code", 0) != 200:
        raise RuntimeError(f"submissions_http_{getattr(resp, 'status_code', 'unknown')}")
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError("submissions_invalid_payload")
    return payload


def _fetch_companyfacts(cik: str, headers: dict[str, str]) -> dict[str, Any]:
    url = _SEC_COMPANYFACTS_URL.format(cik=cik)
    resp = _http_get(url, headers=headers, timeout=15)
    if getattr(resp, "status_code", 0) != 200:
        raise RuntimeError(f"companyfacts_http_{getattr(resp, 'status_code', 'unknown')}")
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError("companyfacts_invalid_payload")
    return payload


def _quarter_from_end_date(value: str) -> int:
    try:
        month = datetime.fromisoformat(str(value).split(" ")[0]).month
    except Exception:
        return 0
    return (month - 1) // 3 + 1


def _parse_companyfacts_period(entry: dict[str, Any]) -> str | None:
    return fact_date(entry.get("end"))


def _is_quarterly_companyfacts_entry(entry: dict[str, Any]) -> bool:
    return duration_frequency(entry.get("start"), entry.get("end")) == "quarterly"


def _period_sort_key(period: str) -> tuple[int, int]:
    if parsed := fact_date(period):
        point = datetime.fromisoformat(parsed)
        return (point.year, point.month * 32 + point.day)
    match = re.match(r"^(20\d{2})Q([1-4])$", str(period or ""))
    if not match:
        return (0, 0)
    return (int(match.group(1)), int(match.group(2)))


def _extract_companyfacts_metric(
    payload: dict[str, Any],
    *,
    concepts: tuple[str, ...],
    unit_candidates: tuple[str, ...],
) -> dict[str, float]:
    return {
        end: fact.value for end, fact in _extract_companyfacts_facts(
            payload, concepts=concepts, unit_candidates=unit_candidates,
        ).items()
    }


@dataclass(frozen=True)
class _DerivedQuarterlyFact(FinancialFact):
    derivation_inputs: tuple[dict[str, Any], ...] = ()

    def metadata(self) -> dict[str, Any]:
        metadata = super().metadata()
        metadata.update(derivation="ytd_difference", derivation_inputs=list(metadata["derivation_inputs"]))
        return metadata


def _cumulative_quarter_count(start: str, end: str) -> int:
    days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
    for quarter, lower, upper in ((1, 70, 110), (2, 150, 210), (3, 240, 300), (4, 330, 380)):
        if lower <= days <= upper:
            return quarter
    return 0


def _derive_ytd_cash_flow_quarters(
    entries: list[dict[str, Any]], *, subject: str, metric: str, concept: str,
    source_url: str | None,
) -> dict[str, FinancialFact]:
    """同主体、同标签、同 USD、同财年起点的相邻累计差额；更正版本不得跨申报拼接。"""
    versions: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for entry in entries:
        start, end = fact_date(entry.get("start")), fact_date(entry.get("end"))
        if not start or not end or not fact_date(entry.get("filed")) or not entry.get("accn"):
            continue
        if _cumulative_quarter_count(start, end):
            versions.setdefault((start, end), []).append(entry)

    latest: dict[tuple[str, str], tuple[dict[str, Any], bool]] = {}
    for period, candidates in versions.items():
        filed = max(str(row["filed"]) for row in candidates)
        chosen = [row for row in candidates if str(row["filed"]) == filed]
        if len({fact_number(row["val"]) for row in chosen}) != 1:
            continue
        entry = min(chosen, key=lambda row: str(row["accn"]))
        corrected = len({fact_number(row["val"]) for row in candidates}) > 1 or any(
            str(row.get("form") or "").upper().endswith("/A") for row in chosen
        )
        latest[period] = (entry, corrected)

    derived: dict[str, FinancialFact] = {}
    for (start, end), (current, current_corrected) in latest.items():
        quarter = _cumulative_quarter_count(start, end)
        if quarter < 2:
            continue
        predecessors = [
            (previous_end, row, corrected)
            for (previous_start, previous_end), (row, corrected) in latest.items()
            if previous_start == start and _cumulative_quarter_count(start, previous_end) == quarter - 1
            and 70 <= (date.fromisoformat(end) - date.fromisoformat(previous_end)).days <= 110
        ]
        if len(predecessors) != 1:
            continue
        previous_end, previous, previous_corrected = predecessors[0]
        if str(previous["filed"]) > str(current["filed"]):
            continue
        if (current_corrected or previous_corrected) and (
            current["accn"] != previous["accn"] or current["filed"] != previous["filed"]
        ):
            continue

        lineage = tuple({
            "subject": subject, "metric": metric, "concept": concept, "unit": "USD",
            "value": float(row["val"]), "period_start": start, "period_end": fact_date(row["end"]),
            "filed": fact_date(row["filed"]), "accession": row["accn"], "form": row["form"],
            "source": "sec_companyfacts", "source_url": source_url,
        } for row in (current, previous))
        derived[end] = _DerivedQuarterlyFact(
            subject=subject, metric=metric, value=float(current["val"]) - float(previous["val"]),
            unit="USD", source="sec_companyfacts", period_end=end,
            period_start=(date.fromisoformat(previous_end) + timedelta(days=1)).isoformat(),
            frequency="quarterly", filed=fact_date(current["filed"]), accession=current["accn"],
            concept=concept, form=current["form"], source_url=source_url, derivation_inputs=lineage,
        )
    return derived


def _extract_companyfacts_facts(
    payload: dict[str, Any],
    *,
    concepts: tuple[str, ...],
    unit_candidates: tuple[str, ...],
    subject: str = "",
    metric: str = "",
    instant: bool = False,
    source_url: str | None = None,
    frequency: str = "quarterly",
) -> dict[str, FinancialFact]:
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    gaap = facts.get("us-gaap") if isinstance(facts.get("us-gaap"), dict) else {}
    rows_by_period: dict[str, FinancialFact] = {}
    cash_flow_series: list[tuple[str, list[dict[str, Any]]]] = []
    direct_periods: set[str] = set()

    for concept in concepts:
        fact_obj = gaap.get(concept)
        if not isinstance(fact_obj, dict):
            continue
        units = fact_obj.get("units") if isinstance(fact_obj.get("units"), dict) else {}
        if not isinstance(units, dict):
            continue
        for unit in unit_candidates:
            entries = units.get(unit)
            if not isinstance(entries, list):
                continue
            valid: dict[str, list[dict[str, Any]]] = {}
            eligible_cash_flows: list[dict[str, Any]] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                form = str(entry.get("form") or "").upper()
                if form not in {"10-Q", "10-Q/A", "10-K", "10-K/A"}:
                    continue
                period = _parse_companyfacts_period(entry)
                if not period or fact_number(entry.get("val")) is None:
                    continue
                if not instant and frequency == "quarterly" and unit == "USD" and metric in {"operating_cash_flow", "capital_expenditures", "capital_expenditure", "dividends_paid", "repurchases_paid"}:
                    eligible_cash_flows.append(entry)
                if instant:
                    if entry.get("start"):
                        continue
                elif duration_frequency(entry.get("start"), entry.get("end")) != frequency:
                    continue
                valid.setdefault(period, []).append(entry)
            cash_flow_series.append((concept, eligible_cash_flows))
            direct_periods.update(valid)
            for period, candidates in valid.items():
                if period in rows_by_period:
                    continue
                # 同财期按提交时间、真实区间挑选；同版冲突值不任意挑一条。
                rank = lambda row: (str(row.get("filed") or ""), str(row.get("start") or ""))
                latest_rank = max(rank(row) for row in candidates)
                chosen = [row for row in candidates if rank(row) == latest_rank]
                values = {fact_number(row.get("val")) for row in chosen}
                if len(values) != 1:
                    continue
                entry = min(chosen, key=lambda row: str(row.get("accn") or ""))
                rows_by_period[period] = FinancialFact(
                    subject=subject, metric=metric, value=float(entry["val"]), unit=unit,
                    source="sec_companyfacts", period_end=period,
                    period_start=None if instant else fact_date(entry.get("start")),
                    frequency="instant" if instant else frequency,
                    filed=fact_date(entry.get("filed")), accession=entry.get("accn"),
                    concept=concept, form=str(entry.get("form") or ""),
                    source_url=source_url,
                    reporting_basis="consolidated", basis_context="sec_companyfacts_entity_wide_context",
                )
    # 先收齐所有标签的直接单季值；冲突的直接单季也不能借差分绕过校验。
    for concept, entries in cash_flow_series:
        for period, fact in _derive_ytd_cash_flow_quarters(
            entries, subject=subject, metric=metric, concept=concept, source_url=source_url,
        ).items():
            if period not in direct_periods:
                rows_by_period.setdefault(period, fact)
    return rows_by_period


def _build_filing_url(cik: str, accession_number: str, primary_doc: str) -> str:
    accession_no_dash = str(accession_number or "").replace("-", "")
    document = str(primary_doc or "").lstrip("/")
    if not accession_no_dash or not document:
        return ""
    return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{accession_no_dash}/{document}"


def _recent_filings(
    submissions: dict[str, Any],
    *,
    forms_filter: list[str],
    limit: int,
    cik: str,
) -> list[dict[str, Any]]:
    filings = submissions.get("filings")
    recent = filings.get("recent") if isinstance(filings, dict) else None
    if not isinstance(recent, dict):
        return []

    forms = recent.get("form") if isinstance(recent.get("form"), list) else []
    filing_dates = recent.get("filingDate") if isinstance(recent.get("filingDate"), list) else []
    report_dates = recent.get("reportDate") if isinstance(recent.get("reportDate"), list) else []
    accession_numbers = recent.get("accessionNumber") if isinstance(recent.get("accessionNumber"), list) else []
    primary_docs = recent.get("primaryDocument") if isinstance(recent.get("primaryDocument"), list) else []
    acceptance = recent.get("acceptanceDateTime") if isinstance(recent.get("acceptanceDateTime"), list) else []
    primary_descriptions = (
        recent.get("primaryDocDescription")
        if isinstance(recent.get("primaryDocDescription"), list)
        else []
    )

    max_len = max(
        len(forms),
        len(filing_dates),
        len(report_dates),
        len(accession_numbers),
        len(primary_docs),
        len(acceptance),
        len(primary_descriptions),
    )
    rows: list[dict[str, Any]] = []
    for idx in range(max_len):
        form = str(forms[idx] if idx < len(forms) else "").strip().upper()
        if not form:
            continue
        if forms_filter and form not in forms_filter:
            continue
        accession_number = str(accession_numbers[idx] if idx < len(accession_numbers) else "").strip()
        primary_doc = str(primary_docs[idx] if idx < len(primary_docs) else "").strip()
        rows.append(
            {
                "form": form,
                "filing_date": filing_dates[idx] if idx < len(filing_dates) else None,
                "report_date": report_dates[idx] if idx < len(report_dates) else None,
                "acceptance_datetime": acceptance[idx] if idx < len(acceptance) else None,
                "accession_number": accession_number,
                "primary_document": primary_doc,
                "primary_doc_description": (
                    primary_descriptions[idx] if idx < len(primary_descriptions) else None
                ),
                "filing_url": _build_filing_url(cik, accession_number, primary_doc),
            }
        )
        if len(rows) >= max(1, min(limit, 50)):
            break
    return rows


def _strip_html(raw: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", raw)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_risk_excerpt(raw_text: str, *, max_chars: int = 2200) -> str:
    cleaned = _strip_html(raw_text)
    pattern = re.compile(
        r"(item\s+1a[^a-z0-9]{0,20}risk\s+factors?)(.*?)(item\s+1b|item\s+2)",
        re.IGNORECASE | re.DOTALL,
    )
    match = pattern.search(cleaned)
    if match:
        snippet = f"{match.group(1)} {match.group(2)}".strip()
        return snippet[:max_chars]

    fallback = re.search(r"risk\s+factors?(.*)", cleaned, re.IGNORECASE | re.DOTALL)
    if fallback:
        return fallback.group(0)[:max_chars]
    return ""


def _extract_research_sections(raw: str) -> dict[str, str]:
    """从实际申报正文提取业务和竞争段落；短目录命中不作为正文。"""
    text = _strip_html(raw)
    sections: dict[str, str] = {}
    patterns = {
        "business": r"\bitem\s+1[.\s:]+business\b(.*?)(?=\bitem\s+1[ab][.\s:]|\bitem\s+2[.\s:]|$)",
        "management_discussion": r"\bitem\s+(?:2|7)[.\s:]+management.{0,80}?discussion(.*?)(?=\bitem\s+(?:3|7a|8)[.\s:]|$)",
    }
    for name, pattern in patterns.items():
        matches = [m.group(0) for m in re.finditer(pattern, text, re.I | re.S) if len(m.group(0)) >= 300]
        if matches:
            sections[name] = max(matches, key=len)[:6500]
    # 竞争通常是业务章节中的小节；保留原句及其相邻上下文，不能从目录标题推演。
    business_matches = [m.group(0) for m in re.finditer(patterns['business'], text, re.I | re.S) if len(m.group(0)) >= 300]
    search_text = max(business_matches, key=len) if business_matches else text
    competition = re.search(r"\b(?:competition|competitive\s+(?:environment|landscape|strengths))\b", search_text, re.I)
    if competition and sections:
        sections['competition'] = search_text[max(0, competition.start()-200):competition.start()+4000]
    return sections


def _material_document(url: str, headers: dict[str, str]) -> tuple[str, str]:
    response = _http_get_no_retry(url, headers=headers, timeout=8, allow_redirects=False)
    if response.status_code != 200:
        raise ValueError(f"material_document_http_{response.status_code}")
    raw = str(response.text or "")
    body = _strip_html(raw)
    if re.search(r"captcha|just a moment|security verification|please register|subscribe to read", body, re.I):
        raise ValueError("material_document_blocked")
    if len(body) < 100:
        raise ValueError("material_document_body_unavailable")
    return raw, body


def _material_exhibit_urls(raw: str, filing: dict[str, Any], cik: str) -> list[str]:
    from bs4 import BeautifulSoup

    base = filing["filing_url"]
    directory = f"/Archives/edgar/data/{int(cik)}/{filing['accession_number'].replace('-', '')}/"
    urls = []
    for anchor in BeautifulSoup(raw, "html.parser").find_all("a", href=True):
        href = str(anchor["href"])
        row = anchor.find_parent("tr")
        description = f"{href} {row.get_text(' ', strip=True) if row else anchor.get_text(' ', strip=True)}"
        if not re.search(r"ex(?:hibit)?[-_. ]?99(?:[-_. ]?[12])?|\b99\.[12]\b", description, re.I):
            continue
        url = urljoin(base, href)
        parsed = urlparse(url)
        normalized_path = posixpath.normpath(unquote(parsed.path))
        if parsed.scheme != "https" or parsed.netloc != "www.sec.gov" or not normalized_path.startswith(directory) or parsed.query:
            continue
        if not parsed.path.lower().endswith((".htm", ".html", ".txt")) or parsed.path == urlparse(base).path:
            continue
        if url not in urls:
            urls.append(url)
        if len(urls) == 2:
            break
    return urls


def _announcement_date(text: str) -> str | None:
    iso = re.search(r"\b20\d{2}-\d{2}-\d{2}\b", text)
    if iso:
        return fact_date(iso.group())
    match = re.search(r"\b([A-Za-z]{3,9}\s+\d{1,2},?\s+20\d{2})\b", text)
    if match:
        for pattern in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
            try:
                return datetime.strptime(match.group(1), pattern).date().isoformat()
            except ValueError:
                continue
    return None


def _dividend_announcement(body: str, *, subject: str, url: str, filing: dict[str, Any]) -> dict[str, Any] | None:
    declaration = re.search(
        r"\bdeclar(?:ed|es)\b[^.;]{0,160}?\b(?:cash\s+)?dividend\b[^.;]{0,80}?"
        r"(?P<currency>US\$|U\.S\.\s*\$|USD\s*|\$)(?P<amount>\d+(?:\.\d+)?)"
        r"\s*(?:per|for each)\s+(?:common\s+)?share\b", body, re.I)
    if not declaration:
        return None
    excerpt = body[max(0, declaration.start() - 150):declaration.end() + 900]
    context = body[max(0, declaration.start() - 100):declaration.end()]
    if re.search(r"(?:expects?\s+to|intends?\s+to|may|could|will)\s+declar(?:e|ed)|not\s+declar(?:e|ed)", context, re.I):
        return None
    currency = "USD" if re.sub(r"\s", "", declaration.group("currency")).upper() in {"US$", "U.S.$", "USD"} else None
    def following_date(marker: str) -> str | None:
        match = re.search(marker + r"(?P<suffix>.{0,100})", excerpt, re.I)
        return _announcement_date(match.group("suffix")) if match else None
    frequency_match = re.search(r"\b(quarterly|annual|monthly|special)\b", declaration.group(), re.I)
    announced = re.search(r"\bon\s+(.{0,50}?)\s*,?\s*(?:the\s+)?(?:board[^.]{0,90}?\s+)?declar(?:ed|es)\b", excerpt, re.I)
    announced_at = _announcement_date(announced.group(1)) if announced else None
    inline_date = re.search(r"\bdeclar(?:ed|es)\s+on\s+(.{0,50})", declaration.group(), re.I)
    if not announced_at and inline_date:
        announced_at = _announcement_date(inline_date.group(1))
    payable_date = following_date(r"\bpayable\b")
    record_date = following_date(r"\b(?:stock|share)holders?\s+of\s+record\b")
    frequency = frequency_match.group(1).lower() if frequency_match else None
    missing = [key for key, value in {"currency": currency, "announced_at": announced_at,
        "payable_date": payable_date, "record_date": record_date, "frequency": frequency}.items() if value is None]
    return {"subject": subject, "metric": "announced_dividend", "amount_per_share": float(declaration.group("amount")),
        "currency": currency, "currency_symbol": declaration.group("currency").strip(),
        "unit": f"{currency or '$'}/share", "frequency": frequency,
        "announced_at": announced_at, "announced_time_precision": "date" if announced_at else "unknown",
        "payable_date": payable_date, "record_date": record_date,
        "source": "sec_edgar", "source_url": url, "content_read": True, "verification": "official_filing_body",
        "filing_date": filing.get("filing_date"), "filing_accepted_at": filing.get("acceptance_datetime"),
        "accession_number": filing.get("accession_number"), "cik": filing.get("cik"), "declaration_excerpt": excerpt,
        "missing_metrics": missing}


def _read_material_filing(filing: dict[str, Any], *, ticker: str, cik: str, headers: dict[str, str]) -> None:
    filing.update(subject=ticker, cik=cik, source="sec_edgar", source_url=filing["filing_url"], content_read=False,
        announced_at=None, exhibits=[], dividend_announcements=[])
    raw, body = _material_document(filing["filing_url"], headers)
    filing.update(content_read=True, body=body[:16000], content_excerpt=body[:16000],
        content_sections={"material_event": body[:16000]}, verification="official_filing_body", body_truncated=len(body) > 16000)
    documents = [(filing["filing_url"], body)]
    for url in _material_exhibit_urls(raw, filing, cik):
        exhibit = {"subject": ticker, "url": url, "source_url": url, "source": "sec_edgar", "content_read": False,
            "parent_filing_url": filing["filing_url"], "accession_number": filing["accession_number"]}
        try:
            _, exhibit_body = _material_document(url, headers)
            exhibit.update(content_read=True, body=exhibit_body[:16000], verification="official_filing_exhibit",
                body_truncated=len(exhibit_body) > 16000)
            documents.append((url, exhibit_body))
        except Exception as exc:
            exhibit["content_error"] = str(exc) if isinstance(exc, ValueError) else "exhibit_fetch_failed"
        filing["exhibits"].append(exhibit)
    for url, content in documents:
        announcement = _dividend_announcement(content, subject=ticker, url=url, filing=filing)
        if announcement:
            filing["dividend_announcements"].append(announcement)
    if not filing["dividend_announcements"]:
        filing["missing_metrics"] = ["announced_dividend"]


def get_sec_filings(
    ticker: str,
    forms: str | list[str] | tuple[str, ...] | None = None,
    limit: int = 12,
    include_content: bool = False,
) -> Dict[str, Any]:
    normalized_ticker = str(ticker or "").strip().upper()
    if not normalized_ticker:
        return _error_payload(
            normalized_ticker,
            error="ticker_required",
            message="Ticker is required for SEC filing queries.",
            market="UNKNOWN",
        )

    market = _detect_market(normalized_ticker)
    if market != "US":
        return _error_payload(
            normalized_ticker,
            error="unsupported_market",
            message="SEC tools currently support US-listed tickers only.",
            market=market,
        )

    user_agent = _resolve_user_agent()
    if not _is_valid_user_agent(user_agent):
        return _error_payload(
            normalized_ticker,
            error="missing_sec_user_agent",
            message="Set SEC_USER_AGENT in format 'FinSight contact@company.com'.",
            market=market,
        )

    try:
        headers = _sec_headers(user_agent)
        company_map = _load_ticker_map(headers)
        company = company_map.get(normalized_ticker)
        if not company:
            return _error_payload(
                normalized_ticker,
                error="ticker_not_found",
                message="Ticker not found in SEC company list.",
                market=market,
            )

        cik = company["cik"]
        filings_filter = _normalize_forms(forms)
        submissions = _fetch_submissions(cik, headers)
        rows = _recent_filings(
            submissions,
            forms_filter=filings_filter,
            limit=limit,
            cik=cik,
        )
        if include_content:
            read_forms: set[str] = set()
            material_read_count = 0
            for filing in rows:
                form = str(filing.get("form") or "")
                if form == "8-K":
                    if material_read_count >= 6:
                        continue
                    material_read_count += 1
                    try:
                        _read_material_filing(filing, ticker=normalized_ticker, cik=cik, headers=headers)
                    except Exception as exc:
                        filing.update(content_read=False, content_error=str(exc) if isinstance(exc, ValueError) else "material_filing_fetch_failed")
                    continue
                if form not in {"10-K", "10-Q"} or form in read_forms:
                    continue
                read_forms.add(form)
                filing["content_read"] = False
                try:
                    response = _http_get(filing["filing_url"], headers=headers, timeout=25)
                    if response.status_code != 200:
                        filing["content_error"] = f"filing_http_{response.status_code}"
                        continue
                    sections = _extract_research_sections(response.text)
                    filing["content_sections"] = sections
                    filing["content_excerpt"] = "\n\n".join(f"{name}: {text}" for name, text in sections.items())
                    filing["content_read"] = bool(sections)
                    if not sections:
                        from bs4 import BeautifulSoup
                        document = BeautifulSoup(response.text, "html.parser")
                        for node in document.select("script, style, ix\\:header, [hidden]"):
                            node.decompose()
                        body = document.get_text(" ", strip=True)
                        if len(body) >= 300 and not re.search(r"captcha|security verification|just a moment", body[:1000], re.I):
                            filing.update(content_read=True, document_body=body[:100000],
                                content_excerpt=body[:16000], verification="official_filing_body",
                                content_warning="section_labels_unavailable")
                        else:
                            filing["content_error"] = "research_section_not_found"
                except Exception as exc:
                    filing["content_error"] = f"filing_fetch_failed:{type(exc).__name__}"
        return {
            "ticker": normalized_ticker,
            "market": market,
            "source": "sec_edgar",
            "company_name": company.get("title"),
            "cik": cik,
            "forms_filter": filings_filter,
            "filings": rows,
            "error": None,
        }
    except Exception as exc:
        logger.info("[SEC] get_sec_filings failed for %s: %s", normalized_ticker, exc)
        return _error_payload(
            normalized_ticker,
            error="sec_fetch_failed",
            message=f"SEC request failed: {exc.__class__.__name__}",
            market=market,
        )


def get_sec_material_events(ticker: str, limit: int = 10, include_content: bool = False) -> Dict[str, Any]:
    payload = get_sec_filings(ticker=ticker, forms=["8-K"], limit=min(limit, 6) if include_content else limit, include_content=include_content)
    events = payload.get("filings") if isinstance(payload.get("filings"), list) else []
    announcements = [announcement for event in events for announcement in event.get("dividend_announcements", [])]
    filings_read = sum(event.get("content_read") is True for event in events)
    return {
        **payload,
        "events": events,
        "event_count": len(events),
        "dividend_announcements": announcements,
        "announcement_search_state": "parsed_declarations_found" if announcements else "no_verified_declaration_in_read_documents" if filings_read else "content_unavailable",
        "coverage": {"scope": "recent_sec_8k_and_attached_exhibits", "exhaustive": False,
            "filings_returned": len(events), "filings_read": filings_read,
            "exhibits_read": sum(exhibit.get("content_read") is True for event in events for exhibit in event.get("exhibits", []))},
    }


def get_sec_risk_factors(ticker: str) -> Dict[str, Any]:
    payload = get_sec_filings(ticker=ticker, forms=["10-K", "10-Q"], limit=6)
    if payload.get("error"):
        return payload

    filings = payload.get("filings") if isinstance(payload.get("filings"), list) else []
    if not filings:
        return {
            **payload,
            "risk_factors_excerpt": "",
            "extracted": False,
            "error": "risk_filing_not_found",
            "message": "No 10-K/10-Q filings found for risk factor extraction.",
        }

    latest = filings[0]
    filing_url = str(latest.get("filing_url") or "")
    if not filing_url:
        return {
            **payload,
            "selected_filing": latest,
            "risk_factors_excerpt": "",
            "extracted": False,
            "error": "filing_url_missing",
            "message": "Latest filing does not contain a primary document URL.",
        }

    user_agent = _resolve_user_agent()
    if not _is_valid_user_agent(user_agent):
        return _error_payload(
            ticker,
            error="missing_sec_user_agent",
            message="Set SEC_USER_AGENT in format 'FinSight contact@company.com'.",
            market=_detect_market(ticker),
        )

    try:
        resp = _http_get(filing_url, headers=_sec_headers(user_agent), timeout=18)
        if getattr(resp, "status_code", 0) != 200:
            return {
                **payload,
                "selected_filing": latest,
                "risk_factors_excerpt": "",
                "extracted": False,
                "error": f"filing_http_{getattr(resp, 'status_code', 'unknown')}",
                "message": "Failed to fetch filing document.",
            }
        body = resp.text if hasattr(resp, "text") else ""
        excerpt = _extract_risk_excerpt(body)
        return {
            **payload,
            "selected_filing": latest,
            "risk_factors_excerpt": excerpt,
            "extracted": bool(excerpt),
            "error": None if excerpt else "risk_section_not_found",
            "message": "Risk factor section extracted." if excerpt else "Risk factor section not found in filing body.",
        }
    except Exception as exc:
        logger.info("[SEC] get_sec_risk_factors failed for %s: %s", ticker, exc)
        return {
            **payload,
            "selected_filing": latest,
            "risk_factors_excerpt": "",
            "extracted": False,
            "error": "risk_extraction_failed",
            "message": f"Risk extraction failed: {exc.__class__.__name__}",
        }


_COMPANYFACTS_METRIC_MAP: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "revenue": (
        ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"),
        ("USD",),
    ),
    "gross_profit": (("GrossProfit",), ("USD",)),
    "operating_income": (("OperatingIncomeLoss",), ("USD",)),
    "net_income": (("NetIncomeLoss", "ProfitLoss"), ("USD",)),
    "eps": (
        ("EarningsPerShareDiluted", "EarningsPerShareBasic", "EarningsPerShareBasicAndDiluted"),
        ("USD/shares", "USD / shares"),
    ),
    "total_assets": (("Assets",), ("USD",)),
    "total_liabilities": (("Liabilities", "LiabilitiesCurrentAndNoncurrent"), ("USD",)),
    "operating_cash_flow": (
        ("NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
        ("USD",),
    ),
    "capital_expenditures": (
        ("PaymentsToAcquirePropertyPlantAndEquipment", "CapitalExpenditures"),
        ("USD",),
    ),
}


def get_sec_company_facts_quarterly(ticker: str, limit: int = 8, time_scope: dict | None = None,
    calculations: list[dict] | None = None) -> Dict[str, Any]:
    # 保留旧入口默认季度行为；主流程用逐项财期合同选择年度或季度。
    scope = time_scope or {}
    frequency = "annual" if scope.get("kind") == "fiscal_year" else "quarterly"
    normalized_ticker = str(ticker or "").strip().upper()
    if not normalized_ticker:
        return _error_payload(
            normalized_ticker,
            error="ticker_required",
            message="Ticker is required for SEC company facts queries.",
            market="UNKNOWN",
        )

    market = _detect_market(normalized_ticker)
    if market != "US":
        return _error_payload(
            normalized_ticker,
            error="unsupported_market",
            message="SEC company facts currently support US-listed tickers only.",
            market=market,
        )

    user_agent = _resolve_user_agent()
    if not _is_valid_user_agent(user_agent):
        return _error_payload(
            normalized_ticker,
            error="missing_sec_user_agent",
            message="Set SEC_USER_AGENT in format 'FinSight contact@company.com'.",
            market=market,
        )

    try:
        headers = _sec_headers(user_agent)
        company_map = _load_ticker_map(headers)
        company = company_map.get(normalized_ticker)
        if not company:
            return _error_payload(
                normalized_ticker,
                error="ticker_not_found",
                message="Ticker not found in SEC company list.",
                market=market,
            )

        cik = company["cik"]
        payload = _fetch_companyfacts(cik, headers)
        if payload.get("cik") is not None and str(payload["cik"]).lstrip("0") != str(cik).lstrip("0"):
            return _error_payload(normalized_ticker, error="issuer_mismatch", message="SEC response issuer does not match requested CIK.", market=market)

        as_of = fact_date(scope.get("as_of")) or date.today().isoformat()
        payload = deepcopy(payload)
        for taxonomy in (payload.get("facts") or {}).values():
            for fact in taxonomy.values():
                for unit, entries in (fact.get("units") or {}).items():
                    fact["units"][unit] = [entry for entry in entries
                        if fact_date(entry.get("filed")) and fact_date(entry["filed"]) <= as_of
                        and (not fact_date(entry.get("end")) or fact_date(entry["end"]) <= as_of)]
        source_latest_filed = max((
            filed for taxonomy in (payload.get("facts") or {}).values()
            for fact in taxonomy.values() for entries in (fact.get("units") or {}).values()
            for entry in entries if (filed := fact_date(entry.get("filed")))
        ), default=None)

        metric_maps: dict[str, dict[str, float]] = {}
        metric_facts: dict[str, dict[str, FinancialFact]] = {}
        for field, (concepts, units) in _COMPANYFACTS_METRIC_MAP.items():
            metric_facts[field] = _extract_companyfacts_facts(
                payload,
                concepts=concepts,
                unit_candidates=units,
                subject=normalized_ticker,
                metric=field,
                instant=field in {"total_assets", "total_liabilities"},
                source_url=_SEC_COMPANYFACTS_URL.format(cik=cik),
                frequency=frequency,
            )
            metric_maps[field] = {end: fact.value for end, fact in metric_facts[field].items()}

        all_periods: set[str] = set()
        for field, series in metric_maps.items():
            if field not in {"total_assets", "total_liabilities"}:
                all_periods.update(series.keys())
        target_periods = sorted(all_periods, key=_period_sort_key, reverse=True)
        if scope.get("period_end"):
            target_periods = [period for period in target_periods if period == fact_date(scope["period_end"])]
        if scope.get("period_start"):
            target_periods = [period for period in target_periods if any(
                fact.period_start == fact_date(scope["period_start"]) for facts in metric_facts.values()
                if (fact := facts.get(period)) is not None and fact.frequency == frequency)]
        period_labels = target_periods[: max(1, min(limit, 12))]
        if not period_labels:
            return {
                "ticker": normalized_ticker,
                "market": market,
                "source": "sec_companyfacts",
                "company_name": company.get("title"),
                "cik": cik,
                "periods": [],
                "error": "companyfacts_period_unavailable",
                "message": "No disclosed company facts match requested period.",
            }

        result: dict[str, Any] = {
            "ticker": normalized_ticker,
            "market": market,
            "source": "sec_companyfacts",
            "company_name": company.get("title"),
            "cik": cik,
            "source_latest_filed": source_latest_filed,
            "periods": period_labels,
            "period_ends": period_labels,
            "frequency": frequency,
            "selected_period": period_labels[0],
            "request_time_scope": scope,
            "calculations": [],
            "currency": "USD",
            "fact_metadata": {
                field: [facts[period].metadata() if period in facts else None for period in period_labels]
                for field, facts in metric_facts.items()
            },
            "metric_gaps": {
                field: [period for period in period_labels if period not in values]
                for field, values in metric_maps.items() if any(period not in values for period in period_labels)
            },
            "warnings": ["年度流量采用完整财年申报区间，不以季度或累计期代替。" if frequency == "annual" else "季度流量优先采用已披露的单季区间；现金流仅允许同标签、同财年起点的相邻累计差分，并保留两项申报来源。"],
            "revenue": [metric_maps["revenue"].get(period) for period in period_labels],
            "gross_profit": [metric_maps["gross_profit"].get(period) for period in period_labels],
            "operating_income": [metric_maps["operating_income"].get(period) for period in period_labels],
            "net_income": [metric_maps["net_income"].get(period) for period in period_labels],
            "eps": [metric_maps["eps"].get(period) for period in period_labels],
            "total_assets": [metric_maps["total_assets"].get(period) for period in period_labels],
            "total_liabilities": [metric_maps["total_liabilities"].get(period) for period in period_labels],
            "operating_cash_flow": [metric_maps["operating_cash_flow"].get(period) for period in period_labels],
            "free_cash_flow": [],
            "error": None,
        }

        for idx, period in enumerate(period_labels):
            ocf = metric_maps["operating_cash_flow"].get(period)
            capex = metric_maps["capital_expenditures"].get(period)
            fcf = None
            ocf_fact = metric_facts["operating_cash_flow"].get(period)
            capex_fact = metric_facts["capital_expenditures"].get(period)
            if ocf is not None and capex is not None and ocf_fact and capex_fact and ocf_fact.period_start == capex_fact.period_start and ocf_fact.unit == capex_fact.unit:
                fcf = ocf + capex if capex < 0 else ocf - capex
            result["free_cash_flow"].append(fcf)
            result["fact_metadata"].setdefault("free_cash_flow", []).append(
                {
                    **ocf_fact.metadata(), "metric": "free_cash_flow", "value": fcf,
                    "derived_from": ["operating_cash_flow", "capital_expenditures"],
                    "derivation": "operating_cash_flow_minus_capital_expenditures",
                    "derivation_inputs": [ocf_fact.metadata(), capex_fact.metadata()],
                    "capital_expenditures_concept": capex_fact.concept,
                }
                if fcf is not None and ocf_fact and capex_fact else None
            )

        from .financial_calculations import calculate_period_change
        selected_period = period_labels[0]
        for spec in calculations or []:
            metric = str(spec.get("metric") or "")
            current = metric_facts.get(metric, {}).get(selected_period)
            if current is None:
                continue
            candidates = [record for record in metric_facts[metric].values() if record.period_end < current.period_end]
            candidates.sort(key=lambda record: record.period_end, reverse=True)
            for previous in candidates:
                computed = calculate_period_change(current.metadata(), previous.metadata(),
                    operation=spec.get("operation"), baseline=spec.get("baseline"))
                if computed is not None:
                    result["calculations"].append(computed)
                    break

        has_any = any(
            any(v is not None for v in (result.get(field) or []))
            for field in (
                "revenue",
                "gross_profit",
                "operating_income",
                "net_income",
                "eps",
                "total_assets",
                "total_liabilities",
                "operating_cash_flow",
                "free_cash_flow",
            )
        )
        if not has_any:
            result["error"] = "companyfacts_no_metric_values"
            result["message"] = "Quarterly company facts response does not contain supported metrics."
        return result
    except Exception as exc:
        logger.info("[SEC] get_sec_company_facts_quarterly failed for %s: %s", normalized_ticker, exc)
        return _error_payload(
            normalized_ticker,
            error="companyfacts_fetch_failed",
            message=f"SEC company facts request failed: {exc.__class__.__name__}",
            market=market,
        )


__all__ = [
    "get_sec_filings",
    "get_sec_material_events",
    "get_sec_risk_factors",
    "get_sec_company_facts_quarterly",
]

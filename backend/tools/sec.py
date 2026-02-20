from __future__ import annotations

import html
import json
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict

from .http import _http_get

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
    value = os.getenv("SEC_USER_AGENT", "").strip()
    if value:
        return value
    fallback_email = os.getenv("EMAIL_FROM", "").strip()
    if fallback_email:
        return f"FinSight {fallback_email}"
    return ""


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
    end = str(entry.get("end") or "").strip()
    if not end:
        return None
    try:
        year = datetime.fromisoformat(end.split(" ")[0]).year
    except Exception:
        return None
    fp = str(entry.get("fp") or "").strip().upper()
    if fp in {"Q1", "Q2", "Q3", "Q4"}:
        return f"{year}{fp}"
    quarter = _quarter_from_end_date(end)
    return f"{year}Q{quarter}" if quarter in {1, 2, 3, 4} else None


def _is_quarterly_companyfacts_entry(entry: dict[str, Any]) -> bool:
    form = str(entry.get("form") or "").strip().upper()
    fp = str(entry.get("fp") or "").strip().upper()
    frame = str(entry.get("frame") or "").strip().upper()
    return bool(
        form.startswith("10-Q")
        or fp in {"Q1", "Q2", "Q3", "Q4"}
        or re.search(r"Q[1-4](?:I)?$", frame)
    )


def _period_sort_key(period: str) -> tuple[int, int]:
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
    facts = payload.get("facts") if isinstance(payload.get("facts"), dict) else {}
    gaap = facts.get("us-gaap") if isinstance(facts.get("us-gaap"), dict) else {}
    rows_by_period: dict[str, tuple[str, float]] = {}

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
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                if not _is_quarterly_companyfacts_entry(entry):
                    continue
                period = _parse_companyfacts_period(entry)
                if not period:
                    continue
                val = entry.get("val")
                try:
                    number = float(val)
                except Exception:
                    continue
                filed = str(entry.get("filed") or "")
                prev = rows_by_period.get(period)
                if prev is None or filed > prev[0]:
                    rows_by_period[period] = (filed, number)
    return {period: value for period, (_, value) in rows_by_period.items()}


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


def get_sec_filings(
    ticker: str,
    forms: str | list[str] | tuple[str, ...] | None = None,
    limit: int = 12,
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


def get_sec_material_events(ticker: str, limit: int = 10) -> Dict[str, Any]:
    payload = get_sec_filings(ticker=ticker, forms=["8-K"], limit=limit)
    events = payload.get("filings") if isinstance(payload.get("filings"), list) else []
    return {
        **payload,
        "events": events,
        "event_count": len(events),
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


def get_sec_company_facts_quarterly(ticker: str, limit: int = 8) -> Dict[str, Any]:
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

        metric_maps: dict[str, dict[str, float]] = {}
        for field, (concepts, units) in _COMPANYFACTS_METRIC_MAP.items():
            metric_maps[field] = _extract_companyfacts_metric(
                payload,
                concepts=concepts,
                unit_candidates=units,
            )

        all_periods: set[str] = set()
        for series in metric_maps.values():
            all_periods.update(series.keys())
        period_labels = sorted(all_periods, key=_period_sort_key, reverse=True)[: max(1, min(limit, 12))]
        if not period_labels:
            return {
                "ticker": normalized_ticker,
                "market": market,
                "source": "sec_companyfacts",
                "company_name": company.get("title"),
                "cik": cik,
                "periods": [],
                "error": "companyfacts_no_quarterly_data",
                "message": "No quarterly company facts found for ticker.",
            }

        result: dict[str, Any] = {
            "ticker": normalized_ticker,
            "market": market,
            "source": "sec_companyfacts",
            "company_name": company.get("title"),
            "cik": cik,
            "periods": period_labels,
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
            if ocf is not None and capex is not None:
                fcf = ocf + capex if capex < 0 else ocf - capex
            result["free_cash_flow"].append(fcf)

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

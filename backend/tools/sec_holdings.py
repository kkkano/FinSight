# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any, Dict

from .http import _http_get
from .sec import (
    _build_filing_url,
    _detect_market,
    _error_payload,
    _is_valid_user_agent,
    _resolve_user_agent,
    _sec_headers,
)

_SEC_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"

FORM_13F_DUE_NOTE = "SEC Form 13F is due within 45 days after each calendar quarter end."
FORM_4_DUE_NOTE = "In most cases, Form 4 is filed within two business days following the transaction date."
FORM_4_INTERPRETATION_TEMPLATE = "Raw SEC Form 4 code {code}; do not infer intent from code alone."

_CUSIP_TO_TICKER_HINTS = {
    "037833100": "AAPL",
    "594918104": "MSFT",
    "67066G104": "NVDA",
    "88160R101": "TSLA",
}


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _upper(value: Any) -> str:
    return _clean(value).upper()


def _safe_float(value: Any) -> float | None:
    text = _clean(value).replace(",", "")
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _safe_int(value: Any) -> int | None:
    number = _safe_float(value)
    if number is None:
        return None
    return int(number)


def _cik10(value: Any) -> str:
    text = _clean(value).upper()
    if not re.fullmatch(r"(?:CIK)?\d{1,10}", text):
        return ""
    digits = text.removeprefix("CIK")
    if not digits:
        return ""
    return f"{int(digits):010d}"


def _node_name(node: ET.Element) -> str:
    return str(node.tag).split("}", 1)[-1].lower()


def _first_child(node: ET.Element, name: str) -> ET.Element | None:
    target = name.lower()
    for child in list(node):
        if _node_name(child) == target:
            return child
    return None


def _first_descendant(node: ET.Element, *names: str) -> ET.Element | None:
    targets = {name.lower() for name in names}
    for child in node.iter():
        if child is node:
            continue
        if _node_name(child) in targets:
            return child
    return None


def _text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return _clean("".join(node.itertext()))


def _value_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    value_node = _first_descendant(node, "value")
    return _text(value_node) if value_node is not None else _text(node)


def _load_ticker_map(headers: dict[str, str]) -> dict[str, dict[str, Any]]:
    resp = _http_get(_SEC_TICKER_MAP_URL, headers=headers, timeout=12)
    if getattr(resp, "status_code", 0) != 200:
        raise RuntimeError(f"ticker_map_http_{getattr(resp, 'status_code', 'unknown')}")
    payload = resp.json()
    rows = payload.values() if isinstance(payload, dict) else payload
    mapping: dict[str, dict[str, Any]] = {}
    if not isinstance(rows, list) and not hasattr(rows, "__iter__"):
        return mapping
    for item in rows:
        if not isinstance(item, dict):
            continue
        ticker = _upper(item.get("ticker"))
        cik_value = item.get("cik_str")
        if not ticker or cik_value is None:
            continue
        mapping[ticker] = {
            "ticker": ticker,
            "title": _clean(item.get("title")),
            "cik": _cik10(cik_value),
        }
    return mapping


def _fetch_submissions(cik: str, headers: dict[str, str]) -> dict[str, Any]:
    resp = _http_get(_SEC_SUBMISSIONS_URL.format(cik=cik), headers=headers, timeout=15)
    if getattr(resp, "status_code", 0) != 200:
        raise RuntimeError(f"submissions_http_{getattr(resp, 'status_code', 'unknown')}")
    payload = resp.json()
    if not isinstance(payload, dict):
        raise RuntimeError("submissions_invalid_payload")
    return payload


def _recent_filings(submissions: dict[str, Any], *, cik: str, forms: set[str], limit: int) -> list[dict[str, Any]]:
    filings = submissions.get("filings")
    recent = filings.get("recent") if isinstance(filings, dict) else None
    if not isinstance(recent, dict):
        return []

    def col(name: str) -> list[Any]:
        value = recent.get(name)
        return value if isinstance(value, list) else []

    rows: list[dict[str, Any]] = []
    max_len = max(
        len(col("form")),
        len(col("filingDate")),
        len(col("reportDate")),
        len(col("acceptanceDateTime")),
        len(col("accessionNumber")),
        len(col("primaryDocument")),
        len(col("primaryDocDescription")),
    )
    for index in range(max_len):
        form = _upper(col("form")[index] if index < len(col("form")) else "")
        if form not in forms:
            continue
        accession_number = _clean(col("accessionNumber")[index] if index < len(col("accessionNumber")) else "")
        primary_document = _clean(col("primaryDocument")[index] if index < len(col("primaryDocument")) else "")
        rows.append(
            {
                "form": form,
                "filing_date": _clean(col("filingDate")[index] if index < len(col("filingDate")) else "") or None,
                "report_date": _clean(col("reportDate")[index] if index < len(col("reportDate")) else "") or None,
                "acceptance_datetime": _clean(col("acceptanceDateTime")[index] if index < len(col("acceptanceDateTime")) else "") or None,
                "accession_number": accession_number,
                "primary_document": primary_document,
                "primary_doc_description": _clean(col("primaryDocDescription")[index] if index < len(col("primaryDocDescription")) else "") or None,
                "filing_url": _build_filing_url(cik, accession_number, primary_document),
            }
        )
        if len(rows) >= max(1, min(limit, 50)):
            break
    return rows


def _normalize_quarter(report_date: str | None) -> str | None:
    try:
        parsed = datetime.fromisoformat(str(report_date or "").split("T")[0])
    except Exception:
        return None
    quarter = (parsed.month - 1) // 3 + 1
    return f"{parsed.year}Q{quarter}"


def _resolve_entity(value: str, headers: dict[str, str]) -> dict[str, Any]:
    raw = _clean(value)
    cik = _cik10(raw)
    if cik:
        return {"query": raw, "cik": cik, "market": "US", "ticker": None, "title": ""}

    market = _detect_market(raw)
    if market != "US":
        return {"query": raw, "cik": "", "market": market, "ticker": _upper(raw), "title": ""}

    ticker_map = _load_ticker_map(headers)
    ticker = _upper(raw)
    if ticker in ticker_map:
        return {"query": raw, "market": "US", **ticker_map[ticker]}

    raw_norm = re.sub(r"[^a-z0-9]+", " ", raw.lower()).strip()
    for item in ticker_map.values():
        title_norm = re.sub(r"[^a-z0-9]+", " ", str(item.get("title") or "").lower()).strip()
        if raw_norm and raw_norm in title_norm:
            return {"query": raw, "market": "US", **item}
    return {"query": raw, "cik": "", "market": "UNKNOWN", "ticker": ticker, "title": ""}


def _ticker_for_holding(row: dict[str, Any], ticker_map: dict[str, dict[str, Any]]) -> str | None:
    cusip = _upper(row.get("cusip"))
    if cusip in _CUSIP_TO_TICKER_HINTS:
        return _CUSIP_TO_TICKER_HINTS[cusip]
    issuer = re.sub(r"[^a-z0-9]+", " ", str(row.get("issuer_name") or "").lower()).strip()
    for item in ticker_map.values():
        title = re.sub(r"[^a-z0-9]+", " ", str(item.get("title") or "").lower()).strip()
        if issuer and (issuer in title or title in issuer):
            return str(item.get("ticker") or "").upper() or None
    return None


def _parse_13f_info_table(xml_text: str, ticker_map: dict[str, dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    rows: list[dict[str, Any]] = []
    for info_table in root.iter():
        if _node_name(info_table) != "infotable":
            continue
        row = {
            "issuer_name": _text(_first_child(info_table, "nameOfIssuer")),
            "title_of_class": _text(_first_child(info_table, "titleOfClass")),
            "cusip": _upper(_text(_first_child(info_table, "cusip"))),
            "value_usd_thousands": _safe_int(_text(_first_child(info_table, "value"))),
            "shares": _safe_int(_text(_first_descendant(info_table, "sshPrnamt"))),
            "share_type": _upper(_text(_first_descendant(info_table, "sshPrnamtType"))) or None,
            "investment_discretion": _text(_first_child(info_table, "investmentDiscretion")) or None,
            "voting_authority": {
                "sole": _safe_int(_text(_first_descendant(info_table, "Sole"))),
                "shared": _safe_int(_text(_first_descendant(info_table, "Shared"))),
                "none": _safe_int(_text(_first_descendant(info_table, "None"))),
            },
        }
        ticker = _ticker_for_holding(row, ticker_map)
        if ticker:
            row["ticker"] = ticker
        rows.append(row)
        if len(rows) >= max(1, min(limit, 500)):
            break
    return rows


def _parse_form4_transactions(xml_text: str, filing: dict[str, Any], *, limit: int) -> list[dict[str, Any]]:
    root = ET.fromstring(xml_text)
    owner = _value_text(_first_descendant(root, "rptOwnerName"))
    issuer_ticker = _value_text(_first_descendant(root, "issuerTradingSymbol"))
    issuer_name = _value_text(_first_descendant(root, "issuerName"))
    rows: list[dict[str, Any]] = []

    for security_type, tag_name in (("non_derivative", "nonDerivativeTransaction"), ("derivative", "derivativeTransaction")):
        for transaction in root.iter():
            if _node_name(transaction) != tag_name.lower():
                continue
            code = _upper(_text(_first_descendant(transaction, "transactionCode")))
            row = {
                "issuer_ticker": issuer_ticker or None,
                "issuer_name": issuer_name or None,
                "owner_name": owner or None,
                "reporting_owner_name": owner or None,
                "security_title": _value_text(_first_descendant(transaction, "securityTitle")) or None,
                "security_type": security_type,
                "transaction_date": _value_text(_first_descendant(transaction, "transactionDate")) or filing.get("report_date"),
                "filing_date": filing.get("filing_date"),
                "transaction_code": code or None,
                "acquired_disposed": _upper(_value_text(_first_descendant(transaction, "transactionAcquiredDisposedCode"))) or None,
                "shares": _safe_float(_value_text(_first_descendant(transaction, "transactionShares"))),
                "price_per_share": _safe_float(_value_text(_first_descendant(transaction, "transactionPricePerShare"))),
                "direct_or_indirect_ownership": _upper(_value_text(_first_descendant(transaction, "directOrIndirectOwnership"))) or None,
                "post_transaction_shares": _safe_float(_value_text(_first_descendant(transaction, "sharesOwnedFollowingTransaction"))),
                "interpretation_note": FORM_4_INTERPRETATION_TEMPLATE.format(code=code or "unknown"),
            }
            rows.append(row)
            if len(rows) >= max(1, min(limit, 200)):
                return rows
    return rows


def _prepared_sec_context(identifier: str) -> tuple[dict[str, Any] | None, dict[str, str] | None, dict[str, dict[str, Any]] | None, dict[str, Any] | None]:
    user_agent = _resolve_user_agent()
    if not _is_valid_user_agent(user_agent):
        return None, None, None, _error_payload(
            identifier,
            error="missing_sec_user_agent",
            message="Set SEC_USER_AGENT in format 'FinSight contact@company.com'.",
            market="US",
        )
    headers = _sec_headers(user_agent)
    entity = _resolve_entity(identifier, headers)
    if entity.get("market") != "US":
        return entity, headers, None, _error_payload(
            identifier,
            error="unsupported_market",
            message="SEC holdings tools currently support US filings only.",
            market=entity.get("market") or "UNKNOWN",
        )
    if not entity.get("cik"):
        return entity, headers, None, _error_payload(
            identifier,
            error="cik_not_found",
            message="Could not resolve a SEC CIK for this identifier.",
            market="US",
        )
    ticker_map = _load_ticker_map(headers)
    return entity, headers, ticker_map, None


def get_institutional_holdings(cik_or_name: str, quarter: str | None = None, limit: int = 100) -> Dict[str, Any]:
    entity, headers, ticker_map, error = _prepared_sec_context(cik_or_name)
    if error:
        return error
    assert entity is not None and headers is not None and ticker_map is not None
    cik = str(entity["cik"])

    try:
        submissions = _fetch_submissions(cik, headers)
        filings = _recent_filings(submissions, cik=cik, forms={"13F-HR", "13F-HR/A"}, limit=20)
        selected = None
        quarter_norm = _upper(quarter) if quarter else None
        for filing in filings:
            filing_quarter = _normalize_quarter(filing.get("report_date"))
            if quarter_norm and filing_quarter != quarter_norm:
                continue
            selected = {**filing, "quarter": filing_quarter}
            break
        if not selected:
            return {
                "source": "sec_13f",
                "cik": cik,
                "holder_name": submissions.get("name") or entity.get("title") or _clean(cik_or_name),
                "quarter": quarter_norm,
                "holdings": [],
                "regulatory_notes": {"form_13f_due": FORM_13F_DUE_NOTE},
                "error": "filing_not_found",
                "message": "No matching 13F-HR filing found in recent SEC submissions.",
            }
        filing_url = selected.get("filing_url") or ""
        resp = _http_get(filing_url, headers=headers, timeout=20)
        if getattr(resp, "status_code", 0) != 200:
            raise RuntimeError(f"filing_http_{getattr(resp, 'status_code', 'unknown')}")
        holdings = _parse_13f_info_table(str(getattr(resp, "text", "") or ""), ticker_map, limit)
        return {
            "source": "sec_13f",
            "cik": cik,
            "holder_name": submissions.get("name") or entity.get("title") or _clean(cik_or_name),
            "quarter": selected.get("quarter"),
            "filing": selected,
            "holdings": holdings,
            "regulatory_notes": {"form_13f_due": FORM_13F_DUE_NOTE},
            "error": None,
        }
    except Exception as exc:
        return _error_payload(cik_or_name, error="sec_13f_fetch_failed", message=str(exc), market="US")


def get_institution_holdings_by_ticker(ticker: str, limit: int = 50) -> Dict[str, Any]:
    market = _detect_market(ticker)
    if market != "US":
        return _error_payload(
            ticker,
            error="unsupported_market",
            message="SEC holdings tools currently support US-listed tickers only.",
            market=market,
        )
    return {
        "ticker": _upper(ticker),
        "source": "sec_13f",
        "supported_market": "US",
        "holders": [],
        "limit": max(1, min(int(limit or 50), 200)),
        "regulatory_notes": {"form_13f_due": FORM_13F_DUE_NOTE},
        "capability_note": "Free SEC recent submissions are holder-centric; bulk by-ticker holders require SEC 13F data sets or a local index.",
        "error": None,
    }


def get_insider_transactions(ticker: str, days: int = 180, limit: int = 50) -> Dict[str, Any]:
    entity, headers, _ticker_map, error = _prepared_sec_context(ticker)
    if error:
        return error
    assert entity is not None and headers is not None
    cik = str(entity["cik"])
    try:
        submissions = _fetch_submissions(cik, headers)
        filings = _recent_filings(submissions, cik=cik, forms={"4", "4/A"}, limit=max(1, min(limit, 50)))
        transactions: list[dict[str, Any]] = []
        for filing in filings:
            resp = _http_get(filing.get("filing_url") or "", headers=headers, timeout=20)
            if getattr(resp, "status_code", 0) != 200:
                continue
            transactions.extend(_parse_form4_transactions(str(getattr(resp, "text", "") or ""), filing, limit=limit - len(transactions)))
            if len(transactions) >= max(1, min(limit, 200)):
                break
        return {
            "source": "sec_form4",
            "ticker": entity.get("ticker") or _upper(ticker),
            "cik": cik,
            "issuer_name": submissions.get("name") or entity.get("title"),
            "transactions": transactions,
            "regulatory_notes": {"form_4_due": FORM_4_DUE_NOTE},
            "error": None,
        }
    except Exception as exc:
        return _error_payload(ticker, error="sec_form4_fetch_failed", message=str(exc), market="US")


def _position_tickers(positions: list[dict]) -> list[str]:
    result: list[str] = []
    for position in positions or []:
        if not isinstance(position, dict):
            continue
        ticker = _upper(position.get("ticker") or position.get("symbol"))
        if ticker and ticker not in result:
            result.append(ticker)
    return result


def get_holdings_overlap(positions: list[dict], holder_cik_or_name: str, quarter: str | None = None) -> Dict[str, Any]:
    portfolio_tickers = _position_tickers(positions)
    holdings_payload = get_institutional_holdings(holder_cik_or_name, quarter=quarter, limit=500)
    if holdings_payload.get("error"):
        return {**holdings_payload, "portfolio_tickers": portfolio_tickers}

    institution_tickers = sorted({
        _upper(row.get("ticker"))
        for row in holdings_payload.get("holdings", [])
        if isinstance(row, dict) and _upper(row.get("ticker"))
    })
    overlap = [ticker for ticker in portfolio_tickers if ticker in institution_tickers]
    portfolio_only = [ticker for ticker in portfolio_tickers if ticker not in institution_tickers]
    institution_only = [ticker for ticker in institution_tickers if ticker not in portfolio_tickers]
    return {
        **holdings_payload,
        "source": "sec_holdings_overlap",
        "portfolio_tickers": portfolio_tickers,
        "institution_tickers": institution_tickers,
        "overlap_tickers": overlap,
        "overlap_count": len(overlap),
        "portfolio_only_tickers": portfolio_only,
        "institution_only_tickers": institution_only,
        "error": None,
    }


__all__ = [
    "FORM_13F_DUE_NOTE",
    "FORM_4_DUE_NOTE",
    "get_institutional_holdings",
    "get_institution_holdings_by_ticker",
    "get_insider_transactions",
    "get_holdings_overlap",
]

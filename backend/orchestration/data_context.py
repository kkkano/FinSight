# -*- coding: utf-8 -*-
"""
DataContext utilities for normalizing as_of / currency / adjustment and
performing consistency checks across collected data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple
import os
import re


DEFAULT_MAX_SKEW_HOURS = float(os.getenv("DATA_CONTEXT_MAX_SKEW_HOURS", "24"))


def _parse_iso(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        text = str(value).strip()
        if not text:
            return None
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except Exception:
        return None


def _normalize_currency(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip().upper()
    if not text:
        return None
    alias_map = {
        "US$": "USD",
        "$": "USD",
        "RMB": "CNY",
    }
    if text in alias_map:
        return alias_map[text]
    return text


def _infer_currency_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    upper = text.upper()
    if "USD" in upper or "$" in upper:
        return "USD"
    for code in ("HKD", "CNY", "EUR", "GBP", "JPY", "AUD", "CAD"):
        if code in upper:
            return code
    return None


def _infer_currency_from_ticker(ticker: str) -> Optional[str]:
    if not ticker:
        return None
    upper = ticker.upper()
    if upper.endswith((".HK",)):
        return "HKD"
    if upper.endswith((".SS", ".SZ")):
        return "CNY"
    if upper.endswith((".T", ".JP")):
        return "JPY"
    if upper.endswith((".L",)):
        return "GBP"
    if upper.endswith((".PA", ".FR", ".DE", ".F")):
        return "EUR"
    if upper.endswith((".TO", ".TSX")):
        return "CAD"
    if upper.endswith((".AX",)):
        return "AUD"
    return "USD"


def _normalize_adjustment(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "adjusted" if value else "raw"
    text = str(value).strip().lower()
    if not text:
        return None
    if "adjust" in text:
        return "adjusted"
    if "raw" in text or "unadjust" in text:
        return "raw"
    return text


def _extract_from_mapping(data: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    as_of = data.get("as_of") or data.get("timestamp") or data.get("generated_at")
    currency = data.get("currency") or data.get("currency_code")
    adjustment = data.get("adjustment")
    if adjustment is None and "adjusted" in data:
        adjustment = data.get("adjusted")
    return (
        str(as_of) if as_of else None,
        _normalize_currency(currency),
        _normalize_adjustment(adjustment),
    )


def extract_context_fields(
    data: Any,
    *,
    as_of: Optional[str] = None,
    currency: Optional[str] = None,
    adjustment: Optional[str] = None,
    ticker: Optional[str] = None,
) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    resolved_as_of = as_of
    resolved_currency = _normalize_currency(currency)
    resolved_adjustment = _normalize_adjustment(adjustment)

    if isinstance(data, dict):
        extracted_as_of, extracted_currency, extracted_adjustment = _extract_from_mapping(data)
        resolved_as_of = resolved_as_of or extracted_as_of
        resolved_currency = resolved_currency or extracted_currency
        resolved_adjustment = resolved_adjustment or extracted_adjustment
    elif isinstance(data, list):
        # pick the latest timestamp-like field if available
        candidate_times: List[datetime] = []
        for item in data:
            if not isinstance(item, dict):
                continue
            item_as_of, item_currency, item_adjustment = _extract_from_mapping(item)
            if not resolved_currency:
                resolved_currency = item_currency
            if not resolved_adjustment:
                resolved_adjustment = item_adjustment
            parsed = _parse_iso(item_as_of)
            if parsed:
                candidate_times.append(parsed)
        if candidate_times and not resolved_as_of:
            resolved_as_of = max(candidate_times).isoformat()
    elif isinstance(data, str):
        if not resolved_currency:
            resolved_currency = _infer_currency_from_text(data)

    if not resolved_currency and ticker:
        resolved_currency = _infer_currency_from_ticker(ticker)

    return resolved_as_of, resolved_currency, resolved_adjustment


@dataclass
class DataContextItem:
    source: str
    as_of: Optional[str] = None
    currency: Optional[str] = None
    adjustment: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "as_of": self.as_of,
            "currency": self.currency,
            "adjustment": self.adjustment,
            "details": dict(self.details) if isinstance(self.details, dict) else {},
        }


@dataclass
class DataContextSummary:
    as_of: Optional[str] = None
    currency: Optional[str] = None
    adjustment: Optional[str] = None
    sources: List[str] = field(default_factory=list)
    items: List[DataContextItem] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    as_of_skew_hours: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "as_of": self.as_of,
            "currency": self.currency,
            "adjustment": self.adjustment,
            "sources": list(self.sources),
            "items": [item.to_dict() for item in self.items],
            "warnings": list(self.warnings),
            "issues": list(self.issues),
            "as_of_skew_hours": self.as_of_skew_hours,
        }


class DataContextCollector:
    def __init__(self, max_skew_hours: Optional[float] = None):
        self.items: List[DataContextItem] = []
        self.max_skew_hours = max_skew_hours if max_skew_hours is not None else DEFAULT_MAX_SKEW_HOURS

    def add(
        self,
        source: str,
        data: Any = None,
        *,
        as_of: Optional[str] = None,
        currency: Optional[str] = None,
        adjustment: Optional[str] = None,
        ticker: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        resolved_as_of, resolved_currency, resolved_adjustment = extract_context_fields(
            data,
            as_of=as_of,
            currency=currency,
            adjustment=adjustment,
            ticker=ticker,
        )
        if details is None and ticker:
            details = {"ticker": ticker}
        self.items.append(
            DataContextItem(
                source=source,
                as_of=resolved_as_of,
                currency=resolved_currency,
                adjustment=resolved_adjustment,
                details=details or {},
            )
        )

    def summarize(self) -> DataContextSummary:
        summary = DataContextSummary()
        if not self.items:
            summary.warnings.append("data_context_empty")
            return summary

        summary.items = list(self.items)
        summary.sources = [item.source for item in self.items]

        currencies = sorted({item.currency for item in self.items if item.currency})
        adjustments = sorted({item.adjustment for item in self.items if item.adjustment})
        as_of_values = [item.as_of for item in self.items if item.as_of]

        if len(currencies) == 1:
            summary.currency = currencies[0]
        elif len(currencies) > 1:
            summary.issues.append(f"currency_conflict:{'/'.join(currencies)}")

        if len(adjustments) == 1:
            summary.adjustment = adjustments[0]
        elif len(adjustments) > 1:
            summary.warnings.append(f"adjustment_mismatch:{'/'.join(adjustments)}")

        parsed_times = []
        for value in as_of_values:
            parsed = _parse_iso(value)
            if parsed:
                parsed_times.append(parsed)

        if parsed_times:
            latest = max(parsed_times)
            earliest = min(parsed_times)
            summary.as_of = latest.isoformat()
            skew_hours = abs((latest - earliest).total_seconds()) / 3600.0
            summary.as_of_skew_hours = round(skew_hours, 4)
            if self.max_skew_hours and skew_hours > self.max_skew_hours:
                summary.warnings.append(f"as_of_skew_exceeds:{self.max_skew_hours}h")
        else:
            summary.warnings.append("as_of_missing")

        if not summary.currency:
            summary.warnings.append("currency_missing")
        if not summary.adjustment:
            summary.warnings.append("adjustment_missing")

        return summary

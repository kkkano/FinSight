# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/report_builder.py（WP3 Task5，零行为变更）。
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from backend.report.util import _classify_report_type, _safe_str

_QUALITY_PROFILES: dict[str, dict[str, bool]] = {
    "deep_financial": {
        "10k": True,
        "10q": True,
        "local_filing": False,
        "transcript": True,
        "media": True,
        "snippets": True,
    },
    "general": {
        "10k": False,
        "10q": False,
        "local_filing": False,
        "transcript": False,
        "media": True,
        "snippets": True,
    },
    "technical": {
        "10k": False,
        "10q": False,
        "local_filing": False,
        "transcript": False,
        "media": False,
        "snippets": True,
    },
    "news": {
        "10k": False,
        "10q": False,
        "local_filing": False,
        "transcript": False,
        "media": True,
        "snippets": True,
    },
}

def _infer_market_from_context(*, tickers: list[str] | None = None, market: str | None = None) -> str:
    market_text = _safe_str(market).strip().upper()
    if market_text in {"US", "CN", "HK"}:
        return market_text

    for ticker in tickers or []:
        symbol = _safe_str(ticker).strip().upper()
        if not symbol:
            continue
        if symbol.endswith((".SS", ".SZ", ".BJ")):
            return "CN"
        if symbol.endswith(".HK"):
            return "HK"
        return "US"
    return "US"


def _build_report_quality_hints(
    *,
    query: str,
    citations: list[dict[str, Any]],
    tickers: list[str] | None = None,
    market: str | None = None,
) -> dict[str, Any]:
    authoritative_media_domains = (
        "reuters.com",
        "bloomberg.com",
        "wsj.com",
        "ft.com",
        "cnbc.com",
        "finance.yahoo.com",
    )
    local_filing_domains = (
        "cninfo.com.cn",
        "sse.com.cn",
        "szse.cn",
        "hkexnews.hk",
        "hkex.com.hk",
    )

    report_type = _classify_report_type(query)
    profile = dict(_QUALITY_PROFILES.get(report_type, _QUALITY_PROFILES["general"]))
    report_market = _infer_market_from_context(tickers=tickers, market=market)
    if report_type == "deep_financial":
        if report_market == "US":
            profile["10k"] = True
            profile["10q"] = True
            profile["local_filing"] = False
        else:
            profile["10k"] = False
            profile["10q"] = False
            profile["local_filing"] = True

    deep_required = report_type == "deep_financial"

    has_10k = False
    has_10q = False
    has_local_filing = False
    has_earnings_transcript = False
    authoritative_media_count = 0
    sec_filing_count = 0
    local_filing_count = 0
    rich_snippet_count = 0

    for item in citations:
        if not isinstance(item, dict):
            continue
        url = _safe_str(item.get("url") or "").strip().lower()
        source = _safe_str(item.get("source") or "").strip().lower()
        title = _safe_str(item.get("title") or "").strip().lower()
        snippet = _safe_str(item.get("snippet") or "").strip()
        parsed = urlparse(url)
        domain = (parsed.netloc or "").lower().lstrip("www.")
        joined = f"{url} {title} {snippet.lower()}"

        if domain.endswith("sec.gov") or "sec.gov/" in url:
            sec_filing_count += 1
            if re.search(r"\b10-k\b|annual report|form\s*10k", joined, flags=re.I):
                has_10k = True
            if re.search(r"\b10-q\b|quarterly report|form\s*10q", joined, flags=re.I):
                has_10q = True

        if any(domain.endswith(d) for d in local_filing_domains) or source == "local_disclosure":
            local_filing_count += 1
            has_local_filing = True

        if re.search(r"earnings|conference call|transcript|业绩电话会|电话会纪要", joined, flags=re.I):
            has_earnings_transcript = True

        if any(domain.endswith(d) for d in authoritative_media_domains):
            authoritative_media_count += 1

        normalized_snippet = snippet.strip().lower()
        if (
            len(snippet) >= 40
            and normalized_snippet
            and normalized_snippet != url
            and not normalized_snippet.startswith("http://")
            and not normalized_snippet.startswith("https://")
        ):
            rich_snippet_count += 1

    missing: list[str] = []
    missing_counts = {"critical": 0, "important": 0, "minor": 0}

    def _append_missing(message: str, severity: str) -> None:
        missing.append(message)
        if severity in missing_counts:
            missing_counts[severity] += 1

    if deep_required:
        if profile.get("10k") and not has_10k:
            _append_missing("缺少可识别的 10-K 引用", "critical")
        if profile.get("10q") and not has_10q:
            _append_missing("缺少可识别的 10-Q 引用", "critical")
        if profile.get("local_filing") and not has_local_filing:
            _append_missing("缺少本地市场披露引用（CN/HK）", "critical")
        if profile.get("transcript") and not has_earnings_transcript:
            _append_missing("缺少业绩电话会纪要/Transcript 引用", "important")
        if profile.get("media") and authoritative_media_count <= 0:
            _append_missing("缺少权威媒体交叉引用（Reuters/Bloomberg/WSJ/FT/CNBC/Yahoo）", "important")
        if profile.get("snippets") and rich_snippet_count < 2:
            _append_missing("证据摘录质量不足（多数仅 URL，缺少正文摘录）", "minor")

    return {
        "deep_report_required": deep_required,
        "report_type": report_type,
        "market": report_market,
        "applied_profile": profile,
        "qualified": not missing,
        "missing_requirements": missing,
        "missing_counts": missing_counts,
        "stats": {
            "citation_count": len(citations),
            "sec_filing_count": sec_filing_count,
            "local_filing_count": local_filing_count,
            "authoritative_media_count": authoritative_media_count,
            "rich_snippet_count": rich_snippet_count,
            "has_10k": has_10k,
            "has_10q": has_10q,
            "has_local_filing": has_local_filing,
            "has_earnings_transcript": has_earnings_transcript,
        },
    }

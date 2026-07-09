# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/report_builder.py（WP3 Task5，零行为变更）。
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from backend.report.util import _freshness_hours, _safe_confidence, _safe_str

_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "source",
    "sourceid",
    "utm_campaign",
    "utm_content",
    "utm_id",
    "utm_medium",
    "utm_name",
    "utm_source",
    "utm_term",
}

_FILING_SECTION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\bItem\s+(\d+[A-Za-z]?)\b", flags=re.IGNORECASE),
    re.compile(r"\bNote\s+(\d+[A-Za-z]?)\b", flags=re.IGNORECASE),
    re.compile(r"\bPart\s+([IVX]+)\b", flags=re.IGNORECASE),
]


@dataclass
class _CitationBuild:
    citations: list[dict[str, Any]]
    id_by_url: dict[str, str]
    id_by_internal_key: dict[str, str]

def _detect_filing_section_ref(item: dict[str, Any]) -> str | None:
    text = " ".join(
        [
            _safe_str(item.get("title") or ""),
            _safe_str(item.get("snippet") or ""),
            _safe_str((item.get("metadata") or {}).get("section") if isinstance(item.get("metadata"), dict) else ""),
        ]
    )
    if not text:
        return None
    for pattern in _FILING_SECTION_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        key = pattern.pattern.lower()
        value = m.group(1).upper()
        if "item" in key:
            return f"Item {value}"
        if "note" in key:
            return f"Note {value}"
        if "part" in key:
            return f"Part {value}"
    return None

def _build_filing_section_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    section_map: dict[str, list[str]] = {}
    for item in citations:
        if not isinstance(item, dict):
            continue
        section = _safe_str(item.get("section_ref") or "").strip()
        source_id = _safe_str(item.get("source_id") or "").strip()
        if not section or not source_id:
            continue
        section_map.setdefault(section, [])
        if source_id not in section_map[section]:
            section_map[section].append(source_id)

    ordered = sorted(section_map.items(), key=lambda kv: kv[0])
    return [{"section": section, "source_ids": source_ids} for section, source_ids in ordered]

def _canonicalize_url_for_citation_match(raw_url: str) -> str:
    url = _safe_str(raw_url).strip()
    if not url:
        return ""
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    if not parsed.scheme or not parsed.netloc:
        return url

    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
        if not path:
            path = "/"

    filtered_query: list[tuple[str, str]] = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        clean_key = _safe_str(key).strip()
        if not clean_key:
            continue
        lower_key = clean_key.lower()
        if lower_key.startswith("utm_") or lower_key in _TRACKING_QUERY_KEYS:
            continue
        filtered_query.append((clean_key, _safe_str(value)))
    filtered_query.sort(key=lambda item: (item[0].lower(), item[1]))
    query = urlencode(filtered_query, doseq=True)

    return urlunparse((scheme, netloc, path, "", query, ""))

def _is_suspicious_citation_item(item: dict[str, Any]) -> bool:
    if not isinstance(item, dict):
        return True
    url = _safe_str(item.get("url") or "").strip().lower()
    title = _safe_str(item.get("title") or "").strip().lower()
    snippet = _safe_str(item.get("snippet") or "").strip().lower()
    if not url.startswith(("http://", "https://")):
        return True
    parsed = urlparse(url)
    domain = (parsed.netloc or "").lower().lstrip("www.")
    path = (parsed.path or "").lower()

    if domain == "finnhub.io" and path.startswith("/api/news"):
        return True

    blocked_domains = (
        "tangxin93.com",
        "hinrijv.cc",
        "xqdyzgc.com",
        "yumiok.com",
        "playfulsoul.net",
        "mtevfryb.cc",
        "ewfvsve.cc",
        "maoyanqing.com",
    )
    blocked_tlds = (".cc", ".xyz", ".top", ".vip", ".club", ".porn", ".sex")
    blocked_terms = (
        "成人视频",
        "乱伦",
        "群p",
        "porn",
        "xxx",
        "casino",
        "betting",
    )
    text = " ".join((url, title, snippet))
    if any(domain in url for domain in blocked_domains):
        return True
    if domain and any(domain.endswith(suffix) for suffix in blocked_tlds):
        return True
    if "/tag/" in path and any(token in path for token in ("群", "porn", "xxx", "sex")):
        return True
    if any(term in text for term in blocked_terms):
        return True
    return False

def _build_citations(evidence_pool: list[dict[str, Any]] | None) -> _CitationBuild:
    citations: list[dict[str, Any]] = []
    id_by_url: dict[str, str] = {}
    id_by_internal_key: dict[str, str] = {}
    if not isinstance(evidence_pool, list):
        return _CitationBuild(
            citations=citations,
            id_by_url=id_by_url,
            id_by_internal_key=id_by_internal_key,
        )

    for item in evidence_pool:
        if not isinstance(item, dict):
            continue
        if _is_suspicious_citation_item(item):
            continue
        url = item.get("url")
        if not isinstance(url, str) or not url.strip():
            continue
        url = url.strip()
        canonical_url = _canonicalize_url_for_citation_match(url)
        if url in id_by_url or (canonical_url and canonical_url in id_by_url):
            continue
        source_id = str(len(citations) + 1)
        id_by_url[url] = source_id
        if canonical_url:
            id_by_url[canonical_url] = source_id
        citations.append(
            {
                "source_id": source_id,
                "title": _safe_str(item.get("title") or item.get("source") or url)[:180] or url,
                "url": url,
                "snippet": _safe_str(item.get("snippet") or "")[:400],
                "published_date": _safe_str(item.get("published_date") or ""),
                "confidence": _safe_confidence(item.get("confidence", 0.7)),
                "freshness_hours": _freshness_hours(item.get("published_date")),
                "section_ref": _detect_filing_section_ref(item),
            }
        )
        if len(citations) >= 24:
            break

    return _CitationBuild(
        citations=citations,
        id_by_url=id_by_url,
        id_by_internal_key=id_by_internal_key,
    )

def _normalize_internal_citation_text(value: Any, *, limit: int = 200) -> str:
    text = re.sub(r"\s+", " ", _safe_str(value)).strip().lower()
    return text[:limit]

def _build_internal_citation_key(
    *,
    agent_name: str,
    source: str,
    title: str,
    snippet: str,
    timestamp: str,
) -> str:
    agent_key = _normalize_internal_citation_text(agent_name, limit=64)
    source_key = _normalize_internal_citation_text(source, limit=64)
    title_key = _normalize_internal_citation_text(title, limit=120)
    snippet_key = _normalize_internal_citation_text(snippet, limit=160)
    timestamp_key = _normalize_internal_citation_text(timestamp, limit=64)
    if not any((source_key, title_key, snippet_key, timestamp_key)):
        return ""
    return "|".join([agent_key, source_key, title_key, snippet_key, timestamp_key])

def _build_internal_citation_url(*, agent_name: str, source: str, title: str) -> str:
    seed = "-".join(
        [
            _normalize_internal_citation_text(agent_name, limit=32),
            _normalize_internal_citation_text(source, limit=32),
            _normalize_internal_citation_text(title, limit=48),
        ]
    )
    slug = re.sub(r"[^a-z0-9]+", "-", seed).strip("-")
    if not slug:
        slug = f"agent-{uuid.uuid4().hex[:8]}"
    return f"internal://{slug}"

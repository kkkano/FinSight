# -*- coding: utf-8 -*-
"""RAG ingestion helper（WP3 Task6 机械搬运自 backend/graph/nodes/execute_plan_stub.py 前段，零行为变更）。"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime, timezone
from typing import Any

from backend.rag.layering import build_subject_kb_collection, build_thread_memory_collection, build_thread_working_set_collection, collection_details

_HIGH_RELIABILITY_SOURCE_HINTS = frozenset({
    "sec.gov", "reuters.com", "bloomberg.com", "wsj.com", "ft.com",
})


def _host_env_int(name, default, **kw):
    """宿主 _env_int 延迟解析（execute_plan_node 顶层 import 本模块，直接互 import 成环）。"""
    from backend.graph.nodes.execute_plan_node import _env_int

    return _env_int(name, default, **kw)


def _ttl_hours_for_evidence(*, subject_type: str, evidence_type: str, source: str, confidence: float = 0.0, source_reliability: float = 0.0) -> int:
    """
    RAG v2 TTL policy:
    - filing/research_doc: persistent (no TTL)
    - DeepSearch high-quality (confidence >= 0.7 AND source_reliability >= 0.75): persistent
    - news/selection/search-derived: short-term TTL
    - others: session-ephemeral TTL
    """
    if subject_type in ("filing", "research_doc"):
        return 0

    # E4: DeepSearch high-quality results 鈫?persistent
    if confidence >= 0.7 and source_reliability >= 0.75:
        return 0

    news_ttl = _host_env_int("RAG_V2_NEWS_TTL_HOURS", 24 * 7, min_value=1, max_value=24 * 180)
    ephemeral_ttl = _host_env_int("RAG_V2_EPHEMERAL_TTL_HOURS", 12, min_value=1, max_value=24 * 30)

    source_norm = (source or "").strip().lower()
    evidence_type_norm = (evidence_type or "").strip().lower()
    if evidence_type_norm in ("news", "selection"):
        return news_ttl
    if source_norm in ("news", "selection", "search", "tavily", "exa", "google_news"):
        return news_ttl
    return ephemeral_ttl

def _estimate_source_reliability(url: str) -> float:
    """Estimate source reliability from URL domain (0.0 - 1.0)."""
    if not url:
        return 0.5
    url_lower = url.lower()
    # Check high-reliability domains
    for domain in _HIGH_RELIABILITY_SOURCE_HINTS:
        if domain in url_lower:
            return 0.9
    # Investor relations pages
    if "investor" in url_lower:
        return 0.85
    # Known finance sources
    finance_hints = ("yahoo.com/finance", "cnbc.com", "marketwatch.com", "seekingalpha.com")
    for hint in finance_hints:
        if hint in url_lower:
            return 0.75
    return 0.6

def _build_rag_doc_id(*, thread_id: str, evidence: dict[str, Any], index: int) -> str:
    explicit = str(evidence.get("id") or "").strip()
    if explicit:
        return explicit
    title = str(evidence.get("title") or "").strip()
    url = str(evidence.get("url") or "").strip()
    snippet = str(evidence.get("snippet") or "").strip()
    material = f"{thread_id}|{index}|{title}|{url}|{snippet}".encode("utf-8")
    return hashlib.sha1(material).hexdigest()[:24]

def _sanitize_collection_segment(value: str) -> str:
    import re

    text = (value or "").strip()
    if not text:
        return "unknown"
    normalized = re.sub(r"[^A-Za-z0-9._-]", "_", text)
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "unknown"

def _collection_from_thread_id(thread_id: str) -> str:
    return build_thread_working_set_collection(thread_id)

def _kb_collection_from_subject(subject: dict[str, Any] | None) -> str | None:
    return build_subject_kb_collection(subject if isinstance(subject, dict) else None)

def _memory_collection_from_thread(*, thread_id: str, user_id: str | None = None) -> str:
    return build_thread_memory_collection(thread_id=thread_id, user_id=user_id)

def _normalize_watchlist_items(value: Any, *, limit: int = 12) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        symbol = str(item or '').strip().upper()
        if not symbol or symbol in result:
            continue
        result.append(symbol)
        if len(result) >= limit:
            break
    return result

def _normalize_memory_focus_list(value: Any, *, limit: int = 3) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        normalized = {
            'ticker': str(item.get('ticker') or '').strip().upper(),
            'query': str(item.get('query') or '').strip(),
            'summary': str(item.get('summary') or '').strip(),
            'sentiment': str(item.get('sentiment') or '').strip(),
            'updated_at': str(item.get('updated_at') or '').strip(),
        }
        if not any(normalized.values()):
            continue
        result.append(normalized)
        if len(result) >= limit:
            break
    return result

def _build_memory_context_specs(*, memory_context: dict[str, Any], user_id: str) -> list[dict[str, Any]]:
    # 延迟导入：backend.graph.__init__ 饿加载 runner，模块级 import 会与 execute_plan_node 成环
    from backend.graph.memory_scope import current_thread_focus, user_profile_memory

    if not isinstance(memory_context, dict) or not memory_context:
        return []

    profile = user_profile_memory(memory_context)
    risk_tolerance = str(profile.get("risk_tolerance") or "").strip().lower()
    investment_style = str(profile.get("investment_style") or "").strip().lower()
    watchlist = _normalize_watchlist_items(profile.get("watchlist"))
    last_focus_raw = current_thread_focus(memory_context)
    last_focus_list = _normalize_memory_focus_list([last_focus_raw] if last_focus_raw else [], limit=1)
    last_focus = last_focus_list[0] if last_focus_list else None
    recent_focuses: list[dict[str, Any]] = []

    specs: list[dict[str, Any]] = []
    if watchlist or risk_tolerance not in {"", "medium"} or investment_style not in {"", "balanced"}:
        profile_lines = [
            "memory_kind: profile",
            f"user_id: {user_id}",
            f"risk_tolerance: {risk_tolerance or 'medium'}",
            f"investment_style: {investment_style or 'balanced'}",
        ]
        if watchlist:
            profile_lines.append(f"watchlist: {', '.join(watchlist)}")
        specs.append({
            "source_id": "memdoc:profile",
            "title": "Memory Profile",
            "content": "\n".join(profile_lines),
            "metadata": {
                "memory_kind": "profile",
                "watchlist": watchlist,
            },
        })

    if watchlist:
        specs.append({
            "source_id": "memdoc:watchlist",
            "title": "Memory Watchlist",
            "content": "\n".join([
                "memory_kind: watchlist",
                f"user_id: {user_id}",
                f"watchlist: {', '.join(watchlist)}",
            ]),
            "metadata": {
                "memory_kind": "watchlist",
                "watchlist": watchlist,
            },
        })

    if last_focus:
        ticker = str(last_focus.get("ticker") or "").strip().upper()
        focus_lines = [
            "memory_kind: last_focus",
            f"user_id: {user_id}",
        ]
        if ticker:
            focus_lines.append(f"ticker: {ticker}")
        if last_focus.get("query"):
            focus_lines.append(f"query: {last_focus['query']}")
        if last_focus.get("summary"):
            focus_lines.append(f"summary: {last_focus['summary']}")
        if last_focus.get("sentiment"):
            focus_lines.append(f"sentiment: {last_focus['sentiment']}")
        if last_focus.get("updated_at"):
            focus_lines.append(f"updated_at: {last_focus['updated_at']}")
        specs.append({
            "source_id": "memdoc:last_focus",
            "title": f"Memory Last Focus {ticker or user_id}",
            "content": "\n".join(focus_lines),
            "metadata": {
                "memory_kind": "last_focus",
                "ticker": ticker or None,
                "query": last_focus.get("query") or None,
                "sentiment": last_focus.get("sentiment") or None,
                "updated_at": last_focus.get("updated_at") or None,
            },
        })

    seen_recent_keys: set[tuple[str, str]] = set()
    if last_focus:
        seen_recent_keys.add((str(last_focus.get("ticker") or "").strip().upper(), str(last_focus.get("query") or "").strip()))

    for index, focus in enumerate(recent_focuses, start=1):
        ticker = str(focus.get("ticker") or "").strip().upper()
        query = str(focus.get("query") or "").strip()
        focus_key = (ticker, query)
        if focus_key in seen_recent_keys:
            continue
        seen_recent_keys.add(focus_key)
        recent_lines = [
            "memory_kind: recent_focus",
            f"user_id: {user_id}",
            f"recent_focus_rank: {index}",
        ]
        if ticker:
            recent_lines.append(f"ticker: {ticker}")
        if query:
            recent_lines.append(f"query: {query}")
        if focus.get("summary"):
            recent_lines.append(f"summary: {focus['summary']}")
        if focus.get("sentiment"):
            recent_lines.append(f"sentiment: {focus['sentiment']}")
        if focus.get("updated_at"):
            recent_lines.append(f"updated_at: {focus['updated_at']}")
        specs.append({
            "source_id": f"memdoc:recent_focus:{index}",
            "title": f"Memory Recent Focus {index} {ticker or user_id}",
            "content": "\n".join(recent_lines),
            "metadata": {
                "memory_kind": "recent_focus",
                "memory_rank": index,
                "ticker": ticker or None,
                "query": query or None,
                "sentiment": focus.get("sentiment") or None,
                "updated_at": focus.get("updated_at") or None,
            },
        })

    return [spec for spec in specs if str(spec.get("content") or "").strip()]
    return [spec for spec in specs if str(spec.get("content") or "").strip()]

def _resolve_hit_layer(hit: dict[str, Any]) -> str:
    metadata = hit.get('metadata') if isinstance(hit.get('metadata'), dict) else {}
    collection = str(hit.get('collection') or metadata.get('collection') or '').strip()
    details = collection_details(collection)
    return str(hit.get('layer') or metadata.get('layer') or details.get('layer') or 'unknown').strip().lower() or 'unknown'

def _summarize_layer_hits(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    total_matches = 0

    for hit in hits or []:
        metadata = hit.get('metadata') if isinstance(hit.get('metadata'), dict) else {}
        matched_collections_raw = hit.get('matched_collections') or metadata.get('matched_collections')
        collection_pairs: list[tuple[str, str]] = []
        if isinstance(matched_collections_raw, list):
            for item in matched_collections_raw:
                collection = str(item or '').strip()
                if not collection:
                    continue
                details = collection_details(collection)
                layer = str(details.get('layer') or 'unknown').strip().lower() or 'unknown'
                collection_pairs.append((layer, collection))

        if not collection_pairs:
            collection = str(hit.get('collection') or metadata.get('collection') or '').strip()
            collection_pairs.append((_resolve_hit_layer(hit), collection))

        title = str(hit.get('title') or hit.get('source_id') or '').strip()
        seen_layers_for_hit: set[str] = set()
        for layer, collection in collection_pairs:
            normalized_layer = str(layer or 'unknown').strip().lower() or 'unknown'
            bucket = buckets.setdefault(normalized_layer, {
                'layer': normalized_layer,
                'count': 0,
                'collections': [],
                'sample_titles': [],
            })
            if normalized_layer not in seen_layers_for_hit:
                bucket['count'] += 1
                total_matches += 1
                seen_layers_for_hit.add(normalized_layer)
            if collection and collection not in bucket['collections']:
                bucket['collections'].append(collection)
            if title and title not in bucket['sample_titles'] and len(bucket['sample_titles']) < 3:
                bucket['sample_titles'].append(title)

    total = max(1, total_matches)
    items = []
    for layer, bucket in buckets.items():
        items.append({
            'layer': layer,
            'count': int(bucket['count']),
            'share': float(bucket['count']) / float(total),
            'collections': bucket['collections'],
            'sample_titles': bucket['sample_titles'],
        })
    return sorted(items, key=lambda item: (-int(item['count']), str(item['layer'])))

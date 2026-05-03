# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import re
from typing import Any

LAYER_MEMORY = "memory"
LAYER_WORKING_SET = "ws"
LAYER_KNOWLEDGE_BASE = "kb"


def _sanitize_segment(value: str | None) -> str:
    text = str(value or "").strip()
    if not text:
        return "unknown"
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._-")
    return text or "unknown"


def normalize_ticker(value: str | None) -> str:
    return _sanitize_segment(str(value or "").strip().upper() or "unknown")


def build_thread_memory_collection(*, thread_id: str | None, user_id: str | None = None) -> str:
    raw = str(thread_id or user_id or "").strip()
    parts = [segment for segment in raw.split(":") if str(segment or "").strip()]
    if len(parts) == 3:
        tenant, user, thread = (_sanitize_segment(part) for part in parts)
        return f"mem:thread:{tenant}:{user}:{thread}"
    return f"mem:thread:{_sanitize_segment(raw)}"


def build_thread_working_set_collection(thread_id: str | None) -> str:
    raw = str(thread_id or "").strip()
    parts = [segment for segment in raw.split(":") if str(segment or "").strip()]
    if len(parts) == 3:
        tenant, user, thread = (_sanitize_segment(part) for part in parts)
        return f"ws:thread:{tenant}:{user}:{thread}"
    return f"ws:thread:{_sanitize_segment(raw)}"


def build_run_working_set_collection(run_id: str | None) -> str:
    return f"ws:run:{_sanitize_segment(run_id)}"


def build_deepsearch_working_set_collection(*, query: str, ticker: str) -> str:
    normalized_ticker = _sanitize_segment((ticker or "unknown").strip().lower() or "unknown")
    seed = f"{normalized_ticker}::{str(query or '').strip()}"
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()[:16]
    return f"ws:deepsearch:{normalized_ticker}:{digest}"


def build_stock_kb_collection(ticker: str | None) -> str | None:
    normalized = normalize_ticker(ticker)
    if normalized == "UNKNOWN":
        return None
    return f"kb:stock:{normalized}"


def build_subject_kb_collection(subject: dict[str, Any] | None) -> str | None:
    payload = subject if isinstance(subject, dict) else {}
    tickers = payload.get("tickers") if isinstance(payload.get("tickers"), list) else []
    for ticker in tickers:
        normalized = normalize_ticker(str(ticker or ""))
        if normalized != "UNKNOWN":
            return f"kb:stock:{normalized}"
    subject_type = str(payload.get("subject_type") or "").strip().lower()
    if subject_type == "macro":
        return "kb:macro:global"
    return None


def collection_details(collection: str | None) -> dict[str, Any]:
    raw = str(collection or "").strip()
    result: dict[str, Any] = {
        "collection": raw,
        "layer": "unknown",
        "collection_kind": "unknown",
        "entity_scope": None,
        "entity_key": None,
        "is_legacy": False,
    }
    if not raw:
        return result

    parts = raw.split(":")
    if parts[:2] == ["mem", "thread"]:
        result.update({"layer": LAYER_MEMORY, "collection_kind": "thread_memory"})
        if len(parts) >= 5:
            result["entity_scope"] = "thread"
            result["entity_key"] = ":".join(parts[2:5])
        return result
    if parts[:2] == ["ws", "thread"]:
        result.update({"layer": LAYER_WORKING_SET, "collection_kind": "thread_working_set"})
        if len(parts) >= 5:
            result["entity_scope"] = "thread"
            result["entity_key"] = ":".join(parts[2:5])
        return result
    if parts[:2] == ["ws", "run"]:
        result.update({
            "layer": LAYER_WORKING_SET,
            "collection_kind": "run_working_set",
            "entity_scope": "run",
            "entity_key": parts[2] if len(parts) >= 3 else None,
        })
        return result
    if parts[:2] == ["ws", "deepsearch"]:
        result.update({"layer": LAYER_WORKING_SET, "collection_kind": "deepsearch_working_set", "entity_scope": "stock"})
        if len(parts) >= 3:
            result["entity_key"] = str(parts[2] or "").upper() or None
        return result
    if parts[:2] == ["kb", "stock"]:
        result.update({"layer": LAYER_KNOWLEDGE_BASE, "collection_kind": "stock_kb", "entity_scope": "stock"})
        if len(parts) >= 3:
            result["entity_key"] = str(parts[2] or "").upper() or None
        return result
    if parts[:2] == ["kb", "theme"]:
        result.update({"layer": LAYER_KNOWLEDGE_BASE, "collection_kind": "theme_kb", "entity_scope": "theme", "entity_key": parts[2] if len(parts) >= 3 else None})
        return result
    if parts[:2] == ["kb", "macro"]:
        result.update({"layer": LAYER_KNOWLEDGE_BASE, "collection_kind": "macro_kb", "entity_scope": "macro", "entity_key": parts[2] if len(parts) >= 3 else None})
        return result
    if parts and parts[0] == "session":
        result.update({"layer": LAYER_WORKING_SET, "collection_kind": "legacy_session", "is_legacy": True})
        if len(parts) >= 4 and parts[1] == "deepsearch":
            result["collection_kind"] = "legacy_deepsearch"
            result["entity_scope"] = "stock"
            result["entity_key"] = str(parts[2] or "").upper() or None
        return result
    return result


def enrich_metadata(
    metadata: dict[str, Any] | None,
    *,
    collection: str | None,
    layer: str | None = None,
    entity_scope: str | None = None,
    entity_key: str | None = None,
    ingest_source: str | None = None,
    promotion_status: str | None = None,
    parent_collection: str | None = None,
    parent_run_id: str | None = None,
    doc_fingerprint: str | None = None,
) -> dict[str, Any]:
    merged = dict(metadata or {})
    details = collection_details(collection)
    merged.setdefault("collection", collection)
    merged["layer"] = str(layer or merged.get("layer") or details.get("layer") or LAYER_WORKING_SET)
    if entity_scope or details.get("entity_scope"):
        merged["entity_scope"] = entity_scope or details.get("entity_scope")
    if entity_key or details.get("entity_key"):
        merged["entity_key"] = entity_key or details.get("entity_key")
    if ingest_source:
        merged["ingest_source"] = ingest_source
    if promotion_status:
        merged["promotion_status"] = promotion_status
    if parent_collection:
        merged["parent_collection"] = parent_collection
    if parent_run_id:
        merged["parent_run_id"] = parent_run_id
    if doc_fingerprint:
        merged["doc_fingerprint"] = doc_fingerprint
    merged.setdefault("collection_kind", details.get("collection_kind"))
    return merged


def compute_doc_fingerprint(
    *,
    title: str | None = None,
    url: str | None = None,
    content: str | None = None,
    source_id: str | None = None,
) -> str:
    payload = "\n".join(
        [
            str(title or "").strip().lower(),
            str(url or "").strip().lower(),
            str(source_id or "").strip().lower(),
            str(content or "").strip()[:1000].lower(),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_kb_vector_source_id(*, doc_fingerprint: str, chunk_index: int | None = None) -> str:
    suffix = f":{int(chunk_index)}" if chunk_index is not None else ""
    return f"kbdoc:{doc_fingerprint[:24]}{suffix}"


def is_long_term_candidate(
    *,
    source_type: str | None = None,
    source: str | None = None,
    metadata: dict[str, Any] | None = None,
    title: str | None = None,
    url: str | None = None,
) -> bool:
    normalized_type = str(source_type or (metadata or {}).get("type") or "").strip().lower()
    normalized_source = str(source or "").strip().lower()
    normalized_title = str(title or "").strip().lower()
    normalized_url = str(url or "").strip().lower()
    if normalized_type in {"filing", "transcript", "research", "research_doc", "annual_report", "quarterly_report"}:
        return True
    if normalized_source in {"filing", "transcript", "sec", "investor_relations", "research"}:
        return True
    if any(token in normalized_url for token in ("sec.gov", "investor", "earnings", "annual-report", "quarterly")):
        return True
    if any(token in normalized_title for token in ("10-k", "10-q", "earnings call", "annual report", "quarterly report", "investor presentation")):
        return True
    return False


def preferred_retrieval_collections(
    *,
    memory_collection: str | None = None,
    working_set_collection: str | None,
    kb_collection: str | None = None,
) -> list[str]:
    ordered: list[str] = []
    for candidate in (memory_collection, working_set_collection, kb_collection):
        value = str(candidate or "").strip()
        if value and value not in ordered:
            ordered.append(value)
    return ordered

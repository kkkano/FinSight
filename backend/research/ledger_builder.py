# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import asdict, is_dataclass
import hashlib
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel

from backend.research.evidence_ledger import (
    EvidenceLedger,
    SourceRef,
    from_agent_output,
    merge_ledgers,
    stable_id,
)


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, BaseModel):
        try:
            return value.model_dump(mode="json")
        except Exception:
            return {}
    if is_dataclass(value):
        try:
            return asdict(value)
        except Exception:
            return {}
    return {}


def _get_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = _clean_text(value)
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item) for item in value if _clean_text(item)]


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _clamp(value: Any, default: float = 0.5) -> float:
    parsed = _safe_float(value, default)
    return max(0.0, min(1.0, parsed))


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return max(0.0, _safe_float(value, 0.0))


def _first_text(*values: Any) -> str:
    for value in values:
        cleaned = _clean_text(value)
        if cleaned:
            return cleaned
    return ""


def _normalise_url(url: Any) -> str:
    raw = _clean_text(url)
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except Exception:
        return raw.rstrip("/")
    if not parts.scheme or not parts.netloc:
        return raw.rstrip("/")
    path = parts.path.rstrip("/")
    if parts.path == "/" and not path:
        path = "/"
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)), doseq=True)
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def _source_key(*, url: Any, title: Any, source: Any, snippet: Any, published_date: Any) -> str:
    normalised_url = _normalise_url(url)
    if normalised_url:
        return f"url:{normalised_url}"
    material = "|".join(
        [
            _clean_text(title).lower(),
            _clean_text(source).lower(),
            _clean_text(snippet),
            _clean_text(published_date),
        ]
    )
    return f"fallback:{hashlib.sha1(material.encode('utf-8')).hexdigest()}"


def _source_id_from_key(key: str) -> str:
    return f"source:{hashlib.sha1(key.encode('utf-8')).hexdigest()[:16]}"


def _source_id_for_raw(
    item: Any,
    *,
    title: Any,
    url: Any,
    source: Any,
    published_date: Any,
) -> str:
    snippet = _first_text(
        _get_value(item, "snippet"),
        _get_value(item, "summary"),
        _get_value(item, "text"),
        _get_value(item, "content"),
        _get_value(item, "description"),
        _get_value(item, "chunk_text"),
    )
    key = _source_key(url=url, title=title, source=source, snippet=snippet, published_date=published_date)
    return _source_id_from_key(key)


def _source_id_for_source(source: SourceRef) -> str:
    if source.url:
        key = _source_key(
            url=source.url,
            title=source.title,
            source=source.source,
            snippet="",
            published_date=source.published_date,
        )
        return _source_id_from_key(key)
    if source.source_id.startswith("source:"):
        return source.source_id
    key = _source_key(
        url=None,
        title=source.title,
        source=source.source,
        snippet="",
        published_date=source.published_date,
    )
    return _source_id_from_key(key)


def _source_key_for_source(source: SourceRef) -> str:
    if source.url:
        return _source_key(
            url=source.url,
            title=source.title,
            source=source.source,
            snippet="",
            published_date=source.published_date,
        )
    return source.source_id


def _source_from_mapping(item: Any, *, default_source: str, index: int) -> SourceRef | None:
    mapping = _as_dict(item)
    meta = _as_dict(mapping.get("meta") or mapping.get("metadata"))
    title = _first_text(
        mapping.get("title"),
        mapping.get("headline"),
        meta.get("title"),
        mapping.get("source_id"),
        mapping.get("id"),
        f"{default_source} source {index + 1}",
    )
    url = _first_text(mapping.get("url"), mapping.get("final_url"), meta.get("url")) or None
    source = _first_text(
        mapping.get("source"),
        mapping.get("source_name"),
        meta.get("source"),
        meta.get("source_name"),
        default_source,
    )
    published_date = _first_text(
        mapping.get("published_date"),
        mapping.get("published_at"),
        mapping.get("datetime"),
        mapping.get("timestamp"),
        meta.get("published_date"),
    ) or None
    as_of = _first_text(mapping.get("as_of"), meta.get("as_of")) or None
    reliability = mapping.get("reliability", meta.get("reliability", None))
    if reliability is None:
        reliability = mapping.get("confidence", meta.get("confidence", 0.5))
    freshness_hours = _optional_float(mapping.get("freshness_hours", meta.get("freshness_hours")))
    layer = _first_text(mapping.get("layer"), meta.get("layer")) or None
    collection = _first_text(mapping.get("collection"), meta.get("collection")) or None

    source_id = _source_id_for_raw(
        mapping,
        title=title,
        url=url,
        source=source,
        published_date=published_date,
    )

    if not any([title, url, _first_text(mapping.get("snippet"), mapping.get("text"), mapping.get("content"))]):
        return None

    return SourceRef(
        source_id=source_id,
        title=title,
        url=url,
        source=source,
        published_date=published_date,
        as_of=as_of,
        reliability=_clamp(reliability),
        freshness_hours=freshness_hours,
        layer=layer,
        collection=collection,
    )


def _rag_source_from_hit(hit: Any, *, index: int) -> SourceRef | None:
    mapping = _as_dict(hit)
    if not mapping:
        return None
    metadata = _as_dict(mapping.get("metadata"))
    chunk_id = _first_text(mapping.get("chunk_id"), metadata.get("chunk_id"))
    title = _first_text(
        mapping.get("title"),
        metadata.get("title"),
        mapping.get("source_id"),
        metadata.get("source_id"),
        chunk_id,
        f"rag source {index + 1}",
    )
    url = _first_text(mapping.get("url"), metadata.get("url")) or None
    source = _first_text(
        mapping.get("source"),
        mapping.get("source_name"),
        metadata.get("source"),
        metadata.get("source_name"),
        "rag",
    )
    published_date = _first_text(
        mapping.get("published_date"),
        mapping.get("published_at"),
        mapping.get("timestamp"),
        metadata.get("published_date"),
    ) or None
    layer = _first_text(mapping.get("layer"), metadata.get("layer")) or None
    collection = _first_text(mapping.get("collection"), metadata.get("collection")) or None
    snippet = _first_text(
        mapping.get("snippet"),
        mapping.get("content"),
        mapping.get("text"),
        mapping.get("chunk_text"),
        metadata.get("chunk_text"),
    )
    reliability = mapping.get("reliability", metadata.get("reliability", None))
    if reliability is None:
        reliability = mapping.get("confidence", mapping.get("score", metadata.get("confidence", 0.65)))

    source_id = _source_id_from_key(
        _source_key(
            url=url,
            title=title,
            source=source,
            snippet=snippet or chunk_id,
            published_date=published_date,
        )
    )
    return SourceRef(
        source_id=source_id,
        title=title,
        url=url,
        source=source,
        published_date=published_date,
        as_of=_first_text(mapping.get("as_of"), metadata.get("as_of")) or None,
        reliability=_clamp(reliability, 0.65),
        freshness_hours=_optional_float(mapping.get("freshness_hours", metadata.get("freshness_hours"))),
        layer=layer,
        collection=collection,
    )


def _iter_step_results(step_results: Any) -> list[tuple[str, Any]]:
    if isinstance(step_results, dict):
        return [(str(step_id), item) for step_id, item in step_results.items()]
    if isinstance(step_results, list):
        return [(str(index), item) for index, item in enumerate(step_results)]
    return []


def _task_ids_from_step(step_id: str, item: Any) -> list[str]:
    values: list[str] = []
    mapping = _as_dict(item)
    values.extend(_list_of_strings(mapping.get("task_ids")))
    single = _clean_text(mapping.get("task_id"))
    if single:
        values.append(single)
    if not values and step_id:
        values.append(step_id)
    return _dedupe_strings(values)


def _step_output(item: Any) -> Any:
    mapping = _as_dict(item)
    if "output" in mapping:
        return mapping.get("output")
    return item


def _looks_skipped_or_failed(item: Any, output: Any) -> bool:
    item_mapping = _as_dict(item)
    output_mapping = _as_dict(output)
    if output_mapping.get("skipped") is True:
        return True
    status = _clean_text(item_mapping.get("status") or output_mapping.get("status")).lower()
    reason = _clean_text(item_mapping.get("status_reason")).lower()
    if status in {"error", "failed", "cancelled"}:
        return True
    if reason in {"error", "failed", "cancelled"}:
        return True
    if output_mapping.get("error") and not (
        output_mapping.get("summary") or output_mapping.get("claims") or output_mapping.get("evidence")
    ):
        return True
    return False


def _ledger_from_embedded_payload(output: Any, query: str, subject: dict[str, Any]) -> EvidenceLedger | None:
    payload = _get_value(output, "ledger")
    if not payload:
        return None
    if isinstance(payload, EvidenceLedger):
        return payload
    if not isinstance(payload, dict):
        return None
    merged = dict(payload)
    merged.setdefault("query", query)
    merged.setdefault("subject", subject)
    merged.setdefault("ledger_id", stable_id("ledger", query, subject, "embedded", merged.get("claims"), merged.get("sources")))
    try:
        return EvidenceLedger.model_validate(merged)
    except Exception:
        return None


def _canonicalise_agent_ledger_sources(ledger: EvidenceLedger, output: Any) -> EvidenceLedger:
    evidence_items = _get_value(output, "evidence", [])
    if not isinstance(evidence_items, list):
        evidence_items = []

    id_map: dict[str, str] = {}
    sources: list[SourceRef] = []
    for index, source in enumerate(ledger.sources):
        raw_item = evidence_items[index] if index < len(evidence_items) else {}
        source_id = _source_id_for_raw(
            raw_item,
            title=source.title,
            url=source.url,
            source=source.source,
            published_date=source.published_date,
        )
        id_map[source.source_id] = source_id
        sources.append(source.model_copy(update={"source_id": source_id}))

    claims = []
    for claim in ledger.claims:
        evidence_ids = _dedupe_strings([id_map.get(source_id, source_id) for source_id in claim.evidence_ids])
        claims.append(claim.model_copy(update={"evidence_ids": evidence_ids}))
    return ledger.model_copy(update={"sources": sources, "claims": claims})


def _dedupe_ledger_sources(ledger: EvidenceLedger) -> EvidenceLedger:
    sources_by_id: dict[str, SourceRef] = {}
    id_map: dict[str, str] = {}
    for source in ledger.sources:
        canonical_id = _source_id_for_source(source)
        id_map[source.source_id] = canonical_id
        candidate = source.model_copy(update={"source_id": canonical_id})
        existing = sources_by_id.get(canonical_id)
        if existing is None:
            sources_by_id[canonical_id] = candidate
            continue
        updates: dict[str, Any] = {}
        for field in ("title", "url", "source", "published_date", "as_of", "layer", "collection"):
            if not getattr(existing, field) and getattr(candidate, field):
                updates[field] = getattr(candidate, field)
        if candidate.reliability > existing.reliability:
            updates["reliability"] = candidate.reliability
        if existing.freshness_hours is None and candidate.freshness_hours is not None:
            updates["freshness_hours"] = candidate.freshness_hours
        if updates:
            sources_by_id[canonical_id] = existing.model_copy(update=updates)

    claims = []
    for claim in ledger.claims:
        evidence_ids = _dedupe_strings([id_map.get(source_id, source_id) for source_id in claim.evidence_ids])
        claims.append(claim.model_copy(update={"evidence_ids": evidence_ids}))
    return ledger.model_copy(update={"sources": list(sources_by_id.values()), "claims": claims})


def _resolve_query(state: Any, artifacts: dict[str, Any]) -> str:
    state_dict = _as_dict(state)
    plan_ir = _as_dict(state_dict.get("plan_ir"))
    return _first_text(state_dict.get("query"), artifacts.get("query"), plan_ir.get("goal"))


def _resolve_subject(state: Any) -> dict[str, Any]:
    state_dict = _as_dict(state)
    subject = _as_dict(state_dict.get("subject"))
    if subject:
        return subject
    plan_ir = _as_dict(state_dict.get("plan_ir"))
    return _as_dict(plan_ir.get("subject"))


def extract_agent_ledgers(step_results: Any, query: str, subject: dict[str, Any]) -> list[EvidenceLedger]:
    ledgers: list[EvidenceLedger] = []
    for step_id, item in _iter_step_results(step_results):
        output = _step_output(item)
        if output is None or _looks_skipped_or_failed(item, output):
            continue
        task_ids = _task_ids_from_step(step_id, item)
        ledger = _ledger_from_embedded_payload(output, query, subject)
        if ledger is None:
            try:
                ledger = from_agent_output(output, query=query, subject=subject, task_ids=task_ids)
            except Exception:
                continue
        ledger = _canonicalise_agent_ledger_sources(ledger, output)
        if ledger.claims or ledger.sources:
            ledgers.append(ledger)
    return ledgers


def extract_pool_sources(evidence_pool: Any) -> list[SourceRef]:
    if not isinstance(evidence_pool, list):
        return []
    sources: list[SourceRef] = []
    for index, item in enumerate(evidence_pool):
        source = _source_from_mapping(item, default_source="evidence_pool", index=index)
        if source is not None:
            sources.append(source)
    return sources


def extract_rag_sources(rag_context: Any) -> list[SourceRef]:
    if not isinstance(rag_context, list):
        return []
    sources: list[SourceRef] = []
    for index, hit in enumerate(rag_context):
        source = _rag_source_from_hit(hit, index=index)
        if source is not None:
            sources.append(source)
    return sources


def attach_pool_sources_to_claims(ledger: EvidenceLedger, pool_sources: list[SourceRef]) -> EvidenceLedger:
    if not pool_sources:
        return ledger

    source_key_by_id = {source.source_id: _source_key_for_source(source) for source in ledger.sources}
    pool_key_by_id = {source.source_id: _source_key_for_source(source) for source in pool_sources}
    claims = []
    for claim in ledger.claims:
        evidence_ids = list(claim.evidence_ids)
        evidence_keys = {source_key_by_id.get(source_id, source_id) for source_id in evidence_ids}
        if evidence_ids:
            for source in pool_sources:
                if pool_key_by_id[source.source_id] in evidence_keys:
                    evidence_ids.append(source.source_id)
        else:
            evidence_ids.extend(source.source_id for source in pool_sources)
        claims.append(claim.model_copy(update={"evidence_ids": _dedupe_strings(evidence_ids)}))

    return ledger.model_copy(update={"sources": [*pool_sources, *ledger.sources], "claims": claims})


def build_ledger_from_artifacts(state: Any, artifacts: Any) -> dict[str, Any]:
    artifact_dict = artifacts if isinstance(artifacts, dict) else {}
    query = _resolve_query(state, artifact_dict)
    subject = _resolve_subject(state)

    agent_ledgers = extract_agent_ledgers(artifact_dict.get("step_results"), query, subject)
    if agent_ledgers:
        ledger = merge_ledgers(query, subject, agent_ledgers)
    else:
        ledger = EvidenceLedger(
            ledger_id=stable_id("ledger", query, subject, "execution_artifacts"),
            query=query,
            subject=subject,
        )

    pool_sources = extract_pool_sources(artifact_dict.get("evidence_pool"))
    ledger = attach_pool_sources_to_claims(ledger, pool_sources)

    rag_sources = extract_rag_sources(artifact_dict.get("rag_context"))
    if rag_sources:
        ledger = ledger.model_copy(update={"sources": [*ledger.sources, *rag_sources]})

    ledger = _dedupe_ledger_sources(ledger)
    return ledger.model_dump(mode="json")


__all__ = [
    "attach_pool_sources_to_claims",
    "build_ledger_from_artifacts",
    "extract_agent_ledgers",
    "extract_pool_sources",
    "extract_rag_sources",
]

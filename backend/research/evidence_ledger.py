# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


Stance = Literal["bull", "bear", "neutral", "risk", "unknown"]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
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


def _list_of_strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


def _list_of_dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            result.append(dict(item))
        elif str(item or "").strip():
            result.append({"target": str(item).strip()})
    return result


def _safe_float(value: Any, default: float) -> float:
    try:
        result = float(value)
    except Exception:
        return default
    return result


def _clamp(value: Any, default: float = 0.5) -> float:
    result = _safe_float(value, default)
    return max(0.0, min(1.0, result))


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def _normalise_for_id(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        try:
            return asdict(value)
        except Exception:
            return str(value)
    if isinstance(value, dict):
        return {str(k): _normalise_for_id(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple, set)):
        return [_normalise_for_id(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def stable_id(prefix: str, *parts: Any) -> str:
    """基于稳定输入生成短 ID，避免把完整原文塞进跨模块契约。"""
    safe_prefix = _clean_text(prefix).replace(" ", "_") or "id"
    payload = json.dumps(_normalise_for_id(parts), ensure_ascii=False, sort_keys=True, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]
    return f"{safe_prefix}:{digest}"


class SourceRef(BaseModel):
    source_id: str
    title: str = ""
    url: str | None = None
    source: str = "unknown"
    published_date: str | None = None
    as_of: str | None = None
    reliability: float = Field(default=0.5, ge=0.0, le=1.0)
    freshness_hours: float | None = Field(default=None, ge=0.0)
    layer: str | None = None
    collection: str | None = None

    @field_validator("source_id")
    @classmethod
    def _source_id_required(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("source_id must not be empty")
        return cleaned

    @field_validator("title", "source", mode="before")
    @classmethod
    def _strip_optional_text(cls, value: Any) -> str:
        return _clean_text(value)

    @field_validator("url", "published_date", "as_of", "layer", "collection", mode="before")
    @classmethod
    def _strip_nullable_text(cls, value: Any) -> str | None:
        cleaned = _clean_text(value)
        return cleaned or None


class ResearchClaim(BaseModel):
    claim_id: str
    claim: str
    stance: Stance = "unknown"
    evidence_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    agent_name: str = ""
    task_ids: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @field_validator("claim_id")
    @classmethod
    def _claim_id_required(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("claim_id must not be empty")
        return cleaned

    @field_validator("claim")
    @classmethod
    def _claim_required(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("claim must not be empty")
        return cleaned

    @field_validator("agent_name", mode="before")
    @classmethod
    def _strip_agent_name(cls, value: Any) -> str:
        return _clean_text(value)

    @field_validator("evidence_ids", "task_ids", "limitations", mode="before")
    @classmethod
    def _normalise_string_lists(cls, value: Any) -> list[str]:
        return _dedupe_strings(_list_of_strings(value))


class EvidenceLedger(BaseModel):
    ledger_id: str
    query: str
    subject: dict[str, Any]
    claims: list[ResearchClaim] = Field(default_factory=list)
    sources: list[SourceRef] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    contradictions: list[dict[str, Any] | str] = Field(default_factory=list)
    coverage_targets: list[dict[str, Any]] = Field(default_factory=list)
    created_at: str = Field(default_factory=_utc_now_iso)

    @field_validator("ledger_id")
    @classmethod
    def _ledger_id_required(cls, value: str) -> str:
        cleaned = _clean_text(value)
        if not cleaned:
            raise ValueError("ledger_id must not be empty")
        return cleaned

    @field_validator("query", mode="before")
    @classmethod
    def _strip_context_text(cls, value: Any) -> str:
        return _clean_text(value)

    @field_validator("subject", mode="before")
    @classmethod
    def _normalise_subject(cls, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return dict(value)
        cleaned = _clean_text(value)
        return {"value": cleaned} if cleaned else {}

    @field_validator("uncertainties", mode="before")
    @classmethod
    def _normalise_context_lists(cls, value: Any) -> list[str]:
        return _dedupe_strings(_list_of_strings(value))

    @field_validator("coverage_targets", mode="before")
    @classmethod
    def _normalise_coverage_targets(cls, value: Any) -> list[dict[str, Any]]:
        return _list_of_dicts(value)


def source_from_evidence_item(item: Any, agent_name: str, index: int) -> SourceRef:
    meta = _as_dict(_get_value(item, "meta", {}))
    title = (
        _clean_text(_get_value(item, "title"))
        or _clean_text(meta.get("title"))
        or _clean_text(_get_value(item, "source"))
        or f"{agent_name or 'agent'} source {index + 1}"
    )
    url = _clean_text(_get_value(item, "url")) or _clean_text(meta.get("url")) or None
    source = _clean_text(_get_value(item, "source")) or _clean_text(meta.get("source")) or _clean_text(agent_name) or "unknown"
    published_date = (
        _clean_text(_get_value(item, "published_date"))
        or _clean_text(meta.get("published_date"))
        or _clean_text(_get_value(item, "timestamp"))
        or None
    )
    as_of = _clean_text(_get_value(item, "as_of")) or _clean_text(meta.get("as_of")) or None
    explicit_id = (
        _clean_text(_get_value(item, "source_id"))
        or _clean_text(meta.get("source_id"))
        or _clean_text(_get_value(item, "id"))
        or _clean_text(meta.get("id"))
    )
    reliability = meta.get("reliability", _get_value(item, "reliability", None))
    if reliability is None:
        reliability = _get_value(item, "confidence", meta.get("confidence", 0.5))

    freshness = meta.get("freshness_hours", _get_value(item, "freshness_hours", None))
    freshness_hours = None if freshness in (None, "") else max(0.0, _safe_float(freshness, 0.0))

    return SourceRef(
        source_id=explicit_id or stable_id("source", agent_name, index, url, title, source),
        title=title,
        url=url,
        source=source,
        published_date=published_date,
        as_of=as_of,
        reliability=_clamp(reliability),
        freshness_hours=freshness_hours,
        layer=_clean_text(_get_value(item, "layer")) or _clean_text(meta.get("layer")) or None,
        collection=_clean_text(_get_value(item, "collection")) or _clean_text(meta.get("collection")) or None,
    )


def claim_from_summary(
    summary: str,
    source_ids: list[str],
    agent_name: str,
    confidence: float,
    task_ids: list[str],
) -> ResearchClaim:
    cleaned_summary = _clean_text(summary)
    return ResearchClaim(
        claim_id=stable_id("claim", agent_name, cleaned_summary, source_ids, task_ids),
        claim=cleaned_summary,
        stance="unknown",
        evidence_ids=source_ids,
        confidence=_clamp(confidence),
        agent_name=agent_name,
        task_ids=task_ids,
        limitations=[],
    )


def _claim_from_payload(
    payload: dict[str, Any],
    *,
    default_source_ids: list[str],
    agent_name: str,
    confidence: float,
    task_ids: list[str],
) -> ResearchClaim | None:
    claim_text = _clean_text(payload.get("claim") or payload.get("summary") or payload.get("text"))
    if not claim_text:
        return None
    evidence_ids = _dedupe_strings(_list_of_strings(payload.get("evidence_ids"))) or default_source_ids
    claim_task_ids = _dedupe_strings(_list_of_strings(payload.get("task_ids"))) or task_ids
    stance = _clean_text(payload.get("stance")).lower()
    if stance not in {"bull", "bear", "neutral", "risk", "unknown"}:
        stance = "unknown"
    return ResearchClaim(
        claim_id=_clean_text(payload.get("claim_id")) or stable_id("claim", agent_name, claim_text, evidence_ids, claim_task_ids),
        claim=claim_text,
        stance=stance,  # type: ignore[arg-type]
        evidence_ids=evidence_ids,
        confidence=_clamp(payload.get("confidence", confidence)),
        agent_name=_clean_text(payload.get("agent_name")) or agent_name,
        task_ids=claim_task_ids,
        limitations=_dedupe_strings(_list_of_strings(payload.get("limitations"))),
    )


def _output_list(output: Any, key: str) -> list[Any]:
    value = _get_value(output, key, [])
    return value if isinstance(value, list) else []


def _output_dict(output: Any, key: str) -> dict[str, Any]:
    return _as_dict(_get_value(output, key, {}))


def _contradictions_from_output(output: Any) -> list[dict[str, Any] | str]:
    contradictions: list[dict[str, Any] | str] = []
    for item in _output_list(output, "conflict_flags"):
        cleaned = _clean_text(item)
        if cleaned:
            contradictions.append(cleaned)
    for item in _output_list(output, "conflicting_claims"):
        if is_dataclass(item):
            try:
                contradictions.append(asdict(item))
                continue
            except Exception:
                pass
        if isinstance(item, dict):
            contradictions.append(dict(item))
        elif _clean_text(item):
            contradictions.append(_clean_text(item))
    return contradictions


def from_agent_output(output: Any, query: str, subject: dict[str, Any], task_ids: list[str]) -> EvidenceLedger:
    agent_name = _clean_text(_get_value(output, "agent_name")) or "unknown_agent"
    evidence_items = _output_list(output, "evidence")
    sources = [source_from_evidence_item(item, agent_name, index) for index, item in enumerate(evidence_items)]
    source_ids = [source.source_id for source in sources]
    confidence = _clamp(_get_value(output, "confidence", 0.5))

    claims: list[ResearchClaim] = []
    for payload in _output_list(output, "claims"):
        if not isinstance(payload, dict):
            continue
        claim = _claim_from_payload(
            payload,
            default_source_ids=source_ids,
            agent_name=agent_name,
            confidence=confidence,
            task_ids=task_ids,
        )
        if claim is not None:
            claims.append(claim)
    if not claims and _clean_text(_get_value(output, "summary")):
        claims.append(
            claim_from_summary(
                _clean_text(_get_value(output, "summary")),
                source_ids,
                agent_name,
                confidence,
                task_ids,
            )
        )

    quality = _output_dict(output, "evidence_quality")
    uncertainties = _dedupe_strings(
        _list_of_strings(quality.get("uncertainties"))
        + _list_of_strings(quality.get("limitations"))
    )
    coverage_targets = _list_of_dicts(quality.get("coverage_targets"))

    return EvidenceLedger(
        ledger_id=stable_id("ledger", query, subject, agent_name, [claim.claim_id for claim in claims], source_ids, task_ids),
        query=query,
        subject=subject,
        claims=claims,
        sources=sources,
        uncertainties=uncertainties,
        contradictions=_contradictions_from_output(output),
        coverage_targets=coverage_targets,
    )


def merge_ledgers(query: str, subject: dict[str, Any], ledgers: list[EvidenceLedger]) -> EvidenceLedger:
    claims_by_id: dict[str, ResearchClaim] = {}
    sources_by_id: dict[str, SourceRef] = {}
    uncertainties: list[str] = []
    contradictions: list[dict[str, Any] | str] = []
    coverage_targets: list[dict[str, Any]] = []

    for ledger in ledgers:
        for source in ledger.sources:
            sources_by_id.setdefault(source.source_id, source)
        for claim in ledger.claims:
            claims_by_id.setdefault(claim.claim_id, claim)
        uncertainties.extend(ledger.uncertainties)
        contradictions.extend(ledger.contradictions)
        coverage_targets.extend(ledger.coverage_targets)

    source_ids = list(sources_by_id)
    claim_ids = list(claims_by_id)
    return EvidenceLedger(
        ledger_id=stable_id("ledger", query, subject, claim_ids, source_ids),
        query=query,
        subject=subject,
        claims=list(claims_by_id.values()),
        sources=list(sources_by_id.values()),
        uncertainties=_dedupe_strings(uncertainties),
        contradictions=contradictions,
        coverage_targets=coverage_targets,
    )


def _json_safe(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _json_safe(value.model_dump(mode="json"))
    if is_dataclass(value):
        try:
            return _json_safe(asdict(value))
        except Exception:
            return str(value)
    if isinstance(value, dict):
        return {str(key): _json_safe(val) for key, val in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _drop_none(payload: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None and value != []}


def to_prompt_context(ledger: EvidenceLedger, max_claims: int = 24, max_sources: int = 24) -> dict[str, Any]:
    claim_limit = max(0, int(max_claims))
    source_limit = max(0, int(max_sources))
    sources = [
        _drop_none(
            {
                "source_id": source.source_id,
                "title": source.title,
                "url": source.url,
                "source": source.source,
                "published_date": source.published_date,
                "as_of": source.as_of,
                "reliability": source.reliability,
                "freshness_hours": source.freshness_hours,
                "layer": source.layer,
                "collection": source.collection,
            }
        )
        for source in ledger.sources[:source_limit]
    ]
    claims = [
        _drop_none(
            {
                "claim_id": claim.claim_id,
                "claim": claim.claim,
                "stance": claim.stance,
                "evidence_ids": claim.evidence_ids,
                "confidence": claim.confidence,
                "agent_name": claim.agent_name,
                "task_ids": claim.task_ids,
                "limitations": claim.limitations,
            }
        )
        for claim in ledger.claims[:claim_limit]
    ]
    return {
        "ledger_id": ledger.ledger_id,
        "query": ledger.query,
        "subject": _json_safe(ledger.subject),
        "claims": claims,
        "sources": sources,
        "uncertainties": ledger.uncertainties[:12],
        "contradictions": _json_safe(ledger.contradictions[:12]),
        "coverage_targets": _json_safe(ledger.coverage_targets[:24]),
    }

# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from backend.research.evidence_ledger import stable_id


QUALITY_SCHEMA_VERSION = "2026-05-18.agent-quality.v1"
VALID_STANCES = {"bull", "bear", "neutral", "risk", "unknown"}
AUDIT_FIELDS = ["source", "url", "timestamp", "confidence"]


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if is_dataclass(value):
        try:
            payload = asdict(value)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}
    return {}


def _get_value(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _set_value(item: Any, key: str, value: Any) -> None:
    if isinstance(item, dict):
        item[key] = value
        return
    try:
        setattr(item, key, value)
    except Exception:
        return


def _meta(item: Any) -> dict[str, Any]:
    meta = _get_value(item, "meta", None)
    if isinstance(meta, dict):
        return meta
    meta = {}
    _set_value(item, "meta", meta)
    return meta


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _clamp(value: Any, default: float = 0.5) -> float:
    parsed = _safe_float(value, default)
    return max(0.0, min(1.0, parsed))


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _list_of_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        cleaned = value.strip()
        return [cleaned] if cleaned else []
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


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


def _evidence_identity(item: Any, agent_name: str, index: int) -> dict[str, Any]:
    del index
    meta = _meta(item)
    return {
        "agent_name": agent_name,
        "source": _clean_text(_get_value(item, "source") or meta.get("source")),
        "url": _clean_text(_get_value(item, "url") or meta.get("url")),
        "timestamp": _clean_text(_get_value(item, "timestamp") or meta.get("timestamp") or meta.get("as_of")),
        "text": _clean_text(_get_value(item, "text") or meta.get("text"))[:300],
        "metric_key": _clean_text(meta.get("metric_key")),
    }


def assign_evidence_source_ids(evidence: list[Any], agent_name: str) -> list[str]:
    source_ids: list[str] = []
    for index, item in enumerate(evidence or []):
        meta = _meta(item)
        source_id = _clean_text(meta.get("source_id") or _get_value(item, "source_id"))
        if not source_id:
            source_id = stable_id("agent_source", _evidence_identity(item, agent_name, index))
        meta["source_id"] = source_id
        meta.setdefault("audit_fields", list(AUDIT_FIELDS))
        source_ids.append(source_id)
    return source_ids


def build_agent_claim(
    *,
    agent_name: str,
    ticker: str,
    query: str,
    claim: str,
    evidence_ids: list[str],
    stance: str = "unknown",
    confidence: float = 0.5,
    limitations: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    cleaned_claim = _clean_text(claim)
    if not cleaned_claim:
        raise ValueError("claim must not be empty")

    clean_stance = _clean_text(stance).lower()
    if clean_stance not in VALID_STANCES:
        clean_stance = "unknown"

    clean_evidence_ids = _dedupe_strings(_list_of_strings(evidence_ids))
    return {
        "claim_id": stable_id("agent_claim", agent_name, ticker, query, cleaned_claim, clean_evidence_ids),
        "claim": cleaned_claim,
        "stance": clean_stance,
        "evidence_ids": clean_evidence_ids,
        "confidence": _clamp(confidence),
        "agent_name": _clean_text(agent_name) or "unknown_agent",
        "limitations": _dedupe_strings(_list_of_strings(limitations or [])),
        "metadata": metadata or {},
    }


def _claim_evidence_ids(claim: Any) -> list[str]:
    payload = _as_dict(claim)
    ids = payload.get("evidence_ids")
    if ids:
        return _dedupe_strings(_list_of_strings(ids))
    legacy = payload.get("sources") or payload.get("evidence") or payload.get("source")
    return _dedupe_strings(_list_of_strings(legacy))


def _claim_limitations(claims: list[Any]) -> list[str]:
    limitations: list[str] = []
    for claim in claims:
        payload = _as_dict(claim)
        limitations.extend(_list_of_strings(payload.get("limitations")))
    return _dedupe_strings(limitations)


def _has_freshness(item: Any) -> bool:
    meta = _meta(item)
    return bool(
        _clean_text(_get_value(item, "timestamp"))
        or _clean_text(_get_value(item, "as_of"))
        or _clean_text(meta.get("timestamp"))
        or _clean_text(meta.get("as_of"))
        or _clean_text(meta.get("published_date"))
    )


def _has_url(item: Any) -> bool:
    meta = _meta(item)
    return bool(_clean_text(_get_value(item, "url")) or _clean_text(meta.get("url")))


def _explicit_confidence(item: Any) -> float | None:
    value = _get_value(item, "confidence", None)
    if value is None:
        value = _meta(item).get("confidence")
    if value is None:
        return None
    return _clamp(value)


def evaluate_agent_quality(output: Any, *, query: str = "", ticker: str = "") -> dict[str, Any]:
    del query, ticker
    agent_name = _clean_text(_get_value(output, "agent_name")) or "unknown_agent"
    evidence = _as_list(_get_value(output, "evidence", []))
    claims = _as_list(_get_value(output, "claims", []))
    risks = _as_list(_get_value(output, "risks", []))
    source_ids = assign_evidence_source_ids(evidence, agent_name=agent_name)
    source_id_set = set(source_ids)

    supported_claim_count = 0
    unsupported_claim_count = 0
    for claim in claims:
        ids = _claim_evidence_ids(claim)
        if ids and source_id_set.intersection(ids):
            supported_claim_count += 1
        else:
            unsupported_claim_count += 1

    evidence_count = len(evidence)
    claim_count = len(claims)
    evidence_with_url_count = sum(1 for item in evidence if _has_url(item))
    evidence_with_freshness_count = sum(1 for item in evidence if _has_freshness(item))
    low_confidence_evidence_count = sum(
        1 for item in evidence
        if (confidence := _explicit_confidence(item)) is not None and confidence < 0.5
    )
    source_names = {
        _clean_text(_get_value(item, "source") or _meta(item).get("source"))
        for item in evidence
        if _clean_text(_get_value(item, "source") or _meta(item).get("source"))
    }
    limitation_count = len(_claim_limitations(claims))
    contradiction_count = len(_as_list(_get_value(output, "conflict_flags", []))) + len(
        _as_list(_get_value(output, "conflicting_claims", []))
    )

    claim_source_ratio = supported_claim_count / claim_count if claim_count else 0.0
    evidence_url_rate = evidence_with_url_count / evidence_count if evidence_count else 0.0
    evidence_freshness_rate = evidence_with_freshness_count / evidence_count if evidence_count else 0.0

    reason_codes: list[str] = []
    if evidence_count == 0:
        reason_codes.append("no_evidence")
    if claim_count == 0:
        reason_codes.append("no_claims")
    if unsupported_claim_count:
        reason_codes.append("unsupported_claim")
    if evidence_count and evidence_freshness_rate < 0.5:
        reason_codes.append("low_freshness")
    if low_confidence_evidence_count:
        reason_codes.append("low_source_quality")

    if "no_evidence" in reason_codes:
        status = "fail"
    elif reason_codes:
        status = "warn"
    else:
        status = "pass"

    support_component = claim_source_ratio if claim_count else 0.0
    evidence_component = min(1.0, evidence_count / 3.0)
    freshness_component = evidence_freshness_rate
    url_component = evidence_url_rate
    overall_score = round(
        support_component * 0.45
        + evidence_component * 0.25
        + freshness_component * 0.20
        + url_component * 0.10,
        4,
    )

    return {
        "schema_version": QUALITY_SCHEMA_VERSION,
        "status": status,
        "reason_codes": reason_codes,
        "metrics": {
            "evidence_count": evidence_count,
            "evidence_with_url_count": evidence_with_url_count,
            "low_confidence_evidence_count": low_confidence_evidence_count,
            "evidence_url_rate": round(evidence_url_rate, 4),
            "evidence_freshness_rate": round(evidence_freshness_rate, 4),
            "source_count": len(source_names),
            "claim_count": claim_count,
            "supported_claim_count": supported_claim_count,
            "unsupported_claim_count": unsupported_claim_count,
            "claim_source_ratio": round(claim_source_ratio, 4),
            "risk_count": len(risks),
            "limitation_count": limitation_count,
            "contradiction_count": contradiction_count,
            "overall_score": overall_score,
        },
        "recovery": {
            "next_actions": [
                {
                    "action": "verify_or_replace_low_confidence_source",
                    "reason": "low_source_quality",
                    "tool_hint": "authoritative_source_lookup",
                }
            ] if low_confidence_evidence_count else []
        },
    }


def apply_agent_quality_contract(output: Any, *, query: str = "", ticker: str = "") -> Any:
    quality = evaluate_agent_quality(output, query=query, ticker=ticker)
    existing_quality = _get_value(output, "evidence_quality", None)
    if not isinstance(existing_quality, dict):
        existing_quality = {}
    merged = dict(existing_quality)
    merged["agent_quality"] = quality
    _set_value(output, "evidence_quality", merged)
    return output


__all__ = [
    "QUALITY_SCHEMA_VERSION",
    "apply_agent_quality_contract",
    "assign_evidence_source_ids",
    "build_agent_claim",
    "evaluate_agent_quality",
]

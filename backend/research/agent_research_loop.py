# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from backend.research.agent_quality_contract import evaluate_agent_quality


SELF_CHECK_SCHEMA_VERSION = "2026-05-18.agent-self-check.v1"


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


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


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _quality_payload(output: Any, query: str, ticker: str) -> dict[str, Any]:
    evidence_quality = _as_dict(_get_value(output, "evidence_quality", {}))
    quality = evidence_quality.get("agent_quality")
    if isinstance(quality, dict):
        return quality
    return evaluate_agent_quality(output, query=query, ticker=ticker)


def _gap_for_reason(reason: str, *, query: str, ticker: str, metrics: dict[str, Any]) -> dict[str, Any] | None:
    base = {
        "query": query,
        "ticker": ticker,
        "metrics": metrics,
    }
    if reason == "no_evidence":
        return {
            **base,
            "code": "collect_evidence",
            "severity": "high",
            "description": "Agent produced no usable evidence.",
            "tool_hint": "domain_tool",
        }
    if reason == "no_claims":
        return {
            **base,
            "code": "extract_claims",
            "severity": "medium",
            "description": "Evidence exists but no claim-level conclusion was produced.",
            "tool_hint": "claim_extractor",
        }
    if reason == "unsupported_claim":
        return {
            **base,
            "code": "attach_sources",
            "severity": "high",
            "description": "At least one claim has no matching evidence source id.",
            "tool_hint": "evidence_linker",
        }
    if reason == "low_freshness":
        return {
            **base,
            "code": "refresh_sources",
            "severity": "medium",
            "description": "Evidence freshness metadata is missing or sparse.",
            "tool_hint": "source_refresh",
        }
    if reason == "low_source_quality":
        return {
            **base,
            "code": "verify_source_quality",
            "severity": "medium",
            "description": "At least one evidence item has explicitly low confidence.",
            "tool_hint": "authoritative_source_lookup",
        }
    return None


def _action_for_gap(gap: dict[str, Any]) -> dict[str, Any]:
    code = str(gap.get("code") or "")
    if code == "collect_evidence":
        action = "run_targeted_domain_tool"
    elif code == "extract_claims":
        action = "extract_claims_from_existing_evidence"
    elif code == "attach_sources":
        action = "relink_claims_to_evidence"
    elif code == "refresh_sources":
        action = "refresh_or_timestamp_evidence"
    elif code == "verify_source_quality":
        action = "verify_or_replace_low_confidence_source"
    else:
        action = "inspect_agent_output"
    return {
        "action": action,
        "tool_hint": gap.get("tool_hint") or "manual_review",
        "query": gap.get("query") or "",
        "ticker": gap.get("ticker") or "",
        "reason": gap.get("code") or "unknown_gap",
    }


def build_quality_gap_plan(output: Any, *, query: str = "", ticker: str = "") -> dict[str, Any]:
    clean_query = _clean_text(query)
    clean_ticker = _clean_text(ticker)
    quality = _quality_payload(output, clean_query, clean_ticker)
    reason_codes = [str(item).strip() for item in quality.get("reason_codes", []) if str(item or "").strip()]
    metrics = _as_dict(quality.get("metrics"))

    gaps = []
    for reason in reason_codes:
        gap = _gap_for_reason(reason, query=clean_query, ticker=clean_ticker, metrics=metrics)
        if gap is not None:
            gaps.append(gap)

    next_actions = [_action_for_gap(gap) for gap in gaps]
    quality_status = str(quality.get("status") or "warn").strip().lower()
    status = "pass" if not gaps and quality_status == "pass" else ("fail" if quality_status == "fail" else "warn")
    return {
        "schema_version": SELF_CHECK_SCHEMA_VERSION,
        "status": status,
        "can_continue": status != "fail",
        "gaps": gaps,
        "next_actions": next_actions,
        "quality_status": quality_status,
    }


def apply_agent_self_check(output: Any, *, query: str = "", ticker: str = "") -> Any:
    plan = build_quality_gap_plan(output, query=query, ticker=ticker)
    evidence_quality = _as_dict(_get_value(output, "evidence_quality", {}))
    merged = dict(evidence_quality)
    merged["agent_self_check"] = plan
    _set_value(output, "evidence_quality", merged)
    return output


__all__ = [
    "SELF_CHECK_SCHEMA_VERSION",
    "apply_agent_self_check",
    "build_quality_gap_plan",
]

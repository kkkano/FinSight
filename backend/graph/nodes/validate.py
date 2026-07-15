# -*- coding: utf-8 -*-
"""统一记录证据、Claim、引用与发布质量状态。"""
from __future__ import annotations

from typing import Any

from backend.graph.state import GraphState


def _mapping_size(value: Any) -> int:
    return len(value) if isinstance(value, dict) else 0


def validate(state: GraphState) -> dict[str, Any]:
    artifacts = dict(state.get("artifacts") or {})
    trace = dict(state.get("trace") or {})
    ledger = artifacts.get("evidence_ledger") if isinstance(artifacts.get("evidence_ledger"), dict) else {}
    claim_validation = artifacts.get("task_claim_validation")
    if not isinstance(claim_validation, dict):
        claim_validation = artifacts.get("claim_validation") if isinstance(artifacts.get("claim_validation"), dict) else {}
    valid_claims = claim_validation.get("valid_claims") if isinstance(claim_validation, dict) else {}
    rejected_claims = claim_validation.get("rejected_claims") if isinstance(claim_validation, dict) else []
    evidence_pool = artifacts.get("evidence_pool") if isinstance(artifacts.get("evidence_pool"), list) else []
    citation_count = sum(
        1 for item in evidence_pool
        if isinstance(item, dict) and str(item.get("url") or item.get("source_url") or "").strip()
    )
    blocked = bool(artifacts.get("quality_blocked"))
    validation = {
        "status": "blocked" if blocked else "passed",
        "evidence_ledger_entries": _mapping_size(ledger.get("items") if isinstance(ledger, dict) else {}),
        "evidence_count": len(evidence_pool),
        "citation_count": citation_count,
        "valid_claim_count": _mapping_size(valid_claims),
        "rejected_claim_count": len(rejected_claims) if isinstance(rejected_claims, list) else 0,
        "future_claim_scrubbed": bool(artifacts.get("future_claims_scrubbed")),
    }
    artifacts["validation"] = validation
    trace["validation"] = validation
    return {"artifacts": artifacts, "trace": trace}


__all__ = ["validate"]

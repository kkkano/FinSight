# -*- coding: utf-8 -*-
"""投资观点的确定性证据门槛。"""
from __future__ import annotations

from typing import Literal

from backend.graph.synthesis.contracts import (
    ClaimValidationResult,
    EvidenceNormalizationResult,
    NonEmptyStr,
    StrictContract,
    TaskSynthesisResult,
    stable_unique,
)
from backend.graph.synthesis.task_outcomes import TaskOutcome

QualifiedDimension = Literal["technical", "fundamental", "valuation", "earnings", "catalyst", "risk"]
ReasonCode = Literal[
    "missing_symbol", "missing_price_anchor", "missing_core_evidence",
    "insufficient_independent_dimensions", "unsupported_direction",
    "unresolved_material_conflict", "evidence_contract_invalid",
]


class OpinionReadiness(StrictContract):
    schema_version: Literal["2026-07-14.opinion-readiness.v1"] = "2026-07-14.opinion-readiness.v1"
    task_id: NonEmptyStr
    symbol: NonEmptyStr | None = None
    direction_allowed: bool
    proposed_direction: Literal["bull", "bear", "neutral"] | None = None
    supporting_claim_ids: list[NonEmptyStr]
    opposing_claim_ids: list[NonEmptyStr]
    price_anchor_source_id: NonEmptyStr | None = None
    qualified_dimensions: list[QualifiedDimension]
    unresolved_conflict_ids: list[NonEmptyStr]
    reason_codes: list[ReasonCode]


def build_opinion_readiness(
    *,
    task_outcome: TaskOutcome,
    task_result: TaskSynthesisResult,
    claim_validation: ClaimValidationResult,
    evidence_normalization: EvidenceNormalizationResult,
) -> OpinionReadiness:
    reasons: list[ReasonCode] = []
    symbol = task_outcome.tickers[0] if len(task_outcome.tickers) == 1 else None
    if symbol is None:
        reasons.append("missing_symbol")

    evidence = evidence_normalization.evidence_by_task.get(task_outcome.task_id, [])
    anchor = next((
        item for item in evidence
        if item.kind == "price_snapshot"
        and item.market_price is not None
        and item.as_of is not None
        and task_outcome.task_id in item.task_ids
    ), None)
    if anchor is None:
        reasons.append("missing_price_anchor")

    task_claims = [
        claim for claim in claim_validation.valid_claims.values()
        if claim.task_id == task_outcome.task_id
    ]
    qualified: list[QualifiedDimension] = []
    sources_by_dimension: dict[str, set[str]] = {}
    for claim in task_claims:
        if claim.dimension not in {"technical", "fundamental", "valuation", "earnings", "catalyst", "risk"}:
            continue
        if claim.dimension not in qualified:
            qualified.append(claim.dimension)  # type: ignore[arg-type]
        sources_by_dimension.setdefault(claim.dimension, set()).update(claim.evidence_ids)
    independent_sources = set().union(*(sources_by_dimension.values() or [set()]))
    if not any(item in qualified for item in ("technical", "fundamental", "valuation", "earnings")):
        reasons.append("missing_core_evidence")
    if len(qualified) < 2 or len(independent_sources) < 2:
        reasons.append("insufficient_independent_dimensions")

    proposal = task_result.proposed_direction
    supporting = list(task_result.direction_supporting_claim_ids)
    supporting_claims = [claim_validation.valid_claims.get(item) for item in supporting]
    supporting_claims = [item for item in supporting_claims if item is not None]
    supporting_dimensions = {item.dimension for item in supporting_claims}
    supporting_sources = {source_id for item in supporting_claims for source_id in item.evidence_ids}
    proposal_valid = bool(
        proposal in {"bull", "bear", "neutral"}
        and supporting
        and len(supporting_claims) == len(supporting)
        and all(item.task_id == task_outcome.task_id and item.stance == proposal for item in supporting_claims)
        and len(supporting_dimensions & set(qualified)) >= 2
        and len(supporting_sources) >= 2
    )
    if not proposal_valid:
        reasons.append("unsupported_direction")

    opposing = [
        item.claim_id for item in task_claims
        if proposal is not None and item.stance in {"bull", "bear", "neutral"} and item.stance != proposal
    ]
    unresolved = [
        item.conflict_id for item in claim_validation.conflicts
        if item.task_id == task_outcome.task_id
        and item.material and not item.resolved and item.affects_direction
    ]
    if unresolved:
        reasons.append("unresolved_material_conflict")
    if evidence_normalization.quality_block_reasons or claim_validation.quality_block_reasons:
        reasons.append("evidence_contract_invalid")

    reasons = stable_unique(reasons)
    direction_allowed = not reasons
    return OpinionReadiness(
        task_id=task_outcome.task_id,
        symbol=symbol,
        direction_allowed=direction_allowed,
        proposed_direction=proposal if direction_allowed else None,
        supporting_claim_ids=supporting if direction_allowed else [],
        opposing_claim_ids=opposing,
        price_anchor_source_id=anchor.source_id if anchor else None,
        qualified_dimensions=qualified,
        unresolved_conflict_ids=unresolved,
        reason_codes=reasons,
    )


__all__ = ["OpinionReadiness", "build_opinion_readiness"]

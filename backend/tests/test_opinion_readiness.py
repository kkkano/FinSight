# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from backend.graph.renderers.opinion import render_investment_opinion
from backend.graph.synthesis.contracts import (
    Claim,
    ClaimConflict,
    ClaimValidationResult,
    EvidenceNormalizationResult,
    NormalizedEvidence,
    TaskSynthesisResult,
)
from backend.graph.synthesis.opinion_readiness import build_opinion_readiness
from backend.graph.synthesis.task_outcomes import TaskOutcome


def _outcome(*, tickers: list[str] | None = None) -> TaskOutcome:
    return TaskOutcome(
        task_id="t1", title="AAPL 投资观点", priority=20, order_index=0,
        operation="investment_opinion", subject_label="AAPL",
        tickers=["AAPL"] if tickers is None else tickers,
        request_frame_id="f1", render_kind="single", render_group_id="f1",
        intent_status="ready", required_step_ids=[], required_evidence=[], error_codes=[],
        status="answered", successful_step_ids=[], evidence_ids=[], missing_evidence=[],
    )


def _claim(claim_id: str, dimension: str, source_id: str, *, stance: str = "bull") -> Claim:
    return Claim(
        claim_id=claim_id, task_id="t1", agent_name=f"{dimension}_agent",
        text=f"{dimension} supported claim", stance=stance, dimension=dimension,
        confidence=0.8, evidence_ids=[source_id], limitations=[],
    )


def _readiness_case(
    *,
    tickers: list[str] | None = None,
    anchor: bool = True,
    claims: list[Claim] | None = None,
    proposal: str | None = "bull",
    support: list[str] | None = None,
    conflicts: list[ClaimConflict] | None = None,
):
    claims = claims or []
    evidence_items: list[NormalizedEvidence] = []
    if anchor:
        evidence_items.append(NormalizedEvidence(
            source_id="price", task_ids=["t1"], kind="price_snapshot", text="price",
            as_of="2026-07-14", market_price=100,
        ))
    for claim in claims:
        if claim.evidence_ids[0] == "price":
            continue
        evidence_items.append(NormalizedEvidence(
            source_id=claim.evidence_ids[0], task_ids=["t1"],
            kind="technical_snapshot" if claim.dimension == "technical" else "fundamental_snapshot",
            text=claim.text,
        ))
    evidence_index = {item.source_id: item for item in evidence_items}
    evidence = EvidenceNormalizationResult(
        evidence_by_task={"t1": evidence_items}, evidence_index=evidence_index,
        rejected_evidence=[], quality_block_reasons=[],
    )
    validation = ClaimValidationResult(
        valid_claims={item.claim_id: item for item in claims}, rejected_claims=[],
        conflicts=conflicts or [], quality_block_reasons=[],
    )
    result = TaskSynthesisResult(
        task_id="t1", title="AAPL 投资观点", priority=20, order_index=0,
        request_frame_id="f1", render_kind="single", render_group_id="f1",
        status="partial", conclusion=claims[0].text if claims else None,
        claim_ids=[item.claim_id for item in claims],
        evidence_ids=[source for item in claims for source in item.evidence_ids],
        proposed_direction=proposal,
        direction_supporting_claim_ids=support if support is not None else [item.claim_id for item in claims],
        agent_names=[], agreements=[], disagreements=[], conflicts=conflicts or [],
        risks=[], limitations=[], fallback_used=False, error_codes=[],
    )
    outcome = _outcome(tickers=tickers)
    return build_opinion_readiness(
        task_outcome=outcome, task_result=result,
        claim_validation=validation, evidence_normalization=evidence,
    ), result, validation, evidence


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ({"tickers": []}, "missing_symbol"),
        ({"anchor": False}, "missing_price_anchor"),
        ({"claims": [_claim("news", "news", "news-e")]}, "missing_core_evidence"),
        ({"claims": [_claim("risk", "risk", "risk-e")]}, "missing_core_evidence"),
        ({"claims": [_claim("tech", "technical", "tech-e")]}, "insufficient_independent_dimensions"),
        ({"claims": [], "support": []}, "unsupported_direction"),
    ],
)
def test_opinion_readiness_negative_cases(case, expected_reason):
    readiness, *_ = _readiness_case(**case)
    assert readiness.direction_allowed is False
    assert readiness.proposed_direction is None
    assert expected_reason in readiness.reason_codes


def test_opinion_readiness_material_conflict_closes_direction():
    claims = [
        _claim("tech", "technical", "tech-e"),
        _claim("fund", "fundamental", "fund-e"),
        _claim("bear", "risk", "risk-e", stance="bear"),
    ]
    conflict = ClaimConflict(
        conflict_id="conflict:t1:bear:tech", task_id="t1",
        claim_ids=["bear", "tech"], material=True, resolved=False, affects_direction=True,
    )
    readiness, *_ = _readiness_case(
        claims=claims, support=["tech", "fund"], conflicts=[conflict],
    )
    assert readiness.direction_allowed is False
    assert readiness.unresolved_conflict_ids == [conflict.conflict_id]
    assert "unresolved_material_conflict" in readiness.reason_codes


def test_opinion_readiness_requires_price_two_independent_dimensions_and_supported_stance():
    claims = [
        _claim("tech", "technical", "tech-e"),
        _claim("fund", "fundamental", "fund-e"),
    ]
    readiness, *_ = _readiness_case(claims=claims, support=["tech", "fund"])
    assert readiness.direction_allowed is True
    assert readiness.proposed_direction == "bull"
    assert readiness.price_anchor_source_id == "price"
    assert readiness.qualified_dimensions == ["technical", "fundamental"]


def test_opinion_renderer_false_state_never_emits_system_direction_terms():
    readiness, result, validation, evidence = _readiness_case(claims=[])
    state = {
        "tasks": [{"id": "t1", "operation": {"name": "investment_opinion"}}],
        "artifacts": {"opinion_synthesis": {
            "task_results_by_task": {"t1": result.model_dump()},
            "readiness_by_task": {"t1": readiness.model_dump()},
            "claim_validation": validation.model_dump(),
            "evidence_normalization": evidence.model_dump(),
        }},
    }
    markdown = render_investment_opinion(state, {"operations": {"investment_opinion"}})
    assert markdown is not None
    assert "证据状态：暂不能形成方向判断" in markdown
    for term in ("偏多", "偏空", "中性", "买入", "卖出", "持有"):
        assert term not in markdown


def test_keyword_bias_helper_is_removed():
    import backend.graph.renderers.opinion as module

    assert not hasattr(module, "_investment_opinion_bias")

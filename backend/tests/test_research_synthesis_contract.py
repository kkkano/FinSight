# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from backend.graph.renderers.research_report import render_research_report
from backend.graph.synthesis.contracts import Claim, NormalizedEvidence
from backend.graph.synthesis.research_synthesis import (
    build_agent_findings,
    evaluate_synthesis_quality,
    finalize_report_synthesis,
    normalize_evidence,
    synthesize_report_draft,
    synthesize_task_results,
    validate_claims,
)
from backend.graph.synthesis.task_outcomes import (
    TaskDescriptor,
    build_task_descriptors,
    finalize_task_outcomes,
)
from backend.services.llm_retry import LLMCallContext


def _descriptor(task_id: str, order: int, *, required: list[str] | None = None) -> TaskDescriptor:
    return TaskDescriptor(
        task_id=task_id,
        title=f"任务 {task_id}",
        priority=20,
        order_index=order,
        operation="investment_opinion",
        subject_label="AAPL",
        tickers=["AAPL"],
        request_frame_id=f"frame-{task_id}",
        render_kind="single",
        render_group_id=f"frame-{task_id}",
        intent_status="ready",
        required_step_ids=[f"step-{task_id}"],
        required_evidence=required or ["price_snapshot"],
        error_codes=[],
    )


def _pipeline(*, two_tasks: bool = False):
    descriptors = [_descriptor("t1", 0)]
    if two_tasks:
        descriptors.append(_descriptor("t2", 1))
    raw_evidence = {
        item.task_id: [{
            "source_id": f"e-{item.task_id}",
            "task_ids": [item.task_id],
            "kind": "price_snapshot",
            "text": f"{item.task_id} price evidence",
            "as_of": "2026-07-14",
            "market_price": 100,
        }]
        for item in descriptors
    }
    evidence = normalize_evidence(
        task_descriptors=descriptors,
        plan_steps=[],
        agent_outputs={},
        raw_evidence_by_task=raw_evidence,
    )
    claims = {
        item.task_id: {
            "raw_claims": [{
                "claim_id": f"c-{item.task_id}",
                "task_id": item.task_id,
                "agent_name": "fundamental_agent",
                "text": f"{item.task_id} supported conclusion",
                "stance": "bull",
                "confidence": 0.8,
                "evidence_ids": [f"e-{item.task_id}"],
                "dimension": "market",
                "limitations": [],
            }],
            "agent_name": "fundamental_agent",
            "task_ids": [item.task_id],
        }
        for item in descriptors
    }
    validation = validate_claims(
        run_id="run-1",
        task_descriptors=descriptors,
        plan_steps=[],
        agent_outputs=claims,
        evidence_normalization=evidence,
    )
    outcomes = finalize_task_outcomes(
        descriptors=descriptors,
        plan_steps=[],
        task_results={f"step-{item.task_id}": {"output": {"ok": True}} for item in descriptors},
        evidence_normalization=evidence,
        claim_validation=validation,
    ).outcomes
    findings = build_agent_findings(
        task_outcomes=outcomes,
        plan_steps=[],
        agent_outputs=claims,
        claim_validation=validation,
        evidence_normalization=evidence,
    )
    return descriptors, evidence, validation, outcomes, findings


def test_descriptor_build_preserves_raw_ordinals_duplicates_and_invalid_order():
    result = build_task_descriptors(
        understanding_tasks=[
            {"id": "t1", "order_index": 1, "title": "一", "subject_label": "AAPL", "operation": {"name": "qa"}, "request_frame_id": "f1", "render_kind": "single", "render_group_id": "f1"},
            {"id": "t1", "order_index": 1, "title": "二", "subject_label": "MSFT", "operation": {"name": "qa"}, "request_frame_id": "f2", "render_kind": "single", "render_group_id": "f2"},
            {"id": "", "order_index": -1, "title": "三", "subject_label": "宏观", "operation": {"name": "qa"}},
        ],
        blocked_tasks=[],
        plan_tasks=[{"id": "t1"}],
        plan_steps=[],
    )
    assert result.requested_task_count == 3
    assert result.requested_task_ids == ["t1", "t1"]
    assert result.invalid_task_ordinals == [2]
    assert result.invalid_order_ordinals == [2]
    assert result.duplicate_task_ids == ["t1"]
    assert {"duplicate_task", "duplicate_order_index", "invalid_task_identity", "invalid_order_index"} <= set(result.quality_block_reasons)


def test_evidence_canonical_merge_and_content_conflict():
    descriptors = [_descriptor("t1", 0), _descriptor("t2", 1)]
    merged = normalize_evidence(
        task_descriptors=descriptors,
        plan_steps=[],
        agent_outputs={},
        raw_evidence_by_task={
            "t1": [{"source_id": "e1", "kind": "price_snapshot", "text": "same", "as_of": "2026-07-14", "market_price": 10}],
            "t2": [{"source_id": "e1", "kind": "price_snapshot", "text": "same", "as_of": "2026-07-14", "market_price": 10}],
        },
    )
    assert merged.evidence_index["e1"].task_ids == ["t1", "t2"]
    assert not merged.quality_block_reasons

    conflicted = normalize_evidence(
        task_descriptors=descriptors,
        plan_steps=[],
        agent_outputs={},
        raw_evidence_by_task={
            "t1": [{"source_id": "e1", "kind": "price_snapshot", "text": "left"}],
            "t2": [{"source_id": "e1", "kind": "price_snapshot", "text": "right"}],
        },
    )
    assert conflicted.quality_block_reasons == ["evidence_id_content_conflict"]


def test_claim_validation_reads_only_raw_claims_and_blocks_cross_task_reference():
    descriptors = [_descriptor("t1", 0), _descriptor("t2", 1)]
    evidence = normalize_evidence(
        task_descriptors=descriptors,
        plan_steps=[],
        agent_outputs={},
        raw_evidence_by_task={"t1": [{"source_id": "e1", "kind": "price_snapshot", "text": "bound only to t1"}]},
    )
    result = validate_claims(
        run_id="run",
        task_descriptors=descriptors,
        plan_steps=[],
        agent_outputs={
            "ignored": {"claims": [{"claim_id": "repaired", "text": "must not be read"}]},
            "cross": {"agent_name": "risk_agent", "task_ids": ["t2"], "raw_claims": [{
                "claim_id": "c2", "task_id": "t2", "agent_name": "risk_agent",
                "text": "cross", "stance": "bear", "confidence": 0.8,
                "evidence_ids": ["e1"], "limitations": [],
            }]},
        },
        evidence_normalization=evidence,
    )
    assert "repaired" not in result.valid_claims
    assert result.quality_block_reasons == ["cross_task_claim_reference"]
    assert result.rejected_claims[0].reason_code == "cross_task_claim_reference"


def test_finding_summary_without_claim_is_limitation_not_conclusion():
    descriptor = _descriptor("t1", 0)
    evidence = normalize_evidence(
        task_descriptors=[descriptor], plan_steps=[], agent_outputs={},
        raw_evidence_by_task={"t1": [{"source_id": "e1", "kind": "price_snapshot", "text": "price"}]},
    )
    validation = validate_claims(
        run_id="run", task_descriptors=[descriptor], plan_steps=[],
        agent_outputs={}, evidence_normalization=evidence,
    )
    outcome = finalize_task_outcomes(
        descriptors=[descriptor], plan_steps=[], task_results={"step-t1": {"output": "ok"}},
        evidence_normalization=evidence, claim_validation=validation,
    ).outcomes[0]
    findings = build_agent_findings(
        task_outcomes=[outcome], plan_steps=[],
        agent_outputs={"a": {"agent_name": "price_agent", "task_ids": ["t1"], "summary": "自由文本摘要"}},
        claim_validation=validation, evidence_normalization=evidence,
    )
    assert findings[0].conclusion is None
    assert findings[0].fallback_used is True
    assert "自由文本摘要" in findings[0].limitations


@pytest.mark.asyncio
async def test_task_and_report_llm_use_isolated_contexts_and_validated_ids(monkeypatch):
    import backend.graph.synthesis.research_synthesis as module

    _, evidence, validation, outcomes, findings = _pipeline(two_tasks=True)
    contexts: list[LLMCallContext] = []

    def task_context(outcome):
        context = LLMCallContext.create(stage="synthesize", agent=outcome.task_id, layer="synthesis")
        contexts.append(context)
        return context

    async def fake_invoke(_messages, *, context, **_kwargs):
        task_id = context.agent
        return {
            "claim_ids": [f"c-{task_id}"],
            "conclusion_claim_id": f"c-{task_id}",
            "proposed_direction": "bull",
            "direction_supporting_claim_ids": [f"c-{task_id}"],
        }

    monkeypatch.setattr(module, "ainvoke_configured_llm", fake_invoke)
    task_results = await synthesize_task_results(
        task_outcomes=outcomes, findings=findings,
        claim_validation=validation, evidence_normalization=evidence,
        llm_call_context_factory=task_context,
    )
    assert [item.task_id for item in task_results] == ["t1", "t2"]
    assert all(item.fallback_used is False for item in task_results)
    assert len({item.logical_call_id for item in contexts}) == 2

    report_context = LLMCallContext.create(stage="report_synthesize", agent="report", layer="synthesis")

    async def fake_report(_messages, *, context, **_kwargs):
        assert context is report_context
        return {"overall_conclusion": "两项任务均有受支持结论。", "supporting_task_ids": ["t1", "t2"]}

    monkeypatch.setattr(module, "ainvoke_configured_llm", fake_report)
    draft = await synthesize_report_draft(
        task_results=task_results, claim_validation=validation,
        evidence_normalization=evidence, llm_call_context_factory=lambda: report_context,
    )
    assert draft.fallback_used is False
    assert draft.overall_conclusion == "两项任务均有受支持结论。"
    assert report_context.logical_call_id not in {item.logical_call_id for item in contexts}


@pytest.mark.asyncio
async def test_fallback_gate_renderer_and_finalize_are_deterministic():
    _, evidence, validation, outcomes, findings = _pipeline()
    task_results = await synthesize_task_results(
        task_outcomes=outcomes, findings=findings,
        claim_validation=validation, evidence_normalization=evidence,
        llm_call_context_factory=lambda _task: None,
    )
    draft = await synthesize_report_draft(
        task_results=task_results, claim_validation=validation,
        evidence_normalization=evidence, llm_call_context_factory=lambda: None,
    )
    assert task_results[0].fallback_used is True
    assert draft.fallback_used is True
    pre_gate = evaluate_synthesis_quality(
        draft=draft, requested_task_ids=["t1"], evidence_index=evidence.evidence_index,
    )
    assert pre_gate.state == "degraded"
    rendered = render_research_report(draft)
    assert rendered.rendered_task_ids == ["t1"]
    assert [line for line in rendered.markdown.splitlines() if line.startswith("## ")] == [
        "## 总判断", "## 分任务结论", "## 关键论据与证据", "## 分歧与风险", "## 限制", "## 引用",
    ]
    final_gate = evaluate_synthesis_quality(
        draft=draft, requested_task_ids=["t1"], evidence_index=evidence.evidence_index,
        rendered_task_ids=rendered.rendered_task_ids,
    )
    final = finalize_report_synthesis(draft=draft, final_gate=final_gate)
    assert final.model_dump(exclude={"degraded"}) == draft.model_dump()
    assert final.degraded is True

    blocked = evaluate_synthesis_quality(
        draft=draft, requested_task_ids=["t1", "missing"],
        evidence_index=evidence.evidence_index,
    )
    assert blocked.state == "block"
    assert "missing_task" in blocked.reasons


def test_contract_models_reject_index_identity_mismatch():
    evidence = NormalizedEvidence(
        source_id="e1", task_ids=["t1"], kind="price_snapshot",
        text="price", as_of="2026-07-14", market_price=100,
    )
    claim = Claim(
        claim_id="c1", task_id="t1", agent_name="price_agent", text="supported",
        stance="bull", dimension="market", confidence=0.8,
        evidence_ids=["e1"], limitations=[],
    )
    assert evidence.source_id == "e1" and claim.claim_id == "c1"

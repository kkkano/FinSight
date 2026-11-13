# -*- coding: utf-8 -*-
"""统一记录证据、Claim、引用与发布质量状态。"""
from __future__ import annotations

from typing import Any

from backend.graph.state import GraphState
from backend.report.quality_engine import evaluate_result_quality
from backend.graph.synthesis.contracts import ReportSynthesisDraft, aggregate_task_status
from backend.graph.synthesis.research_synthesis import evaluate_synthesis_quality, finalize_report_synthesis
from backend.graph.synthesis.requirement_validation import overall_conclusion_block_reasons


def _mapping_size(value: Any) -> int:
    return len(value) if isinstance(value, dict) else 0


def validate(state: GraphState) -> dict[str, Any]:
    artifacts = dict(state.get("artifacts") or {})
    trace = dict(state.get("trace") or {})
    raw = artifacts.get("research_result") or artifacts.get("research_synthesis_draft")
    if isinstance(raw, dict):
        draft = ReportSynthesisDraft.model_validate(raw)
        # 覆盖检查是执行前的可规划性诊断；实际完成度由已取到的事实与逐要求校验决定。
        draft.status = aggregate_task_status([task.status for task in draft.task_results])
        overall_reasons = overall_conclusion_block_reasons(draft)
        if overall_reasons:
            draft.overall_conclusion = None
        draft.synthesis_validation = {**draft.synthesis_validation, "overall_block_reasons": overall_reasons}
        gate = evaluate_synthesis_quality(
            draft=draft, requested_task_ids=artifacts.get("research_requested_task_ids") or [task.task_id for task in draft.task_results],
            evidence_index=draft.evidence_index,
            structural_block_reasons=artifacts.get("research_structural_block_reasons") or [],
            require_claims=False,
        )
        artifacts.update(research_result=draft.model_dump(), research_result_quality=gate.model_dump())
        if state.get("output_mode") == "investment_report":
            artifacts.update(research_synthesis=finalize_report_synthesis(draft=draft, final_gate=gate).model_dump(),
                             research_synthesis_gate=gate.model_dump())
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
    quality = evaluate_result_quality(state={**state, "artifacts": artifacts})
    artifacts["result_quality"] = quality
    artifacts["quality_blocked"] = quality["state"] == "block"
    artifacts["publishable"] = quality["publishable"]
    blocked = artifacts["quality_blocked"]
    validation = {
        "status": "blocked" if blocked else "partial" if quality["state"] == "warn" else "passed",
        "answer_status": quality["answer_status"],
        "quality": quality,
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

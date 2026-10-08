"""截止时间内只投影已完成的执行事实，不启动网络取数或模型合成。"""
from __future__ import annotations

from typing import Any

from backend.graph.execution.evidence_pipeline import normalize_execution_evidence
from backend.graph.renderers.research_report import render_research_report
from backend.graph.synthesis.analysis_requirements import answer_requirements_by_task, requested_task_partition
from backend.graph.synthesis.contracts import ClaimValidationResult, EvidenceNormalizationResult
from backend.graph.synthesis.research_synthesis import synthesize_report_draft, synthesize_task_results
from backend.graph.synthesis.task_outcomes import build_task_descriptors, finalize_task_outcomes


async def build_partial_delivery(run) -> dict[str, Any]:
    state = run.compiled_state or {}
    completed = run.completed_step_snapshot()
    if not state or not completed:
        return {"response": "", "answer_status": "unavailable", "publishable": False}
    steps = [step for step, _ in completed.values()]
    results = {key: result for key, (_, result) in completed.items()}
    ready, blocked = requested_task_partition(state)
    plan = {"steps": steps, "tasks": [*ready, *blocked]}
    artifacts = {"step_results": results}
    normalize_execution_evidence(state=state, plan_ir=plan, artifacts=artifacts, enrich_snippets=False)
    if not artifacts.get("task_evidence_normalization"):
        return {"response": "", "answer_status": "unavailable", "publishable": False}
    evidence = EvidenceNormalizationResult.model_validate(artifacts["task_evidence_normalization"])
    if evidence.quality_block_reasons:
        return {"response": "", "answer_status": "blocked", "publishable": False,
                "blocked_reason_codes": evidence.quality_block_reasons}
    descriptors = build_task_descriptors(understanding_tasks=ready, blocked_tasks=blocked,
                                         plan_tasks=plan["tasks"], plan_steps=steps).descriptors
    claims = ClaimValidationResult(valid_claims={}, rejected_claims=[], conflicts=[], quality_block_reasons=[])
    outcomes = finalize_task_outcomes(descriptors=descriptors, plan_steps=steps, task_results=results,
                                     evidence_normalization=evidence, claim_validation=claims).outcomes
    tasks = await synthesize_task_results(task_outcomes=outcomes, findings=[], claim_validation=claims,
        evidence_normalization=evidence, llm_call_context_factory=lambda _: None,
        answer_requirements_by_task=answer_requirements_by_task(state))
    draft = await synthesize_report_draft(task_results=tasks, claim_validation=claims,
        evidence_normalization=evidence, llm_call_context_factory=lambda: None)
    supported = any(item.fact_ids for item in tasks)
    response = render_research_report(draft, output_mode="chat", allow_overall_conclusion=False).markdown if supported else ""
    return {"response": response, "answer_status": "partial" if supported else "unavailable",
            "has_supported_content": supported, "publishable": False,
            "research_result": draft.model_dump(), "task_results": [task.model_dump() for task in tasks]}

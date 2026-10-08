"""截止时间内只投影已完成的执行事实，不启动网络取数或模型合成。"""
from __future__ import annotations

from typing import Any
from datetime import datetime, timezone

from backend.graph.execution.evidence_pipeline import normalize_execution_evidence
from backend.graph.renderers.research_report import render_research_report
from backend.graph.synthesis.analysis_requirements import answer_requirements_by_task, requested_task_partition, unconfirmed_request_requirement
from backend.graph.synthesis.contracts import Claim, ClaimValidationResult, EvidenceNormalizationResult
from backend.graph.synthesis.research_synthesis import synthesize_report_draft, synthesize_task_results
from backend.graph.synthesis.task_outcomes import build_task_descriptors, finalize_task_outcomes
from backend.report.evidence_policy import QUALITY_SCHEMA_VERSION
from backend.report.quality_engine import evaluate_result_quality

_NO_FACTS_RESPONSE = "本轮已停止，尚未取得可核验的数据。请求和运行记录已保留，可重试本次研究。"


def _content_delivery(payload: dict[str, Any]) -> dict[str, Any]:
    """只序列化已得出的内容状态；到期出口与正常交付共用 v2 字段。"""
    status = payload["answer_status"]
    supported = bool(payload.get("has_supported_content"))
    missing = payload.get("missing_requirements")
    if missing is None:
        missing = [item for task in payload.get("task_results", []) for item in task.get("missing_requirements", [])]
    state = "warn" if status == "partial" else "block"
    content = {"answer_status": status, "content_status": status, "content_contract_version": "research_content.v2",
               "has_supported_content": supported, "publishable": False, "missing_requirements": missing}
    quality = {"schema_version": QUALITY_SCHEMA_VERSION, "state": state, "evaluated_at": datetime.now(timezone.utc).isoformat(),
               **content, "conclusion_status": "unavailable", "reasons": [{"code": "run_deadline_exceeded", "severity": state,
                   "message": "本轮时间预算已用尽，保留已核验内容与未完成要求。"}]}
    return {**payload, **content, "quality": quality}


async def build_partial_delivery(run) -> dict[str, Any]:
    state = run.compiled_state or {}
    completed = run.completed_step_snapshot()
    subject = state.get("subject") or {}
    trace = state.get("trace") or {}
    request_diagnostics = trace.get("request_requirements") or {}
    compiler_diagnostics = trace.get("request_compiler") or {}
    graph = {"subject": {key: subject[key] for key in ("subject_type", "type", "label", "tickers") if key in subject},
             "output_mode": state.get("output_mode") or run.entry,
             "trace": {"request_requirements": {key: request_diagnostics[key] for key in (
                 "status", "validation_code", "cause_code", "error_code", "provider_attempts", "stage_budget_seconds") if key in request_diagnostics},
                 "request_compiler": {key: compiler_diagnostics[key] for key in ("version", "requirement_count", "task_count", "blocked_count") if key in compiler_diagnostics}}}
    if not state or not completed:
        return _content_delivery({"response": _NO_FACTS_RESPONSE, "answer_status": "unavailable", "graph": graph})
    steps = [step for step, _ in completed.values()]
    results = {key: result for key, (_, result) in completed.items()}
    ready, blocked = requested_task_partition(state)
    plan = {"steps": steps, "tasks": [*ready, *blocked]}
    artifacts = {"step_results": results}
    unconfirmed = unconfirmed_request_requirement(state)
    preserved = run.validated_analysis_snapshot() if unconfirmed is None else {}
    if preserved:
        evidence = EvidenceNormalizationResult.model_validate(next(iter(preserved.values()))["evidence_normalization"])
    else:
        normalize_execution_evidence(state=state, plan_ir=plan, artifacts=artifacts, enrich_snippets=False)
        if not artifacts.get("task_evidence_normalization"):
            return _content_delivery({"response": _NO_FACTS_RESPONSE, "answer_status": "unavailable", "graph": graph})
        evidence = EvidenceNormalizationResult.model_validate(artifacts["task_evidence_normalization"])
    if evidence.quality_block_reasons:
        return _content_delivery({"response": "本轮资料存在来源冲突，尚未交付可核验的结果。请求和运行记录已保留，可重试。", "answer_status": "blocked",
                "blocked_reason_codes": evidence.quality_block_reasons, "graph": graph})
    descriptors = build_task_descriptors(understanding_tasks=ready, blocked_tasks=blocked,
                                         plan_tasks=plan["tasks"], plan_steps=steps).descriptors
    claims = ClaimValidationResult(valid_claims={}, rejected_claims=[], conflicts=[], quality_block_reasons=[])
    for record in preserved.values():
        for raw in record["claims"]:
            claim = Claim.model_validate(raw)
            claims.valid_claims[claim.claim_id] = claim
    outcomes = finalize_task_outcomes(descriptors=descriptors, plan_steps=steps, task_results=results,
                                     evidence_normalization=evidence, claim_validation=claims).outcomes
    tasks = await synthesize_task_results(task_outcomes=outcomes, findings=[], claim_validation=claims,
        evidence_normalization=evidence, llm_call_context_factory=lambda _: None,
        answer_requirements_by_task=answer_requirements_by_task(state))
    if unconfirmed is not None:
        for task in tasks:
            task.status = "partial" if task.fact_ids else "unavailable"
            task.error_codes = list(dict.fromkeys([*task.error_codes, "request_contract_unconfirmed"]))
            missing = {**unconfirmed, "task_id": task.task_id, "status": "partial", "reason": "request_contract_unconfirmed"}
            task.missing_requirements = [missing]
            task.requirement_results = [missing]
    draft = await synthesize_report_draft(task_results=tasks, claim_validation=claims,
        evidence_normalization=evidence, llm_call_context_factory=lambda: None)
    quality = evaluate_result_quality(state={**state, "artifacts": {"research_result": draft.model_dump()}})
    supported = bool(quality["has_supported_content"])
    show_background = unconfirmed is not None and any(item.fact_ids for item in tasks)
    response = render_research_report(draft, output_mode="chat", allow_overall_conclusion=False).markdown if supported or show_background else _NO_FACTS_RESPONSE
    if unconfirmed is not None:
        response = "本轮尚未确认完整请求范围，原问仍未完成：" + str(unconfirmed["source_text"]) + "\n\n以下仅为本轮取得的资料，不代表原问已回答。\n\n" + response
    return _content_delivery({"response": response, "answer_status": "partial" if supported else "unavailable",
            "has_supported_content": supported, "publishable": False,
            "research_result": draft.model_dump(), "task_results": [task.model_dump() for task in tasks],
            **({"missing_requirements": [unconfirmed]} if unconfirmed is not None else {}), "graph": graph})

"""结构化合成编排：保持节点只负责模式选择与阶段调度。"""

from __future__ import annotations

from collections import Counter
from typing import Any

from backend.graph.failure import build_runtime
from backend.graph.state import GraphState
from backend.graph.synthesis.contracts import TaskSynthesisResult, stable_unique
from backend.graph.synthesis.analysis_requirements import analysis_task_modes, answer_requirements_by_task, requested_task_partition
from backend.graph.synthesis.requirement_validation import evaluate_answer_requirements
from backend.graph.synthesis.opinion_readiness import build_opinion_readiness
from backend.graph.synthesis.research_synthesis import (
    build_agent_findings,
    normalize_evidence,
    synthesize_report_draft,
    synthesize_task_results,
    validate_claims,
    evaluate_synthesis_quality,
)
from backend.graph.synthesis.task_outcomes import (
    TaskDescriptor,
    build_task_descriptors,
    finalize_task_outcomes,
)
from backend.services.llm_retry import LLMCallContext


ChatTaskContract = tuple[Any, Any, Any, Any, list[dict[str, Any]], dict[str, Any]]


def _failure_diagnostics_by_stage(draft) -> dict[str, Any]:
    return {
        "tasks": {task.task_id: task.synthesis_validation["failure_diagnostics"] for task in draft.task_results if task.synthesis_validation.get("failure_diagnostics")},
        "report": draft.synthesis_validation.get("failure_diagnostics") or [],
    }


def _requested_dimensions_by_task(state: GraphState, results) -> dict[str, list[str]]:
    dimensions = {}
    requirements = answer_requirements_by_task(state)
    frames = state.get("request_frames") if isinstance(state.get("request_frames"), list) else []
    frame = state.get("request_frame")
    if isinstance(frame, dict) and frame not in frames:
        frames = [*frames, frame]
    for result in results:
        bound = next((frame for frame in frames if isinstance(frame, dict) and str(frame.get("frame_id") or frame.get("id") or "") == result.request_frame_id), None)
        contract = bound.get("intent_contract") if isinstance(bound, dict) and isinstance(bound.get("intent_contract"), dict) else state.get("intent_contract") if len(results) == 1 else {}
        contract = contract if isinstance(contract, dict) else {}
        render = contract.get("render_intent") if isinstance(contract.get("render_intent"), dict) else bound.get("render_contract") if isinstance(bound, dict) and isinstance(bound.get("render_contract"), dict) else {}
        dimensions[result.task_id] = stable_unique([str(value) for value in render.get("dimensions", []) if isinstance(value, str) and value.strip()] + [str(item["dimension"]) for item in requirements.get(result.task_id, []) if item.get("dimension")])
    return dimensions


def _attach_requested_dimensions(state: GraphState, results: list[TaskSynthesisResult]) -> None:
    dimensions = _requested_dimensions_by_task(state, results)
    for result in results:
        result.requested_dimensions = dimensions.get(result.task_id, [])


def prepare_chat_task_contract(
    state: GraphState,
    trace: dict[str, Any],
) -> tuple[GraphState, ChatTaskContract | None]:
    artifacts = dict(state.get("artifacts") or {})
    ready, blocked = requested_task_partition(state)
    ready = [item for item in (ready or []) if isinstance(item, dict)]
    blocked = [item for item in (blocked or []) if isinstance(item, dict)]
    if not ready and not blocked:
        return state, None

    plan = state.get("plan_ir") if isinstance(state.get("plan_ir"), dict) else {}
    plan_tasks = [item for item in (plan.get("tasks") or []) if isinstance(item, dict)]
    plan_steps = [item for item in (plan.get("steps") or []) if isinstance(item, dict)]
    step_results = artifacts.get("step_results") if isinstance(artifacts.get("step_results"), dict) else {}
    agent_outputs = {
        str(step_id): bucket["output"]
        for step_id, bucket in step_results.items()
        if isinstance(bucket, dict) and bucket.get("output") is not None
    }
    descriptor_build = build_task_descriptors(
        understanding_tasks=ready,
        blocked_tasks=blocked,
        plan_tasks=plan_tasks,
        plan_steps=plan_steps,
    )
    evidence_normalization = normalize_evidence(
        task_descriptors=descriptor_build.descriptors,
        plan_steps=plan_steps,
        agent_outputs=agent_outputs,
        raw_evidence_by_task=(
            artifacts.get("evidence_by_task")
            if isinstance(artifacts.get("evidence_by_task"), dict)
            else {}
        ),
    )
    claim_validation = validate_claims(
        run_id=str(state.get("run_id") or trace.get("run_id") or "chat-run"),
        task_descriptors=descriptor_build.descriptors,
        plan_steps=plan_steps,
        agent_outputs=agent_outputs,
        evidence_normalization=evidence_normalization,
    )
    outcome_build = finalize_task_outcomes(
        descriptors=descriptor_build.descriptors,
        plan_steps=plan_steps,
        task_results=step_results,
        evidence_normalization=evidence_normalization,
        claim_validation=claim_validation,
    )
    structural_reasons: list[str] = []
    for reasons in (
        descriptor_build.quality_block_reasons,
        evidence_normalization.quality_block_reasons,
        claim_validation.quality_block_reasons,
        outcome_build.quality_block_reasons,
    ):
        for reason in reasons:
            if reason not in structural_reasons:
                structural_reasons.append(reason)

    requested_counter = Counter(descriptor_build.requested_task_ids)
    outcome_counter = Counter(outcome_build.outcome_task_ids)
    matched_count = sum(
        min(count, outcome_counter.get(task_id, 0))
        for task_id, count in requested_counter.items()
    )
    coverage = (
        matched_count / descriptor_build.requested_task_count
        if descriptor_build.requested_task_count
        else 1.0
    )
    coverage_complete = bool(
        coverage == 1.0
        and not descriptor_build.invalid_task_ordinals
        and not descriptor_build.invalid_order_ordinals
        and not descriptor_build.duplicate_task_ids
        and not outcome_build.duplicate_task_ids
        and requested_counter == outcome_counter
    )
    if not coverage_complete and "task_coverage_mismatch" not in structural_reasons:
        structural_reasons.append("task_coverage_mismatch")

    artifacts.update({
        "task_descriptors": [item.model_dump() for item in descriptor_build.descriptors],
        "task_outcomes": [item.model_dump() for item in outcome_build.outcomes],
        "task_structural_block_reasons": structural_reasons,
        "task_evidence_normalization": evidence_normalization.model_dump(),
        "task_claim_validation": claim_validation.model_dump(),
    })
    trace["task_coverage"] = {
        "requested_task_count": descriptor_build.requested_task_count,
        "requested_task_ids": descriptor_build.requested_task_ids,
        "invalid_task_ordinals": descriptor_build.invalid_task_ordinals,
        "invalid_order_ordinals": descriptor_build.invalid_order_ordinals,
        "outcome_task_ids": outcome_build.outcome_task_ids,
        "missing_task_ids": outcome_build.missing_task_ids,
        "duplicate_task_ids": stable_unique(
            descriptor_build.duplicate_task_ids + outcome_build.duplicate_task_ids
        ),
        "coverage": coverage,
        "complete": coverage_complete,
    }
    next_state: GraphState = {**state, "artifacts": artifacts, "trace": trace}
    contract: ChatTaskContract = (
        descriptor_build,
        evidence_normalization,
        claim_validation,
        outcome_build,
        plan_steps,
        agent_outputs,
    )
    return next_state, contract


async def synthesize_structured_report(
    state: GraphState,
    trace: dict[str, Any],
    *,
    structured_synthesis_mode: str,
    env_mode: str,
) -> tuple[GraphState, dict[str, Any] | None]:
    artifacts = dict(state.get("artifacts") or {})
    ready, blocked = requested_task_partition(state)
    plan = state.get("plan_ir") if isinstance(state.get("plan_ir"), dict) else {}
    plan_tasks = plan.get("tasks") if isinstance(plan.get("tasks"), list) else []
    plan_steps = plan.get("steps") if isinstance(plan.get("steps"), list) else []
    step_results = artifacts.get("step_results") if isinstance(artifacts.get("step_results"), dict) else {}
    agent_outputs = {
        str(step_id): bucket["output"]
        for step_id, bucket in step_results.items()
        if isinstance(bucket, dict) and bucket.get("output") is not None
    }
    descriptor_build = build_task_descriptors(
        understanding_tasks=[item for item in (ready or []) if isinstance(item, dict)],
        blocked_tasks=[item for item in (blocked or []) if isinstance(item, dict)],
        plan_tasks=[item for item in plan_tasks if isinstance(item, dict)],
        plan_steps=[item for item in plan_steps if isinstance(item, dict)],
    )
    if not descriptor_build.descriptors:
        descriptor_build.descriptors.append(TaskDescriptor(
            task_id="__invalid_request_task__",
            title="无效的研究任务",
            priority=50,
            order_index=0,
            operation="qa",
            subject_label="未指定分析对象",
            tickers=[],
            request_frame_id="invalid-request-frame",
            render_kind="single",
            render_group_id="invalid-request-frame",
            intent_status="blocked",
            required_step_ids=[],
            required_evidence=[],
            error_codes=["invalid_task_identity"],
        ))
        descriptor_build.quality_block_reasons.append("invalid_task_identity")
    evidence_normalization = normalize_evidence(
        task_descriptors=descriptor_build.descriptors,
        plan_steps=plan_steps,
        agent_outputs=agent_outputs,
        raw_evidence_by_task=(
            artifacts.get("evidence_by_task")
            if isinstance(artifacts.get("evidence_by_task"), dict)
            else {}
        ),
    )
    run_id = str(state.get("run_id") or trace.get("run_id") or "research-run").strip() or "research-run"
    claim_validation = validate_claims(
        run_id=run_id,
        task_descriptors=descriptor_build.descriptors,
        plan_steps=plan_steps,
        agent_outputs=agent_outputs,
        evidence_normalization=evidence_normalization,
    )
    outcome_build = finalize_task_outcomes(
        descriptors=descriptor_build.descriptors,
        plan_steps=plan_steps,
        task_results=step_results,
        evidence_normalization=evidence_normalization,
        claim_validation=claim_validation,
    )
    findings = build_agent_findings(
        task_outcomes=outcome_build.outcomes,
        plan_steps=plan_steps,
        agent_outputs=agent_outputs,
        claim_validation=claim_validation,
        evidence_normalization=evidence_normalization,
    )
    task_synthesis = await synthesize_task_results(
        requested_dimensions_by_task=_requested_dimensions_by_task(state, outcome_build.outcomes),
        answer_requirements_by_task=answer_requirements_by_task(state),
        task_outcomes=outcome_build.outcomes,
        findings=findings,
        claim_validation=claim_validation,
        evidence_normalization=evidence_normalization,
        llm_call_context_factory=(
            lambda task: LLMCallContext.create(
                stage="report_task_synthesize", agent=f"task_synthesis:{task.task_id}", layer="synthesis",
            )
            if structured_synthesis_mode == "on" and env_mode in {"llm", "narrative"} and analysis_task_modes(state).get(task.task_id, "research") == "research"
            else None
        ),
    )
    _attach_requested_dimensions(state, task_synthesis)
    report_draft = await synthesize_report_draft(
        task_results=task_synthesis,
        claim_validation=claim_validation,
        evidence_normalization=evidence_normalization,
        llm_call_context_factory=(
            lambda: LLMCallContext.create(
                stage="report_synthesize", agent="research_report", layer="synthesis",
            )
            if structured_synthesis_mode == "on" and env_mode in {"llm", "narrative"}
            else None
        ),
    )
    structural_reasons: list[str] = []
    for reasons in (
        descriptor_build.quality_block_reasons,
        evidence_normalization.quality_block_reasons,
        claim_validation.quality_block_reasons,
        outcome_build.quality_block_reasons,
    ):
        for reason in reasons:
            if reason not in structural_reasons:
                structural_reasons.append(reason)
    structured_artifacts = {
        "research_result": report_draft.model_dump(),
        "research_synthesis_draft": report_draft.model_dump(),
        "research_requested_task_ids": descriptor_build.requested_task_ids,
        "research_structural_block_reasons": structural_reasons,
        "research_task_outcomes": [item.model_dump() for item in outcome_build.outcomes],
        "research_agent_findings": [item.model_dump() for item in findings],
    }
    artifacts.update(structured_artifacts)
    trace.update({
        "llm_failure_diagnostics": _failure_diagnostics_by_stage(report_draft),
        "synthesize_runtime": build_runtime(
            mode="research_structured", fallback=report_draft.fallback_used or any(task.fallback_used for task in task_synthesis),
            reason=next(iter(report_draft.error_codes + [code for task in task_synthesis if task.fallback_used for code in task.error_codes if code.startswith(("llm_", "task_synthesis_", "explanation_"))]), None),
        ),
        "research_synthesis": {
            "mode": structured_synthesis_mode,
            "task_count": len(task_synthesis),
            "structural_reasons": structural_reasons,
        },
    })
    return state, {"artifacts": artifacts, "trace": trace}


async def prepare_opinion_synthesis(
    state: GraphState,
    chat_task_contract: ChatTaskContract | None,
    *,
    structured_synthesis_mode: str,
    env_mode: str,
) -> GraphState:
    if chat_task_contract is None:
        return state

    artifacts = dict(state.get("artifacts") or {})
    (
        descriptor_build,
        evidence_normalization,
        claim_validation,
        outcome_build,
        plan_steps,
        agent_outputs,
    ) = chat_task_contract
    findings = build_agent_findings(
        task_outcomes=outcome_build.outcomes,
        plan_steps=plan_steps,
        agent_outputs=agent_outputs,
        claim_validation=claim_validation,
        evidence_normalization=evidence_normalization,
    )
    research_outcomes = outcome_build.outcomes
    if not research_outcomes:
        artifacts.update({
            "research_result_quality": {"state": "block", "reasons": descriptor_build.quality_block_reasons or ["missing_task_contract"]},
            "quality_blocked": True, "publishable": False,
            "error_code": "missing_task_contract",
            "draft_markdown": "[数据缺失] 本轮没有取得可用的研究结果，现有上下文已保留。\n",
        })
        return {**state, "artifacts": artifacts}
    quality_blocked = bool(
        descriptor_build.quality_block_reasons
        or evidence_normalization.quality_block_reasons
        or claim_validation.quality_block_reasons
        or outcome_build.quality_block_reasons
    )
    if quality_blocked:
        task_synthesis = [
            TaskSynthesisResult(
                task_id=item.task_id,
                title=item.title,
                request_text=item.request_text,
                priority=item.priority,
                order_index=item.order_index,
                request_frame_id=item.request_frame_id,
                render_kind=item.render_kind,
                render_group_id=item.render_group_id,
                status="unavailable",
                conclusion=None,
                claim_ids=[],
                evidence_ids=[],
                proposed_direction=None,
                direction_supporting_claim_ids=[],
                agent_names=[],
                agreements=[],
                disagreements=[],
                conflicts=[],
                risks=[],
                limitations=[],
                fallback_used=False,
                error_codes=[*item.error_codes, "synthesis_quality_blocked"],
                fact_ids=[evidence.source_id for evidence in evidence_normalization.evidence_by_task.get(item.task_id, []) if evidence.usage == "fact"],
                missing_evidence=item.missing_evidence, subject=item.subject_label, operation=item.operation,
                requested_subjects=item.tickers,
            )
            for item in research_outcomes
        ]
    else:
        task_modes = analysis_task_modes(state)
        task_synthesis = await synthesize_task_results(
            requested_dimensions_by_task=_requested_dimensions_by_task(state, research_outcomes),
            answer_requirements_by_task=answer_requirements_by_task(state),
            task_outcomes=research_outcomes,
            findings=findings,
            claim_validation=claim_validation,
            evidence_normalization=evidence_normalization,
            llm_call_context_factory=(
                lambda task: LLMCallContext.create(
                    stage="synthesize", agent=f"task_synthesis:{task.task_id}", layer="synthesis",
                )
                if structured_synthesis_mode == "on" and env_mode == "llm" and task_modes.get(task.task_id, (state.get("trace") or {}).get("analysis", {}).get("mode", "research")) != "deterministic"
                else None
            ),
        )
    if quality_blocked:
        requirements = answer_requirements_by_task(state)
        for result in task_synthesis:
            evaluate_answer_requirements(
                result=result, requirements=requirements.get(result.task_id, []),
                evidence_index=evidence_normalization.evidence_index, claim_index=claim_validation.valid_claims,
                subjects=next(outcome.tickers for outcome in research_outcomes if outcome.task_id == result.task_id),
            )
    results_by_task = {item.task_id: item for item in task_synthesis}
    _attach_requested_dimensions(state, task_synthesis)
    research_result = await synthesize_report_draft(
        task_results=task_synthesis,
        claim_validation=claim_validation,
        evidence_normalization=evidence_normalization,
        llm_call_context_factory=lambda: None,
    )
    structural_reasons = stable_unique([
        *descriptor_build.quality_block_reasons, *evidence_normalization.quality_block_reasons,
        *claim_validation.quality_block_reasons, *outcome_build.quality_block_reasons,
    ])
    gate = evaluate_synthesis_quality(
        draft=research_result, requested_task_ids=descriptor_build.requested_task_ids,
        evidence_index=evidence_normalization.evidence_index,
        structural_block_reasons=structural_reasons, require_claims=False,
    )
    artifacts["research_result"] = research_result.model_dump()
    artifacts["research_result_quality"] = gate.model_dump()
    artifacts["research_requested_task_ids"] = descriptor_build.requested_task_ids
    artifacts["research_structural_block_reasons"] = structural_reasons
    readiness_by_task = {}
    for outcome in research_outcomes:
        if outcome.operation != "investment_opinion":
            continue
        result = results_by_task[outcome.task_id]
        readiness = build_opinion_readiness(
            task_outcome=outcome,
            task_result=result,
            claim_validation=claim_validation,
            evidence_normalization=evidence_normalization,
        )
        readiness_by_task[outcome.task_id] = readiness.model_dump()
    artifacts["opinion_synthesis"] = {
        "evidence_normalization": evidence_normalization.model_dump(),
        "claim_validation": claim_validation.model_dump(),
        "task_results_by_task": {
            key: value.model_dump() for key, value in results_by_task.items()
        },
        "readiness_by_task": readiness_by_task,
    }
    trace = state.get("trace") if isinstance(state.get("trace"), dict) else {}
    trace["llm_failure_diagnostics"] = _failure_diagnostics_by_stage(research_result)
    return {**state, "artifacts": artifacts, "trace": trace}


__all__ = [
    "ChatTaskContract",
    "prepare_chat_task_contract",
    "prepare_opinion_synthesis",
    "synthesize_structured_report",
]

# -*- coding: utf-8 -*-
"""深度研究的规范化、校验与结构化合成流水线。"""
from __future__ import annotations

import json
import math
from collections.abc import Callable
from typing import Any, Literal

from langchain_core.messages import HumanMessage
from pydantic import Field

from backend.graph.intent_contract import EvidenceKind
from backend.graph.synthesis.contracts import (
    SCHEMA_VERSION,
    AgentFinding,
    Claim,
    ClaimConflict,
    ClaimValidationResult,
    EvidenceDimension,
    EvidenceNormalizationResult,
    NonEmptyStr,
    NormalizedEvidence,
    RejectedClaim,
    RejectedEvidence,
    ReportSynthesisDraft,
    ReportSynthesisResult,
    StrictContract,
    SynthesisQualityGateResult,
    TaskStatus,
    TaskSynthesisResult,
    aggregate_task_status,
    stable_unique,
)
from backend.graph.synthesis.task_outcomes import TaskDescriptor, TaskOutcome
from backend.services.llm_retry import LLMCallContext, ainvoke_configured_llm

_EVIDENCE_KINDS = set(EvidenceKind.__args__)
_STANCE = {"bull", "bear", "neutral", "risk", "unknown"}
_DIMENSIONS = {
    "market", "technical", "fundamental", "valuation", "earnings",
    "catalyst", "risk", "macro", "news", "unknown",
}
_KIND_DIMENSION: dict[str, EvidenceDimension] = {
    "price_snapshot": "market", "performance_comparison": "market",
    "technical_snapshot": "technical", "company_profile": "fundamental",
    "fundamental_snapshot": "fundamental", "filing_context": "fundamental",
    "holdings_ownership": "fundamental", "earnings_estimates": "earnings",
    "transcript_context": "earnings", "event_calendar": "catalyst",
    "risk_profile": "risk", "options_derivatives": "risk",
    "macro_context": "macro", "news_context": "news", "document_context": "unknown",
}
_AGENT_DIMENSION: dict[str, EvidenceDimension] = {
    "price_agent": "market", "technical_agent": "technical",
    "fundamental_agent": "fundamental", "macro_agent": "macro",
    "risk_agent": "risk", "news_agent": "news", "deep_search_agent": "unknown",
}


class _TaskSynthesisSelection(StrictContract):
    """LLM 只能选择已经通过校验的 Claim，不能创建新的事实。"""

    claim_ids: list[NonEmptyStr]
    conclusion_claim_id: NonEmptyStr | None = None
    proposed_direction: Literal["bull", "bear", "neutral"] | None = None
    direction_supporting_claim_ids: list[NonEmptyStr]


class _ReportSynthesisSelection(StrictContract):
    """报告层只生成总括文本并声明其来源 task。"""

    overall_conclusion: NonEmptyStr
    supporting_task_ids: list[NonEmptyStr] = Field(min_length=1)


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _strings(value: Any) -> list[str]:
    if isinstance(value, (str, int, float)):
        value = [value]
    if not isinstance(value, list):
        return []
    return stable_unique([_text(item) for item in value if _text(item)])


def _step_task_ids(step: dict[str, Any]) -> list[str]:
    values = _strings(step.get("task_ids"))
    for item in _strings(step.get("task_id")):
        if item not in values:
            values.append(item)
    return values


def _meta(raw: dict[str, Any]) -> dict[str, Any]:
    return raw.get("meta") if isinstance(raw.get("meta"), dict) else {}


def _kind(raw: dict[str, Any], step: dict[str, Any] | None) -> str:
    meta = _meta(raw)
    for value in (raw.get("kind"), meta.get("evidence_kind"), meta.get("kind")):
        normalized = _text(value)
        if normalized in _EVIDENCE_KINDS:
            return normalized
    inputs = step.get("inputs") if isinstance(step, dict) and isinstance(step.get("inputs"), dict) else {}
    required = [item for item in _strings(inputs.get("required_evidence")) if item in _EVIDENCE_KINDS]
    return required[0] if len(required) == 1 else "unknown"


def _display_text(raw: dict[str, Any]) -> str:
    for key in ("text", "snippet", "title"):
        value = _text(raw.get(key))
        if value:
            return value
    structured = raw.get("value", raw.get("data"))
    if structured not in (None, "", [], {}):
        try:
            return json.dumps(structured, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except (TypeError, ValueError):
            return ""
    return ""


def _market_price(raw: dict[str, Any], kind: str) -> float | None:
    if kind != "price_snapshot":
        return None
    meta = _meta(raw)
    for key in ("market_price", "current_price", "price", "close"):
        value = raw.get(key, meta.get(key))
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number) and number > 0:
            return number
    return None


def _agent_output_entries(
    plan_steps: list[dict[str, Any]], agent_outputs: dict[str, Any]
) -> list[tuple[dict[str, Any] | None, dict[str, Any]]]:
    result: list[tuple[dict[str, Any] | None, dict[str, Any]]] = []
    consumed: set[str] = set()
    for step in plan_steps:
        if _text(step.get("kind")) != "agent":
            continue
        step_id = _text(step.get("id"))
        output = agent_outputs.get(step_id)
        if isinstance(output, dict) and isinstance(output.get("output"), dict):
            output = output["output"]
        if isinstance(output, dict):
            result.append((step, output))
            consumed.add(step_id)
    for key, output in agent_outputs.items():
        if key in consumed:
            continue
        if isinstance(output, dict) and isinstance(output.get("output"), dict):
            output = output["output"]
        if isinstance(output, dict):
            result.append((None, output))
    return result


def normalize_evidence(
    *,
    task_descriptors: list[TaskDescriptor],
    plan_steps: list[dict[str, Any]],
    agent_outputs: dict[str, Any],
    raw_evidence_by_task: dict[str, list[dict[str, Any]]],
) -> EvidenceNormalizationResult:
    descriptor_ids = {item.task_id for item in task_descriptors}
    candidates: list[tuple[dict[str, Any], list[str], dict[str, Any] | None, str | None]] = []
    for task_id, items in raw_evidence_by_task.items():
        if not isinstance(items, list):
            continue
        for raw in items:
            if isinstance(raw, dict):
                candidates.append((raw, [task_id] if task_id in descriptor_ids else [], None, None))
    for step, output in _agent_output_entries(plan_steps, agent_outputs):
        bindings = [item for item in (_step_task_ids(step) if step else _strings(output.get("task_ids"))) if item in descriptor_ids]
        agent_name = _text(output.get("agent_name")) or (_text(step.get("name")) if step else "") or None
        for raw in output.get("evidence", []) if isinstance(output.get("evidence"), list) else []:
            if isinstance(raw, dict):
                explicit = _strings(raw.get("task_ids")) + _strings(raw.get("task_id"))
                merged = stable_unique([item for item in bindings + explicit if item in descriptor_ids])
                candidates.append((raw, merged, step, agent_name))

    evidence_index: dict[str, NormalizedEvidence] = {}
    rejected: list[RejectedEvidence] = []
    quality: list[str] = []
    for ordinal, (raw, inherited_bindings, step, inherited_agent) in enumerate(candidates):
        meta = _meta(raw)
        source_id = _text(raw.get("source_id") or meta.get("source_id"))
        explicit = _strings(raw.get("task_ids")) + _strings(raw.get("task_id"))
        task_ids = stable_unique([item for item in inherited_bindings + explicit if item in descriptor_ids])
        agent_name = _optional_text(raw.get("agent_name") or inherited_agent)
        if not source_id:
            rejected.append(RejectedEvidence(ordinal=ordinal, source_id=None, task_ids=task_ids, agent_name=agent_name, reason_code="missing_source_id"))
            continue
        if not task_ids:
            rejected.append(RejectedEvidence(ordinal=ordinal, source_id=source_id, task_ids=[], agent_name=agent_name, reason_code="missing_task_binding"))
            continue
        text = _display_text(raw)
        if not text:
            rejected.append(RejectedEvidence(ordinal=ordinal, source_id=source_id, task_ids=task_ids, agent_name=agent_name, reason_code="empty_evidence_content"))
            continue
        kind = _kind(raw, step)
        promoted = {
            key: _optional_text(raw.get(key) if raw.get(key) is not None else meta.get(key))
            for key in ("title", "source_name", "url", "as_of")
        }
        evidence = NormalizedEvidence(
            source_id=source_id, task_ids=task_ids, agent_name=agent_name,
            kind=kind, text=text, market_price=_market_price(raw, kind), **promoted,
        )
        existing = evidence_index.get(source_id)
        if existing is None:
            evidence_index[source_id] = evidence
            continue
        existing_content = existing.model_dump(exclude={"task_ids"})
        new_content = evidence.model_dump(exclude={"task_ids"})
        if existing_content != new_content:
            rejected.append(RejectedEvidence(ordinal=ordinal, source_id=source_id, task_ids=task_ids, agent_name=agent_name, reason_code="evidence_id_content_conflict"))
            quality.append("evidence_id_content_conflict")
            continue
        merged_task_ids = stable_unique(existing.task_ids + task_ids)
        evidence_index[source_id] = existing.model_copy(update={"task_ids": merged_task_ids})

    by_task: dict[str, list[NormalizedEvidence]] = {item.task_id: [] for item in task_descriptors}
    for evidence in evidence_index.values():
        for task_id in evidence.task_ids:
            if task_id in by_task:
                by_task[task_id].append(evidence)
    return EvidenceNormalizationResult(
        evidence_by_task=by_task,
        evidence_index=evidence_index,
        rejected_evidence=rejected,
        quality_block_reasons=quality,
    )


def _dimension(raw: dict[str, Any], evidence: list[NormalizedEvidence], step: dict[str, Any] | None, agent_name: str) -> EvidenceDimension:
    raw_dimension = _text(raw.get("dimension"))
    kinds = {item.kind for item in evidence}
    mapped = {_KIND_DIMENSION.get(item.kind, "unknown") for item in evidence}
    compatible = False
    if raw_dimension in _DIMENSIONS:
        if raw_dimension == "valuation":
            compatible = bool(kinds & {"price_snapshot", "performance_comparison"}) and bool(kinds & {"company_profile", "fundamental_snapshot", "filing_context", "holdings_ownership", "earnings_estimates", "transcript_context"})
        elif raw_dimension == "catalyst":
            compatible = bool(kinds & {"event_calendar", "news_context"})
        else:
            compatible = mapped == {raw_dimension}
        if compatible:
            return raw_dimension  # type: ignore[return-value]
    if len(mapped) == 1:
        return next(iter(mapped))
    inputs = step.get("inputs") if isinstance(step, dict) and isinstance(step.get("inputs"), dict) else {}
    required = {_KIND_DIMENSION[item] for item in _strings(inputs.get("required_evidence")) if item in _KIND_DIMENSION}
    if len(required) == 1:
        return next(iter(required))
    return _AGENT_DIMENSION.get(agent_name, "unknown")


def _claim_content(claim: Claim) -> dict[str, Any]:
    return claim.model_dump(exclude={"claim_id"})


def _directional_family(stance: str) -> str | None:
    return stance if stance in {"bull", "bear", "neutral"} else None


def _build_conflicts(claims: dict[str, Claim]) -> list[ClaimConflict]:
    result: list[ClaimConflict] = []
    by_task: dict[str, list[Claim]] = {}
    for claim in claims.values():
        by_task.setdefault(claim.task_id, []).append(claim)
    for task_id, items in by_task.items():
        ordered = sorted(items, key=lambda item: item.claim_id)
        for index, left in enumerate(ordered):
            left_family = _directional_family(left.stance)
            if left_family is None:
                continue
            for right in ordered[index + 1:]:
                right_family = _directional_family(right.stance)
                if right_family is None or right_family == left_family:
                    continue
                ids = [left.claim_id, right.claim_id]
                result.append(ClaimConflict(
                    conflict_id=f"conflict:{task_id}:{ids[0]}:{ids[1]}",
                    task_id=task_id, claim_ids=ids,
                    material=left.confidence >= 0.60 and right.confidence >= 0.60,
                    resolved=False, affects_direction=True,
                ))
    return result


def validate_claims(
    *,
    run_id: str,
    task_descriptors: list[TaskDescriptor],
    plan_steps: list[dict[str, Any]],
    agent_outputs: dict[str, Any],
    evidence_normalization: EvidenceNormalizationResult,
) -> ClaimValidationResult:
    task_ids = {item.task_id for item in task_descriptors}
    valid: dict[str, Claim] = {}
    rejected: list[RejectedClaim] = []
    quality: list[str] = []
    ordinal = 0
    for step, output in _agent_output_entries(plan_steps, agent_outputs):
        bindings = [item for item in (_step_task_ids(step) if step else _strings(output.get("task_ids"))) if item in task_ids]
        default_agent = _text(output.get("agent_name")) or (_text(step.get("name")) if step else "")
        raw_claims = output.get("raw_claims") if isinstance(output.get("raw_claims"), list) else []
        for raw in raw_claims:
            current_ordinal = ordinal
            ordinal += 1
            if not isinstance(raw, dict):
                rejected.append(RejectedClaim(ordinal=current_ordinal, reason_code="missing_claim_identity"))
                continue
            claim_id = _optional_text(raw.get("claim_id") or raw.get("id"))
            task_id = _text(raw.get("task_id"))
            if not task_id and len(bindings) == 1:
                task_id = bindings[0]
            agent_name = _text(raw.get("agent_name")) or default_agent
            text = _text(raw.get("text") or raw.get("claim"))
            stance = _text(raw.get("stance")).lower()
            evidence_ids = _strings(raw.get("evidence_ids") or raw.get("source_ids"))
            if not text:
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=claim_id, task_id=task_id or None, agent_name=agent_name or None, reason_code="empty_claim_text"))
                continue
            if stance not in _STANCE:
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=claim_id, task_id=task_id or None, agent_name=agent_name or None, reason_code="invalid_claim_stance"))
                continue
            try:
                confidence = float(raw.get("confidence"))
            except (TypeError, ValueError):
                confidence = math.nan
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=claim_id, task_id=task_id or None, agent_name=agent_name or None, reason_code="invalid_confidence"))
                continue
            if not task_id or task_id not in task_ids or not agent_name:
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=claim_id, task_id=task_id or None, agent_name=agent_name or None, reason_code="missing_claim_identity"))
                continue
            if not evidence_ids:
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=claim_id, task_id=task_id, agent_name=agent_name, reason_code="missing_evidence_reference"))
                continue
            referenced: list[NormalizedEvidence] = []
            reason: str | None = None
            for evidence_id in evidence_ids:
                evidence = evidence_normalization.evidence_index.get(evidence_id)
                if evidence is None:
                    reason = "invalid_claim_reference"
                    break
                if task_id not in evidence.task_ids:
                    reason = "cross_task_claim_reference"
                    break
                referenced.append(evidence)
            if reason:
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=claim_id, task_id=task_id, agent_name=agent_name, reason_code=reason))  # type: ignore[arg-type]
                quality.append(reason)
                continue
            normalized_id = claim_id or f"claim:{run_id}:{task_id}:{agent_name}:{current_ordinal}"
            claim = Claim(
                claim_id=normalized_id, task_id=task_id, agent_name=agent_name, text=text,
                stance=stance, dimension=_dimension(raw, referenced, step, agent_name),
                confidence=confidence, evidence_ids=evidence_ids,
                limitations=_strings(raw.get("limitations")),
            )
            existing = valid.get(normalized_id)
            if existing is None:
                valid[normalized_id] = claim
            elif _claim_content(existing) != _claim_content(claim):
                rejected.append(RejectedClaim(ordinal=current_ordinal, claim_id=normalized_id, task_id=task_id, agent_name=agent_name, reason_code="claim_id_content_conflict"))
                quality.append("claim_id_content_conflict")
    return ClaimValidationResult(
        valid_claims=valid, rejected_claims=rejected,
        conflicts=_build_conflicts(valid), quality_block_reasons=quality,
    )


def build_agent_findings(
    *,
    task_outcomes: list[TaskOutcome],
    plan_steps: list[dict[str, Any]],
    agent_outputs: dict[str, Any],
    claim_validation: ClaimValidationResult,
    evidence_normalization: EvidenceNormalizationResult,
) -> list[AgentFinding]:
    outcomes = {item.task_id: item for item in task_outcomes}
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for step, output in _agent_output_entries(plan_steps, agent_outputs):
        bindings = [item for item in (_step_task_ids(step) if step else _strings(output.get("task_ids"))) if item in outcomes]
        agent = _text(output.get("agent_name")) or (_text(step.get("name")) if step else "")
        if not agent:
            continue
        for task_id in bindings:
            grouped.setdefault((task_id, agent), []).append(output)
    findings: list[AgentFinding] = []
    for (task_id, agent), outputs in grouped.items():
        outcome = outcomes[task_id]
        claims = [item for item in claim_validation.valid_claims.values() if item.task_id == task_id and item.agent_name == agent]
        evidence_ids = stable_unique([evidence_id for claim in claims for evidence_id in claim.evidence_ids])
        has_evidence = any(item.agent_name == agent for item in evidence_normalization.evidence_by_task.get(task_id, []))
        fallback = any(bool(item.get("fallback_used")) for item in outputs)
        risks = stable_unique([value for item in outputs for value in _strings(item.get("risks"))])
        summaries = stable_unique([_text(item.get("summary")) for item in outputs if _text(item.get("summary"))])
        limitations = stable_unique([value for claim in claims for value in claim.limitations])
        if summaries and not claims:
            limitations.extend(item for item in summaries if item not in limitations)
            fallback = True
        errors = stable_unique([_text(item.get("fallback_reason") or item.get("error_code")) for item in outputs if _text(item.get("fallback_reason") or item.get("error_code"))])
        if outcome.status == "blocked":
            status: TaskStatus = "blocked"
        elif claims:
            status = "answered" if outcome.status == "answered" else "partial"
        elif has_evidence:
            status = "partial"
        else:
            status = "unavailable"
        findings.append(AgentFinding(
            task_id=task_id, agent_name=agent, status=status,
            conclusion=claims[0].text if claims else None,
            claim_ids=[item.claim_id for item in claims], evidence_ids=evidence_ids,
            risks=risks, limitations=limitations, fallback_used=fallback,
            error_codes=errors or (["agent_output_unavailable"] if status == "unavailable" else []),
        ))
    return findings


def _min_status(left: TaskStatus, right: TaskStatus) -> TaskStatus:
    rank = {"answered": 0, "partial": 1, "unavailable": 2, "blocked": 3}
    return left if rank[left] >= rank[right] else right


def _response_payload(response: Any) -> Any:
    if isinstance(response, (StrictContract, dict)):
        return response
    content = getattr(response, "content", response)
    if isinstance(content, dict):
        return content
    text = _text(content)
    if not text:
        raise ValueError("empty_structured_synthesis_response")
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```")
        text = text.removesuffix("```").strip()
    return json.loads(text)


async def _invoke_structured(
    *,
    prompt: str,
    context: LLMCallContext,
    schema: type[StrictContract],
    stage: str,
) -> StrictContract:
    """结构化解析失败时复用同一 context，修复请求不能重置预算。"""
    current_prompt = prompt
    last_error: Exception | None = None
    while context.budget.remaining > 0:
        response = await ainvoke_configured_llm(
            [HumanMessage(content=current_prompt)],
            context=context,
            temperature=0.1,
            max_tokens=1800,
            request_timeout=120,
            acquire_timeout_seconds=45,
            acquire_token=True,
            client_transform=lambda client: client.with_structured_output(schema),
        )
        try:
            return schema.model_validate(_response_payload(response))
        except Exception as exc:
            last_error = exc
            if context.budget.remaining <= 0:
                break
            current_prompt = (
                f"{prompt}\n\n上一次输出未通过 {stage} schema 校验。"
                "只返回符合 schema 的对象；不得添加输入中不存在的 ID。"
            )
    raise ValueError(f"{stage}_structured_output_invalid") from last_error


def _fallback_task_result(
    *,
    outcome: TaskOutcome,
    findings: list[AgentFinding],
    claims: list[Claim],
    conflicts: list[ClaimConflict],
    evidence_normalization: EvidenceNormalizationResult,
    llm_failed: bool,
) -> TaskSynthesisResult:
    common = dict(
        task_id=outcome.task_id, title=outcome.title, priority=outcome.priority,
        order_index=outcome.order_index, request_frame_id=outcome.request_frame_id,
        render_kind=outcome.render_kind, render_group_id=outcome.render_group_id,
    )
    if outcome.status == "blocked":
        return TaskSynthesisResult(
            **common, status="blocked", conclusion=None, claim_ids=[], evidence_ids=[],
            proposed_direction=None, direction_supporting_claim_ids=[], agent_names=[],
            agreements=[], disagreements=[], conflicts=[], risks=[], limitations=[],
            fallback_used=False, error_codes=outcome.error_codes,
        )

    families = stable_unique([
        family for item in claims if (family := _directional_family(item.stance))
    ])
    ordered = sorted(enumerate(claims), key=lambda item: (-item[1].confidence, item[0]))
    conclusion: str | None = None
    disagreements: list[str] = []
    proposal: str | None = None
    supporting: list[str] = []
    status = outcome.status
    selected_claims: list[Claim] = []
    if len(families) == 1 and ordered:
        selected_claims = [item for item in claims if item.stance == families[0]]
        conclusion = ordered[0][1].text
        proposal = families[0]
        supporting = [item.claim_id for item in selected_claims]
        status = _min_status(status, "partial")
    elif len(families) >= 2:
        selected_claims = list(claims)
        disagreements = [item.text for item in claims]
        status = "partial"
    elif ordered:
        selected_claims = [ordered[0][1]]
        conclusion = ordered[0][1].text
        status = _min_status(status, "partial")
    elif evidence_normalization.evidence_by_task.get(outcome.task_id):
        status = "partial"
    else:
        status = "unavailable"

    limitations = stable_unique([
        value for item in claims for value in item.limitations
    ] + [value for item in findings for value in item.limitations])
    if llm_failed:
        limitations.append("模型合成不可用，结论来自已校验证据")
    claim_ids = [item.claim_id for item in selected_claims]
    evidence_ids = stable_unique([
        source_id for item in selected_claims for source_id in item.evidence_ids
    ])
    finding_fallback = any(item.fallback_used for item in findings)
    error_codes = list(outcome.error_codes)
    if llm_failed:
        error_codes.append("llm_unavailable")
    return TaskSynthesisResult(
        **common, status=status, conclusion=conclusion, claim_ids=claim_ids,
        evidence_ids=evidence_ids, proposed_direction=proposal,
        direction_supporting_claim_ids=supporting,
        agent_names=[item.agent_name for item in findings], agreements=[],
        disagreements=disagreements, conflicts=conflicts,
        risks=stable_unique([value for item in findings for value in item.risks]),
        limitations=limitations, fallback_used=finding_fallback or llm_failed,
        error_codes=stable_unique(error_codes),
    )


async def synthesize_task_results(
    *,
    task_outcomes: list[TaskOutcome],
    findings: list[AgentFinding],
    claim_validation: ClaimValidationResult,
    evidence_normalization: EvidenceNormalizationResult,
    llm_call_context_factory: Callable[[TaskOutcome], LLMCallContext | None],
) -> list[TaskSynthesisResult]:
    results: list[TaskSynthesisResult] = []
    for outcome in task_outcomes:
        task_findings = [item for item in findings if item.task_id == outcome.task_id]
        if outcome.status == "blocked":
            results.append(_fallback_task_result(
                outcome=outcome, findings=task_findings, claims=[], conflicts=[],
                evidence_normalization=evidence_normalization, llm_failed=False,
            ))
            continue
        claims = [item for item in claim_validation.valid_claims.values() if item.task_id == outcome.task_id]
        conflicts = [item for item in claim_validation.conflicts if item.task_id == outcome.task_id]
        context = llm_call_context_factory(outcome) if claims else None
        if context is None:
            results.append(_fallback_task_result(
                outcome=outcome, findings=task_findings, claims=claims, conflicts=conflicts,
                evidence_normalization=evidence_normalization, llm_failed=True,
            ))
            continue
        prompt_payload = {
            "task": {"task_id": outcome.task_id, "title": outcome.title, "status": outcome.status},
            "claims": [item.model_dump(mode="json") for item in claims],
            "evidence": [
                item.model_dump(mode="json")
                for item in evidence_normalization.evidence_by_task.get(outcome.task_id, [])
            ],
            "risks": stable_unique([value for item in task_findings for value in item.risks]),
            "limitations": stable_unique([value for item in task_findings for value in item.limitations]),
        }
        try:
            selection = await _invoke_structured(
                prompt=(
                    "从输入 Claim 中选择本任务应展示的论据和结论。只能返回输入中的 ID，"
                    "不得生成新的事实、ID 或解决冲突。\n"
                    + json.dumps(prompt_payload, ensure_ascii=False, sort_keys=True)
                ),
                context=context, schema=_TaskSynthesisSelection, stage="task_synthesis",
            )
            assert isinstance(selection, _TaskSynthesisSelection)
            claim_by_id = {item.claim_id: item for item in claims}
            selected_ids = selection.claim_ids
            if any(item not in claim_by_id for item in selected_ids):
                raise ValueError("task_synthesis_unknown_claim_id")
            if selection.conclusion_claim_id and selection.conclusion_claim_id not in selected_ids:
                raise ValueError("task_synthesis_conclusion_not_selected")
            support = selection.direction_supporting_claim_ids
            if any(item not in selected_ids for item in support):
                raise ValueError("task_synthesis_direction_reference_invalid")
            if selection.proposed_direction is None and support:
                raise ValueError("task_synthesis_direction_without_proposal")
            if selection.proposed_direction is not None and (
                not support
                or any(claim_by_id[item].stance != selection.proposed_direction for item in support)
            ):
                raise ValueError("task_synthesis_direction_stance_mismatch")
            selected_claims = [claim_by_id[item] for item in selected_ids]
            conclusion = (
                claim_by_id[selection.conclusion_claim_id].text
                if selection.conclusion_claim_id else None
            )
            status = outcome.status if conclusion else _min_status(outcome.status, "partial")
            finding_fallback = any(item.fallback_used for item in task_findings)
            results.append(TaskSynthesisResult(
                task_id=outcome.task_id, title=outcome.title, priority=outcome.priority,
                order_index=outcome.order_index, request_frame_id=outcome.request_frame_id,
                render_kind=outcome.render_kind, render_group_id=outcome.render_group_id,
                status=status, conclusion=conclusion, claim_ids=selected_ids,
                evidence_ids=stable_unique([
                    source_id for item in selected_claims for source_id in item.evidence_ids
                ]),
                proposed_direction=selection.proposed_direction,
                direction_supporting_claim_ids=support,
                agent_names=[item.agent_name for item in task_findings], agreements=[],
                disagreements=[item.text for item in claims] if len({item.stance for item in claims if _directional_family(item.stance)}) > 1 else [],
                conflicts=conflicts,
                risks=stable_unique([value for item in task_findings for value in item.risks]),
                limitations=stable_unique([value for item in task_findings for value in item.limitations]),
                fallback_used=finding_fallback, error_codes=outcome.error_codes,
            ))
        except Exception:
            results.append(_fallback_task_result(
                outcome=outcome, findings=task_findings, claims=claims, conflicts=conflicts,
                evidence_normalization=evidence_normalization, llm_failed=True,
            ))
    return results


async def synthesize_report_draft(
    *,
    task_results: list[TaskSynthesisResult],
    claim_validation: ClaimValidationResult,
    evidence_normalization: EvidenceNormalizationResult,
    llm_call_context_factory: Callable[[], LLMCallContext | None],
) -> ReportSynthesisDraft:
    conclusions = [item.conclusion for item in task_results if item.conclusion]
    fallback_overall = None
    if len(task_results) == 1 and conclusions:
        fallback_overall = conclusions[0]
    elif conclusions:
        fallback_overall = f"本轮完成 {len(conclusions)}/{len(task_results)} 个任务，无法形成统一总判断"
    context = llm_call_context_factory() if conclusions else None
    overall = fallback_overall
    report_fallback = True
    if context is not None:
        try:
            selection = await _invoke_structured(
                prompt=(
                    "基于受支持的分任务结论生成简洁总判断。只能使用输入内容；"
                    "supporting_task_ids 必须来自输入。存在未解决冲突时必须明确无法形成统一判断。\n"
                    + json.dumps({
                        "task_results": [item.model_dump(mode="json") for item in task_results],
                        "conflicts": [item.model_dump(mode="json") for item in claim_validation.conflicts],
                    }, ensure_ascii=False, sort_keys=True)
                ),
                context=context, schema=_ReportSynthesisSelection, stage="report_synthesis",
            )
            assert isinstance(selection, _ReportSynthesisSelection)
            supported = {
                item.task_id for item in task_results if item.conclusion and item.claim_ids
            }
            if any(item not in supported for item in selection.supporting_task_ids):
                raise ValueError("report_synthesis_unknown_task_id")
            has_material_conflict = any(
                item.material and not item.resolved for item in claim_validation.conflicts
            )
            if has_material_conflict and len(task_results) > 1:
                overall = fallback_overall
                report_fallback = True
            else:
                overall = selection.overall_conclusion
                report_fallback = False
        except Exception:
            overall = fallback_overall
            report_fallback = True
    citation_ids = stable_unique([
        evidence_id
        for result in task_results
        for claim_id in result.claim_ids
        if (claim := claim_validation.valid_claims.get(claim_id)) is not None
        for evidence_id in claim.evidence_ids
    ])
    return ReportSynthesisDraft(
        schema_version=SCHEMA_VERSION,
        status=aggregate_task_status([item.status for item in task_results]),
        overall_conclusion=overall, task_results=task_results,
        claim_index=claim_validation.valid_claims,
        evidence_index=evidence_normalization.evidence_index,
        citation_ids=citation_ids, conflicts=claim_validation.conflicts,
        disagreements=stable_unique([value for item in task_results for value in item.disagreements]),
        risks=stable_unique([value for item in task_results for value in item.risks]),
        limitations=stable_unique([value for item in task_results for value in item.limitations]),
        fallback_used=report_fallback,
    )


def evaluate_synthesis_quality(
    *,
    draft: ReportSynthesisDraft,
    requested_task_ids: list[NonEmptyStr],
    evidence_index: dict[NonEmptyStr, NormalizedEvidence],
    rendered_task_ids: list[NonEmptyStr] | None = None,
    structural_block_reasons: list[NonEmptyStr] | None = None,
) -> SynthesisQualityGateResult:
    block = list(structural_block_reasons or [])
    result_ids = [item.task_id for item in draft.task_results]
    if len(requested_task_ids) != len(set(requested_task_ids)) or len(result_ids) != len(set(result_ids)):
        block.append("duplicate_task")
    if requested_task_ids != result_ids:
        block.append("missing_task")
    orders = [item.order_index for item in draft.task_results]
    if len(orders) != len(set(orders)):
        block.append("duplicate_order_index")
    if any(key != value.claim_id for key, value in draft.claim_index.items()):
        block.append("claim_index_key_mismatch")
    if any(key != value.source_id for key, value in draft.evidence_index.items()):
        block.append("evidence_index_key_mismatch")
    if evidence_index != draft.evidence_index:
        block.append("evidence_index_mismatch")
    expected_citations: list[str] = []
    for result in draft.task_results:
        for claim_id in result.claim_ids:
            claim = draft.claim_index.get(claim_id)
            if claim is None:
                block.append("invalid_claim_reference")
                continue
            for source_id in claim.evidence_ids:
                evidence = draft.evidence_index.get(source_id)
                if evidence is None:
                    block.append("invalid_claim_reference")
                elif claim.task_id not in evidence.task_ids:
                    block.append("cross_task_claim_reference")
                elif source_id not in expected_citations:
                    expected_citations.append(source_id)
    if draft.citation_ids != expected_citations:
        block.append("citation_set_mismatch")
    if rendered_task_ids is not None and rendered_task_ids != result_ids:
        block.append("renderer_task_coverage_mismatch")
    block = stable_unique(block)
    if block:
        return SynthesisQualityGateResult(state="block", reasons=block)
    degraded: list[str] = []
    if any(item.status != "answered" for item in draft.task_results):
        degraded.append("task_not_answered")
    if draft.fallback_used or any(item.fallback_used for item in draft.task_results):
        degraded.append("fallback_used")
    if any(item.material and not item.resolved for item in draft.conflicts):
        degraded.append("unresolved_material_conflict")
    if not draft.overall_conclusion:
        degraded.append("missing_overall_conclusion")
    if not any(item.conclusion and item.claim_ids for item in draft.task_results):
        degraded.append("missing_supported_task_conclusion")
    return SynthesisQualityGateResult(state="degraded" if degraded else "pass", reasons=degraded)


def finalize_report_synthesis(
    *, draft: ReportSynthesisDraft, final_gate: SynthesisQualityGateResult,
) -> ReportSynthesisResult:
    return ReportSynthesisResult(**draft.model_dump(), degraded=final_gate.state != "pass")


__all__ = [
    "build_agent_findings", "evaluate_synthesis_quality", "finalize_report_synthesis",
    "normalize_evidence", "synthesize_report_draft", "synthesize_task_results",
    "validate_claims",
]

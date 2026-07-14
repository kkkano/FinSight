# -*- coding: utf-8 -*-
"""请求任务描述与执行结果的双阶段事实源。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from backend.graph.intent_contract import EvidenceKind
from backend.graph.synthesis.contracts import (
    ClaimValidationResult,
    EvidenceNormalizationResult,
    NonEmptyStr,
    StrictContract,
    TaskStatus,
    stable_unique,
)

_EVIDENCE_KINDS = set(EvidenceKind.__args__)

_DETERMINISTIC_TOOL_OPERATIONS = {
    "compare",
    "earnings_impact",
    "earnings_performance",
    "fetch",
    "holdings",
    "macro_brief",
    "news_impact",
    "portfolio",
    "price",
    "technical",
    "valuation_sanity",
}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _strings(value: Any) -> list[str]:
    if not isinstance(value, list):
        value = [value] if value is not None else []
    return stable_unique([_text(item) for item in value if _text(item)])


def _operation(raw: dict[str, Any]) -> str:
    value = raw.get("operation")
    if isinstance(value, dict):
        value = value.get("name")
    return _text(value) or "qa"


class TaskDescriptor(StrictContract):
    task_id: NonEmptyStr
    title: NonEmptyStr
    priority: int = Field(ge=0)
    order_index: int = Field(ge=0)
    operation: NonEmptyStr
    subject_label: NonEmptyStr
    tickers: list[NonEmptyStr]
    request_frame_id: NonEmptyStr
    render_kind: Literal["single", "compare"]
    render_group_id: NonEmptyStr
    intent_status: Literal["ready", "blocked"]
    required_step_ids: list[NonEmptyStr]
    required_evidence: list[EvidenceKind]
    error_codes: list[NonEmptyStr]


class TaskDescriptorBuildResult(StrictContract):
    descriptors: list[TaskDescriptor]
    requested_task_count: int = Field(ge=0)
    requested_task_ids: list[NonEmptyStr]
    invalid_task_ordinals: list[int]
    invalid_order_ordinals: list[int]
    duplicate_task_ids: list[NonEmptyStr]
    quality_block_reasons: list[NonEmptyStr]


class TaskOutcome(TaskDescriptor):
    status: TaskStatus
    successful_step_ids: list[NonEmptyStr]
    evidence_ids: list[NonEmptyStr]
    missing_evidence: list[NonEmptyStr]


class TaskOutcomeBuildResult(StrictContract):
    outcomes: list[TaskOutcome]
    outcome_task_ids: list[NonEmptyStr]
    missing_task_ids: list[NonEmptyStr]
    duplicate_task_ids: list[NonEmptyStr]
    quality_block_reasons: list[NonEmptyStr]


def _step_task_ids(step: dict[str, Any]) -> list[str]:
    return _strings(step.get("task_ids")) + [
        item for item in _strings(step.get("task_id")) if item not in _strings(step.get("task_ids"))
    ]


def _required_evidence(raw: dict[str, Any]) -> list[EvidenceKind]:
    values = _strings(raw.get("required_evidence"))
    return [item for item in values if item in _EVIDENCE_KINDS]  # type: ignore[misc]


def build_task_descriptors(
    *,
    understanding_tasks: list[dict[str, Any]],
    blocked_tasks: list[dict[str, Any]],
    plan_tasks: list[dict[str, Any]],
    plan_steps: list[dict[str, Any]],
) -> TaskDescriptorBuildResult:
    raw_items = [(item, "ready", ordinal) for ordinal, item in enumerate(understanding_tasks)]
    offset = len(raw_items)
    raw_items.extend((item, "blocked", offset + ordinal) for ordinal, item in enumerate(blocked_tasks))
    requested_task_count = len(raw_items)

    requested_task_ids: list[str] = []
    invalid_task_ordinals: list[int] = []
    invalid_order_ordinals: list[int] = []
    quality: list[str] = []
    sortable: list[tuple[int, int, dict[str, Any], str, bool]] = []
    order_counts: dict[int, int] = {}
    for raw, intent_status, ordinal in raw_items:
        task_id = _text(raw.get("id") or raw.get("task_id"))
        if task_id:
            requested_task_ids.append(task_id)
        else:
            invalid_task_ordinals.append(ordinal)
            quality.append("invalid_task_identity")
        order = raw.get("order_index")
        valid_order = isinstance(order, int) and not isinstance(order, bool) and order >= 0
        if valid_order:
            order_counts[order] = order_counts.get(order, 0) + 1
            sort_order = order
        else:
            invalid_order_ordinals.append(ordinal)
            quality.append("invalid_order_index")
            sort_order = 2**31 - 1
        sortable.append((sort_order, ordinal, raw, intent_status, valid_order))
    if any(count > 1 for count in order_counts.values()):
        quality.append("duplicate_order_index")

    seen_ids: set[str] = set()
    duplicate_task_ids: list[str] = []
    for task_id in requested_task_ids:
        if task_id in seen_ids:
            duplicate_task_ids.append(task_id)
            quality.append("duplicate_task")
        seen_ids.add(task_id)

    plan_by_id: dict[str, list[dict[str, Any]]] = {}
    for task in plan_tasks:
        plan_by_id.setdefault(_text(task.get("id") or task.get("task_id")), []).append(task)

    descriptors: list[TaskDescriptor] = []
    for _, ordinal, raw, intent_status, valid_order in sorted(sortable, key=lambda item: (item[0], item[1])):
        task_id = _text(raw.get("id") or raw.get("task_id"))
        if not task_id or not valid_order:
            continue
        plan_matches = plan_by_id.get(task_id, []) if intent_status == "ready" else []
        if intent_status == "ready" and len(plan_matches) != 1:
            quality.append("missing_task" if not plan_matches else "duplicate_task")
        plan_task = plan_matches[0] if len(plan_matches) == 1 else {}
        required_steps = [
            _text(step.get("id")) for step in plan_steps
            if _text(step.get("id")) and task_id in _step_task_ids(step) and not bool(step.get("optional"))
        ] if intent_status == "ready" else []
        required = _required_evidence(raw)
        required.extend(item for item in _required_evidence(plan_task) if item not in required)
        for step in plan_steps:
            if task_id not in _step_task_ids(step):
                continue
            inputs = step.get("inputs") if isinstance(step.get("inputs"), dict) else {}
            for item in _required_evidence(inputs):
                if item not in required:
                    required.append(item)
        subject_label = _text(raw.get("subject_label")) or _text(raw.get("subject_type")) or "未指定分析对象"
        title = _text(raw.get("title")) or subject_label
        frame_id = _text(raw.get("request_frame_id") or raw.get("frame_id"))
        render_kind = _text(raw.get("render_kind"))
        group_id = _text(raw.get("render_group_id"))
        if not frame_id or render_kind not in {"single", "compare"} or not group_id:
            quality.append("legacy_task_binding_degraded")
            frame_id = frame_id or f"legacy-frame-{ordinal}"
            render_kind = render_kind if render_kind in {"single", "compare"} else "single"
            group_id = group_id or frame_id
        errors = _strings(raw.get("error_codes"))
        if intent_status == "blocked" and not errors:
            errors = [_text(raw.get("error_code")) or _text(raw.get("reason")) or "task_blocked"]
        descriptors.append(TaskDescriptor(
            task_id=task_id,
            title=title,
            priority=max(0, int(raw.get("priority"))) if isinstance(raw.get("priority"), int) else 50,
            order_index=int(raw["order_index"]),
            operation=_operation(raw),
            subject_label=subject_label,
            tickers=_strings(raw.get("tickers")),
            request_frame_id=frame_id,
            render_kind=render_kind,  # type: ignore[arg-type]
            render_group_id=group_id,
            intent_status=intent_status,  # type: ignore[arg-type]
            required_step_ids=required_steps,
            required_evidence=required,
            error_codes=errors,
        ))

    return TaskDescriptorBuildResult(
        descriptors=descriptors,
        requested_task_count=requested_task_count,
        requested_task_ids=requested_task_ids,
        invalid_task_ordinals=invalid_task_ordinals,
        invalid_order_ordinals=invalid_order_ordinals,
        duplicate_task_ids=duplicate_task_ids,
        quality_block_reasons=quality,
    )


def _step_succeeded(result: Any) -> bool:
    if result is None:
        return False
    if isinstance(result, dict):
        if _text(result.get("status")).lower() in {"error", "failed", "timeout", "empty", "unavailable"}:
            return False
        value = result.get("output", result.get("result", result.get("data")))
        return value not in (None, "", [], {})
    return result not in ("", [], {})


def finalize_task_outcomes(
    *,
    descriptors: list[TaskDescriptor],
    plan_steps: list[dict[str, Any]],
    task_results: dict[str, Any],
    evidence_normalization: EvidenceNormalizationResult,
    claim_validation: ClaimValidationResult,
) -> TaskOutcomeBuildResult:
    del plan_steps
    outcomes: list[TaskOutcome] = []
    for descriptor in descriptors:
        evidence = evidence_normalization.evidence_by_task.get(descriptor.task_id, [])
        evidence_ids = [item.source_id for item in evidence]
        covered = stable_unique([
            kind for item in evidence for kind in [item.kind] if kind != "unknown"
        ])
        missing = [item for item in descriptor.required_evidence if item not in covered]
        successful = [
            step_id for step_id in descriptor.required_step_ids
            if _step_succeeded(task_results.get(step_id))
        ]
        claims = [claim for claim in claim_validation.valid_claims.values() if claim.task_id == descriptor.task_id]
        error_codes = list(descriptor.error_codes)
        if missing:
            error_codes.append("missing_required_evidence")
        missing_steps = [
            step_id for step_id in descriptor.required_step_ids
            if step_id not in successful
        ]
        if missing_steps:
            error_codes.append("required_step_unavailable")
        has_supported_conclusion = bool(claims) or (
            descriptor.operation in _DETERMINISTIC_TOOL_OPERATIONS
            and bool(successful)
            and bool(evidence)
        )
        if descriptor.intent_status == "blocked":
            status: TaskStatus = "blocked"
        elif not successful:
            status = "unavailable"
            error_codes.append("no_successful_result")
        elif (
            has_supported_conclusion
            and not missing
            and not missing_steps
            and "legacy_task_binding_degraded" not in error_codes
        ):
            status = "answered"
        elif successful or evidence:
            status = "partial"
        else:
            status = "unavailable"
            error_codes.append("no_supported_result")
        payload = descriptor.model_dump()
        payload["error_codes"] = stable_unique(error_codes)
        outcomes.append(TaskOutcome(
            **payload,
            status=status,
            successful_step_ids=successful,
            evidence_ids=evidence_ids,
            missing_evidence=missing,
        ))

    ids = [item.task_id for item in outcomes]
    duplicate_ids = stable_unique([item for index, item in enumerate(ids) if item in ids[:index]])
    requested = [item.task_id for item in descriptors]
    missing_ids = [item for item in requested if item not in ids]
    quality: list[str] = []
    if missing_ids:
        quality.append("missing_task")
    if duplicate_ids:
        quality.append("duplicate_task")
    return TaskOutcomeBuildResult(
        outcomes=outcomes,
        outcome_task_ids=ids,
        missing_task_ids=missing_ids,
        duplicate_task_ids=duplicate_ids,
        quality_block_reasons=quality,
    )


__all__ = [
    "TaskDescriptor", "TaskDescriptorBuildResult", "TaskOutcome",
    "TaskOutcomeBuildResult", "build_task_descriptors", "finalize_task_outcomes",
]

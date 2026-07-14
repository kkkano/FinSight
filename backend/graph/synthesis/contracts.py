# -*- coding: utf-8 -*-
"""研究合成公共合同。

该模块只定义结构、不读取 GraphState，也不包含 renderer 行为。
"""
from __future__ import annotations

import json
from typing import Annotated, Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

from backend.graph.intent_contract import EvidenceKind

SCHEMA_VERSION = "2026-07-14.research-synthesis.v1"

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
TaskStatus: TypeAlias = Literal["answered", "partial", "unavailable", "blocked"]
EvidenceDimension: TypeAlias = Literal[
    "market", "technical", "fundamental", "valuation", "earnings",
    "catalyst", "risk", "macro", "news", "unknown",
]


def stable_unique(values: list[Any]) -> list[Any]:
    """按首次出现顺序去重，兼容 Pydantic model 与嵌套对象。"""
    result: list[Any] = []
    seen: set[str] = set()
    for value in values:
        raw = value.model_dump(mode="json") if isinstance(value, BaseModel) else value
        try:
            key = json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError):
            key = repr(raw)
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def aggregate_task_status(statuses: list[TaskStatus]) -> TaskStatus:
    if not statuses:
        return "unavailable"
    rank = {"answered": 0, "partial": 1, "unavailable": 2, "blocked": 3}
    return max(statuses, key=lambda item: rank[item])


class StrictContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    @model_validator(mode="before")
    @classmethod
    def _reject_blank_dict_keys(cls, value: Any) -> Any:
        if isinstance(value, dict):
            for key in value:
                if isinstance(key, str) and not key.strip():
                    raise ValueError("字典 key 不得为空")
        return value

class NormalizedEvidence(StrictContract):
    source_id: NonEmptyStr
    task_ids: list[NonEmptyStr] = Field(min_length=1)
    agent_name: NonEmptyStr | None = None
    kind: EvidenceKind | Literal["unknown"] = "unknown"
    text: NonEmptyStr
    title: NonEmptyStr | None = None
    source_name: NonEmptyStr | None = None
    url: NonEmptyStr | None = None
    as_of: NonEmptyStr | None = None
    market_price: float | None = Field(default=None, gt=0)


class RejectedEvidence(StrictContract):
    ordinal: int = Field(ge=0)
    source_id: NonEmptyStr | None = None
    task_ids: list[NonEmptyStr]
    agent_name: NonEmptyStr | None = None
    reason_code: Literal[
        "missing_source_id", "missing_task_binding", "empty_evidence_content",
        "evidence_id_content_conflict",
    ]


class EvidenceNormalizationResult(StrictContract):
    evidence_by_task: dict[NonEmptyStr, list[NormalizedEvidence]]
    evidence_index: dict[NonEmptyStr, NormalizedEvidence]
    rejected_evidence: list[RejectedEvidence]
    quality_block_reasons: list[NonEmptyStr]

    @model_validator(mode="after")
    def _validate_identity(self) -> "EvidenceNormalizationResult":
        for source_id, evidence in self.evidence_index.items():
            if source_id != evidence.source_id:
                raise ValueError("evidence_index key 与 source_id 不一致")
        for task_id, evidence_items in self.evidence_by_task.items():
            if any(task_id not in item.task_ids for item in evidence_items):
                raise ValueError("evidence_by_task 存在跨任务证据")
        return self


class Claim(StrictContract):
    claim_id: NonEmptyStr
    task_id: NonEmptyStr
    agent_name: NonEmptyStr
    text: NonEmptyStr
    stance: Literal["bull", "bear", "neutral", "risk", "unknown"]
    dimension: EvidenceDimension
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_ids: list[NonEmptyStr] = Field(min_length=1)
    limitations: list[NonEmptyStr]


class ClaimConflict(StrictContract):
    conflict_id: NonEmptyStr
    task_id: NonEmptyStr
    claim_ids: list[NonEmptyStr] = Field(min_length=2, max_length=2)
    material: bool
    resolved: Literal[False] = False
    affects_direction: bool

    @model_validator(mode="after")
    def _validate_pair(self) -> "ClaimConflict":
        if len(self.claim_ids) != 2 or self.claim_ids != sorted(self.claim_ids):
            raise ValueError("claim_ids 必须是两个不同且按字典序排列的 ID")
        return self


class RejectedClaim(StrictContract):
    ordinal: int = Field(ge=0)
    claim_id: NonEmptyStr | None = None
    task_id: NonEmptyStr | None = None
    agent_name: NonEmptyStr | None = None
    reason_code: Literal[
        "empty_claim_text", "invalid_claim_stance", "invalid_confidence",
        "missing_claim_identity", "missing_evidence_reference",
        "invalid_claim_reference", "cross_task_claim_reference",
        "claim_id_content_conflict",
    ]


class ClaimValidationResult(StrictContract):
    valid_claims: dict[NonEmptyStr, Claim]
    rejected_claims: list[RejectedClaim]
    conflicts: list[ClaimConflict]
    quality_block_reasons: list[NonEmptyStr]

    @model_validator(mode="after")
    def _validate_identity(self) -> "ClaimValidationResult":
        if any(key != value.claim_id for key, value in self.valid_claims.items()):
            raise ValueError("valid_claims key 与 claim_id 不一致")
        return self


class AgentFinding(StrictContract):
    task_id: NonEmptyStr
    agent_name: NonEmptyStr
    status: TaskStatus
    conclusion: NonEmptyStr | None = None
    claim_ids: list[NonEmptyStr]
    evidence_ids: list[NonEmptyStr]
    risks: list[NonEmptyStr]
    limitations: list[NonEmptyStr]
    fallback_used: bool
    error_codes: list[NonEmptyStr]


class TaskSynthesisResult(StrictContract):
    task_id: NonEmptyStr
    title: NonEmptyStr
    priority: int = Field(ge=0)
    order_index: int = Field(ge=0)
    request_frame_id: NonEmptyStr
    render_kind: Literal["single", "compare"]
    render_group_id: NonEmptyStr
    status: TaskStatus
    conclusion: NonEmptyStr | None = None
    claim_ids: list[NonEmptyStr]
    evidence_ids: list[NonEmptyStr]
    proposed_direction: Literal["bull", "bear", "neutral"] | None = None
    direction_supporting_claim_ids: list[NonEmptyStr]
    agent_names: list[NonEmptyStr]
    agreements: list[NonEmptyStr]
    disagreements: list[NonEmptyStr]
    conflicts: list[ClaimConflict]
    risks: list[NonEmptyStr]
    limitations: list[NonEmptyStr]
    fallback_used: bool
    error_codes: list[NonEmptyStr]

    @model_validator(mode="after")
    def _validate_direction_refs(self) -> "TaskSynthesisResult":
        if self.proposed_direction is None and self.direction_supporting_claim_ids:
            raise ValueError("无方向提案时不得存在 supporting claim")
        claim_ids = set(self.claim_ids)
        if any(item not in claim_ids for item in self.direction_supporting_claim_ids):
            raise ValueError("方向 supporting claim 必须是 task claim 子集")
        return self


class ReportSynthesisDraft(StrictContract):
    schema_version: Literal["2026-07-14.research-synthesis.v1"] = SCHEMA_VERSION
    status: TaskStatus
    overall_conclusion: NonEmptyStr | None = None
    task_results: list[TaskSynthesisResult] = Field(min_length=1)
    claim_index: dict[NonEmptyStr, Claim]
    evidence_index: dict[NonEmptyStr, NormalizedEvidence]
    citation_ids: list[NonEmptyStr]
    conflicts: list[ClaimConflict]
    disagreements: list[NonEmptyStr]
    risks: list[NonEmptyStr]
    limitations: list[NonEmptyStr]
    fallback_used: bool

    @model_validator(mode="after")
    def _validate_indexes_and_direction(self) -> "ReportSynthesisDraft":
        if any(key != value.claim_id for key, value in self.claim_index.items()):
            raise ValueError("claim_index key 与 claim_id 不一致")
        if any(key != value.source_id for key, value in self.evidence_index.items()):
            raise ValueError("evidence_index key 与 source_id 不一致")
        for result in self.task_results:
            for claim_id in result.direction_supporting_claim_ids:
                claim = self.claim_index.get(claim_id)
                if claim is None or claim.task_id != result.task_id or claim.stance != result.proposed_direction:
                    raise ValueError("方向 supporting claim 与提案不一致")
        return self


class ReportSynthesisResult(ReportSynthesisDraft):
    degraded: bool


class ResearchReportRenderResult(StrictContract):
    markdown: NonEmptyStr
    rendered_task_ids: list[NonEmptyStr] = Field(min_length=1)


class SynthesisQualityGateResult(StrictContract):
    state: Literal["pass", "degraded", "block"]
    reasons: list[NonEmptyStr]


__all__ = [
    "SCHEMA_VERSION", "AgentFinding", "Claim", "ClaimConflict",
    "ClaimValidationResult", "EvidenceDimension", "EvidenceNormalizationResult",
    "NonEmptyStr", "NormalizedEvidence", "RejectedClaim", "RejectedEvidence",
    "ReportSynthesisDraft", "ReportSynthesisResult", "ResearchReportRenderResult",
    "StrictContract", "SynthesisQualityGateResult", "TaskStatus",
    "TaskSynthesisResult", "aggregate_task_status", "stable_unique",
]

"""compiler 唯一产出的版本化请求合同；未知要求保留原文，不参与任意字段取值。"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from backend.graph.semantic_requirements import (
    FactAttribute, RequirementQualifier, SemanticConstraint, SemanticRequirement,
    SemanticSubject, SemanticTimeScope,
)
from backend.graph.research_capabilities import CAPABILITIES

CanonicalMetric = Literal[tuple(sorted(CAPABILITIES)) + ("unknown", "comparison")]


class SourceSpan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    start: int = Field(ge=0)
    end: int = Field(ge=0)


class CompiledTimeScope(SemanticTimeScope):
    reporting_basis: Literal["consolidated", "parent", "unspecified"] | None = None


class CompiledSubject(SemanticSubject):
    raw_type: str | None = None


class UnmappedQualifier(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str
    source_text: str
    value: str | None = None
    description: str = ""


class InputDependencySpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    input_key: str
    source_text: str
    source_ref: str | None = None
    available: bool


class RequirementSpec(SemanticRequirement):
    model_config = ConfigDict(extra="forbid", frozen=True)
    requirement_id: str
    metric: CanonicalMetric = "unknown"
    source_span: SourceSpan | None = None
    attributes: list[FactAttribute] = Field(default_factory=list)
    qualifiers: list[RequirementQualifier] = Field(default_factory=list)
    time_scope: CompiledTimeScope = Field(default_factory=CompiledTimeScope)
    capability_reason: str | None = None
    unsupported_reason: str | None = None
    unmapped_qualifiers: list[UnmappedQualifier] = Field(default_factory=list)
    unmapped_evidence_kinds: list[str] = Field(default_factory=list)
    input_dependency_specs: list[InputDependencySpec] = Field(default_factory=list)
    attribute_owner_requirement_id: str | None = None
    comparison_requirement_ids: list[str] = Field(default_factory=list)
    comparison_inputs: list[RequirementSpec] = Field(default_factory=list)
    constraint_type: str | None = None
    source_requirement: str | None = None
    raw_metric: str | None = None
    raw_dimension: str | None = None
    raw_capability_status: str | None = None
    raw_requires_analysis: bool | None = None
    raw_time_scope: dict[str, Any] | None = None


class UnmappedRequirement(RequirementSpec):
    metric: Literal["unknown"] = "unknown"
    capability_status: Literal["unsupported", "input_missing"] = "unsupported"


class RequestTaskSpec(BaseModel):
    # operation 与 selection 为只读旧投影，不参与新的要求映射。
    model_config = ConfigDict(extra="allow", frozen=True)
    id: str
    subject_type: str
    tickers: list[str] = Field(default_factory=list)
    request_text: str
    answer_requirements: list[UnmappedRequirement | RequirementSpec] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    status: Literal["ready", "blocked"] = "ready"


class RequestSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["request_spec.v2"] = "request_spec.v2"
    status: Literal["confirmed", "unconfirmed"]
    route: Literal["research", "direct", "clarify"]
    query: str
    subjects: list[CompiledSubject] = Field(default_factory=list)
    output_mode: str
    relation: Literal["single", "compare", "rank", "impact", "continuation", "none"] = "single"
    requirements: list[UnmappedRequirement | RequirementSpec] = Field(default_factory=list)
    constraints: list[SemanticConstraint] = Field(default_factory=list)
    tasks: list[RequestTaskSpec] = Field(default_factory=list)

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

METRIC_KEYS_V2 = [
    "keypoint_coverage",
    "keypoint_context_recall",
    "claim_support_rate",
    "unsupported_claim_rate",
    "contradiction_rate",
    "numeric_consistency_rate",
]


@dataclass
class CaseResultV2:
    case_id: str
    doc_type: str
    question_type: str
    answer_len: int
    metrics: dict[str, float | None]
    metric_errors: dict[str, str] = field(default_factory=dict)
    error: str | None = None
    judge_artifacts: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GateResultV2:
    passed: bool
    failures: list[str]
    applied_thresholds: dict[str, dict[str, float]] = field(default_factory=dict)
    null_rate_failures: list[str] = field(default_factory=list)
    policy_name: str = "rag_quality_v2_gate"
    policy_version: str = "v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DriftResultV2:
    enabled: bool
    baseline_available: bool
    passed: bool
    deltas: dict[str, float]
    failures: list[str]
    baseline_run_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvalReportV2:
    run_id: str
    generated_at: str
    layer: str
    dataset_version: str
    config: dict[str, Any]
    overall_metrics: dict[str, float | None]
    by_doc_type: dict[str, dict[str, float | None]]
    by_question_type: dict[str, dict[str, float | None]]
    metric_null_rates: dict[str, float]
    gate_result: dict[str, Any]
    drift_result: dict[str, Any]
    case_results: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


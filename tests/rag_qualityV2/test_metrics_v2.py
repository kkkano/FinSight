from __future__ import annotations

from rag_qualityV2.engine_v2 import compute_metrics_from_counters


def test_metrics_formula_happy_path() -> None:
    counters = {
        "total_claims": 10,
        "supported_claims": 7,
        "unsupported_claims": 2,
        "contradicted_claims": 1,
        "total_numeric_claims": 4,
        "supported_numeric_claims": 3,
        "total_keypoints": 8,
        "covered_keypoints": 5,
        "partial_keypoints": 2,
        "keypoints_supported_by_context": 6,
    }
    m = compute_metrics_from_counters(counters)
    assert m["claim_support_rate"] == 0.7
    assert m["unsupported_claim_rate"] == 0.2
    assert m["contradiction_rate"] == 0.1
    assert m["numeric_consistency_rate"] == 0.75
    assert m["keypoint_coverage"] == 0.75
    assert m["keypoint_context_recall"] == 0.75


def test_numeric_consistency_none_when_no_numeric_claims() -> None:
    counters = {
        "total_claims": 5,
        "supported_claims": 4,
        "unsupported_claims": 1,
        "contradicted_claims": 0,
        "total_numeric_claims": 0,
        "supported_numeric_claims": 0,
        "total_keypoints": 3,
        "covered_keypoints": 2,
        "partial_keypoints": 0,
        "keypoints_supported_by_context": 2,
    }
    m = compute_metrics_from_counters(counters)
    assert m["numeric_consistency_rate"] is None


def test_empty_denominator_returns_none() -> None:
    counters = {
        "total_claims": 0,
        "supported_claims": 0,
        "unsupported_claims": 0,
        "contradicted_claims": 0,
        "total_numeric_claims": 0,
        "supported_numeric_claims": 0,
        "total_keypoints": 0,
        "covered_keypoints": 0,
        "partial_keypoints": 0,
        "keypoints_supported_by_context": 0,
    }
    m = compute_metrics_from_counters(counters)
    assert all(v is None for v in m.values())

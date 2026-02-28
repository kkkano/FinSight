from __future__ import annotations

from copy import deepcopy

from rag_qualityV2.engine_v2 import check_drift_v2, check_gates_v2
from rag_qualityV2.types_v2 import EvalReportV2, GateResultV2


def _build_report(
    *,
    overall: dict[str, float | None],
    by_doc: dict[str, dict[str, float | None]] | None = None,
    by_qt: dict[str, dict[str, float | None]] | None = None,
    null_rates: dict[str, float] | None = None,
) -> EvalReportV2:
    return EvalReportV2(
        run_id="r1",
        generated_at="2026-03-01T00:00:00+00:00",
        layer="layer1_v2",
        dataset_version="v1",
        config={},
        overall_metrics=overall,
        by_doc_type=by_doc or {},
        by_question_type=by_qt or {},
        metric_null_rates=null_rates or {},
        gate_result=GateResultV2(passed=True, failures=[]).to_dict(),
        drift_result={},
        case_results=[],
    )


def test_gate_passes_with_good_metrics(thresholds: dict) -> None:
    overall = {
        "keypoint_coverage": 0.85,
        "keypoint_context_recall": 0.9,
        "claim_support_rate": 0.88,
        "unsupported_claim_rate": 0.05,
        "contradiction_rate": 0.01,
        "numeric_consistency_rate": 0.95,
    }
    report = _build_report(overall=overall, null_rates={k: 0.0 for k in overall})
    gate = check_gates_v2(report, thresholds)
    assert gate.passed
    assert gate.failures == []


def test_gate_fails_on_max_metric(thresholds: dict) -> None:
    overall = {
        "keypoint_coverage": 0.85,
        "keypoint_context_recall": 0.9,
        "claim_support_rate": 0.88,
        "unsupported_claim_rate": 0.3,
        "contradiction_rate": 0.01,
        "numeric_consistency_rate": 0.95,
    }
    report = _build_report(overall=overall, null_rates={k: 0.0 for k in overall})
    gate = check_gates_v2(report, thresholds)
    assert not gate.passed
    assert any("unsupported_claim_rate" in f for f in gate.failures)


def test_gate_merge_prefers_stricter_min_max(thresholds: dict) -> None:
    cfg = deepcopy(thresholds)
    cfg["question_type_overrides"]["factoid"]["unsupported_claim_rate"] = {"max": 0.08}
    overall = {
        "keypoint_coverage": 0.9,
        "keypoint_context_recall": 0.9,
        "claim_support_rate": 0.9,
        "unsupported_claim_rate": 0.09,
        "contradiction_rate": 0.01,
        "numeric_consistency_rate": 0.98,
    }
    report = _build_report(
        overall=overall,
        by_doc={"filing": overall},
        by_qt={"factoid": overall},
        null_rates={k: 0.0 for k in overall},
    )
    gate = check_gates_v2(report, cfg)
    assert not gate.passed
    assert any("qt:factoid.unsupported_claim_rate" in f for f in gate.failures)


def test_null_rate_hard_fail(thresholds: dict) -> None:
    overall = {
        "keypoint_coverage": 0.85,
        "keypoint_context_recall": 0.9,
        "claim_support_rate": 0.88,
        "unsupported_claim_rate": 0.05,
        "contradiction_rate": 0.01,
        "numeric_consistency_rate": 0.95,
    }
    report = _build_report(
        overall=overall,
        null_rates={**{k: 0.0 for k in overall}, "claim_support_rate": 1.0},
    )
    gate = check_gates_v2(report, thresholds)
    assert not gate.passed
    assert any("null_rate=100%" in f for f in gate.failures)


def test_drift_bi_direction(thresholds: dict) -> None:
    baseline = {
        "run_id": "baseline-1",
        "overall_metrics": {
            "keypoint_coverage": 0.8,
            "keypoint_context_recall": 0.8,
            "claim_support_rate": 0.8,
            "unsupported_claim_rate": 0.1,
            "contradiction_rate": 0.02,
            "numeric_consistency_rate": 0.92,
        },
    }
    current = {
        "keypoint_coverage": 0.81,
        "keypoint_context_recall": 0.79,
        "claim_support_rate": 0.79,
        "unsupported_claim_rate": 0.16,
        "contradiction_rate": 0.06,
        "numeric_consistency_rate": 0.91,
    }
    drift = check_drift_v2(current, baseline, thresholds)
    assert not drift.passed
    assert any("unsupported_claim_rate" in f for f in drift.failures)
    assert any("contradiction_rate" in f for f in drift.failures)

# -*- coding: utf-8 -*-
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from run_retrieval_eval import (
    _drift_gate,
    _gate,
    compute_citation_coverage,
    compute_mrr,
    compute_ndcg_at_k,
    compute_precision_at_k,
    compute_recall_at_k,
    write_gate_summary,
)


def test_compute_recall_at_k_basic() -> None:
    recall = compute_recall_at_k(
        expected_ids=["a", "b", "c"],
        retrieved_ids=["x", "a", "b"],
    )
    assert recall == 2 / 3


def test_compute_precision_at_k_basic() -> None:
    precision = compute_precision_at_k(
        gold_ids=["a", "b"],
        retrieved_ids=["a", "x", "b", "y", "z"],
        k=5,
    )
    assert precision == 2 / 5


def test_compute_precision_at_k_top_3() -> None:
    precision = compute_precision_at_k(
        gold_ids=["a", "b"],
        retrieved_ids=["a", "b", "x", "y", "z"],
        k=3,
    )
    assert precision == 2 / 3


def test_compute_precision_at_k_no_hits() -> None:
    precision = compute_precision_at_k(
        gold_ids=["a", "b"],
        retrieved_ids=["x", "y", "z"],
        k=3,
    )
    assert precision == 0.0


def test_compute_precision_at_k_empty_gold() -> None:
    precision = compute_precision_at_k(
        gold_ids=[],
        retrieved_ids=["x", "y"],
        k=2,
    )
    assert precision == 1.0


def test_compute_mrr_first_position() -> None:
    mrr = compute_mrr(
        gold_ids=["a", "b"],
        retrieved_ids=["a", "x", "b"],
    )
    assert mrr == 1.0


def test_compute_mrr_second_position() -> None:
    mrr = compute_mrr(
        gold_ids=["a"],
        retrieved_ids=["x", "a", "y"],
    )
    assert mrr == 0.5


def test_compute_mrr_not_found() -> None:
    mrr = compute_mrr(
        gold_ids=["a"],
        retrieved_ids=["x", "y", "z"],
    )
    assert mrr == 0.0


def test_compute_mrr_empty_gold() -> None:
    mrr = compute_mrr(
        gold_ids=[],
        retrieved_ids=["x", "y"],
    )
    assert mrr == 1.0


def test_compute_ndcg_at_k_perfect_is_one() -> None:
    ndcg = compute_ndcg_at_k(
        retrieved_ids=["doc1", "doc2", "doc3"],
        relevance_map={"doc1": 3, "doc2": 2, "doc3": 1},
        k=3,
    )
    assert abs(ndcg - 1.0) < 1e-9


def test_compute_ndcg_at_k_penalizes_wrong_order() -> None:
    perfect = compute_ndcg_at_k(
        retrieved_ids=["doc1", "doc2", "doc3"],
        relevance_map={"doc1": 3, "doc2": 2, "doc3": 1},
        k=3,
    )
    wrong = compute_ndcg_at_k(
        retrieved_ids=["doc3", "doc2", "doc1"],
        relevance_map={"doc1": 3, "doc2": 2, "doc3": 1},
        k=3,
    )
    assert wrong < perfect


def test_compute_citation_coverage() -> None:
    coverage = compute_citation_coverage(
        gold_citation_ids=["e1", "e2"],
        predicted_citation_ids=["e1", "x"],
    )
    assert coverage == 0.5


def test_gate_fails_when_metric_below_threshold() -> None:
    gate = _gate(
        overall={
            "recall_at_k": 0.7,
            "precision_at_k": 0.3,
            "mrr": 0.9,
            "ndcg_at_k": 0.9,
            "citation_coverage": 0.8,
            "latency_p95_ms": 12.0,
        },
        thresholds={
            "recall_at_k_min": 0.8,
            "precision_at_k_min": 0.25,
            "mrr_min": 0.85,
            "ndcg_at_k_min": 0.85,
            "citation_coverage_min": 0.7,
            "latency_p95_ms_max": 30.0,
        },
    )
    assert gate.passed is False
    assert "recall_at_k" in gate.failed_metrics
    assert "precision_at_k" not in gate.failed_metrics
    assert "mrr" not in gate.failed_metrics


def test_gate_fails_on_precision() -> None:
    gate = _gate(
        overall={
            "recall_at_k": 0.99,
            "precision_at_k": 0.10,
            "mrr": 0.95,
            "ndcg_at_k": 0.99,
            "citation_coverage": 0.99,
            "latency_p95_ms": 1.0,
        },
        thresholds={
            "recall_at_k_min": 0.95,
            "precision_at_k_min": 0.30,
            "mrr_min": 0.85,
            "ndcg_at_k_min": 0.95,
            "citation_coverage_min": 0.95,
            "latency_p95_ms_max": 10.0,
        },
    )
    assert gate.passed is False
    assert "precision_at_k" in gate.failed_metrics


def test_gate_fails_on_mrr() -> None:
    gate = _gate(
        overall={
            "recall_at_k": 0.99,
            "precision_at_k": 0.40,
            "mrr": 0.50,
            "ndcg_at_k": 0.99,
            "citation_coverage": 0.99,
            "latency_p95_ms": 1.0,
        },
        thresholds={
            "recall_at_k_min": 0.95,
            "precision_at_k_min": 0.30,
            "mrr_min": 0.85,
            "ndcg_at_k_min": 0.95,
            "citation_coverage_min": 0.95,
            "latency_p95_ms_max": 10.0,
        },
    )
    assert gate.passed is False
    assert "mrr" in gate.failed_metrics


def test_drift_gate_fails_on_negative_quality_regression() -> None:
    drift = _drift_gate(
        overall={
            "recall_at_k": 0.90,
            "precision_at_k": 0.30,
            "mrr": 0.85,
            "ndcg_at_k": 0.90,
            "citation_coverage": 0.88,
            "latency_p95_ms": 15.0,
        },
        baseline_overall={
            "recall_at_k": 0.95,
            "precision_at_k": 0.40,
            "mrr": 1.0,
            "ndcg_at_k": 0.94,
            "citation_coverage": 0.92,
            "latency_p95_ms": 10.0,
        },
        thresholds={
            "recall_at_k_delta_min": -0.03,
            "precision_at_k_delta_min": -0.05,
            "mrr_delta_min": -0.03,
            "ndcg_at_k_delta_min": -0.03,
            "citation_coverage_delta_min": -0.03,
            "latency_p95_ms_delta_max": 4.0,
        },
    )
    assert drift.passed is False
    assert "recall_at_k_delta" in drift.failed_metrics
    assert "mrr_delta" in drift.failed_metrics
    assert "latency_p95_ms_delta" in drift.failed_metrics
    # precision dropped 0.10 which exceeds -0.05
    assert "precision_at_k_delta" in drift.failed_metrics


def test_drift_gate_passes_within_tolerance() -> None:
    drift = _drift_gate(
        overall={
            "recall_at_k": 0.98,
            "precision_at_k": 0.38,
            "mrr": 0.98,
            "ndcg_at_k": 0.975,
            "citation_coverage": 0.975,
            "latency_p95_ms": 3.0,
        },
        baseline_overall={
            "recall_at_k": 1.0,
            "precision_at_k": 0.40,
            "mrr": 1.0,
            "ndcg_at_k": 1.0,
            "citation_coverage": 1.0,
            "latency_p95_ms": 0.08,
        },
        thresholds={
            "recall_at_k_delta_min": -0.03,
            "precision_at_k_delta_min": -0.05,
            "mrr_delta_min": -0.03,
            "ndcg_at_k_delta_min": -0.03,
            "citation_coverage_delta_min": -0.03,
            "latency_p95_ms_delta_max": 5.0,
        },
    )
    assert drift.passed is True
    assert drift.failed_metrics == []


def test_write_gate_summary_creates_file(tmp_path: Path) -> None:
    payload = {
        "run_id": "retrieval-test-run",
        "generated_at": "2026-02-08T12:00:00Z",
        "backend": "memory",
        "backend_requested": "memory",
        "case_count": 2,
        "overall_metrics": {
            "recall_at_k": 1.0,
            "precision_at_k": 0.4,
            "mrr": 1.0,
            "ndcg_at_k": 1.0,
            "citation_coverage": 1.0,
            "latency_p95_ms": 0.5,
        },
    }
    gate = _gate(
        overall=payload["overall_metrics"],
        thresholds={
            "recall_at_k_min": 0.95,
            "precision_at_k_min": 0.30,
            "mrr_min": 0.85,
            "ndcg_at_k_min": 0.95,
            "citation_coverage_min": 0.95,
            "latency_p95_ms_max": 10.0,
        },
    )
    drift_gate = _drift_gate(
        overall=payload["overall_metrics"],
        baseline_overall=payload["overall_metrics"],
        thresholds={
            "recall_at_k_delta_min": -0.03,
            "precision_at_k_delta_min": -0.05,
            "mrr_delta_min": -0.03,
            "ndcg_at_k_delta_min": -0.03,
            "citation_coverage_delta_min": -0.03,
            "latency_p95_ms_delta_max": 5.0,
        },
    )

    json_report = tmp_path / "retrieval-test-run.json"
    md_report = tmp_path / "retrieval-test-run.md"
    json_report.write_text("{}", encoding="utf-8")
    md_report.write_text("# report", encoding="utf-8")

    output = write_gate_summary(
        output_dir=tmp_path,
        payload=payload,
        gate=gate,
        drift_gate=drift_gate,
        json_report_path=json_report,
        markdown_report_path=md_report,
    )

    assert output.exists()
    assert output.name == "gate_summary.json"
    content = output.read_text(encoding="utf-8")
    assert '"run_id": "retrieval-test-run"' in content
    assert '"passed": true' in content

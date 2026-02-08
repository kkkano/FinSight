from __future__ import annotations

from pathlib import Path

from backend.services.release_drills import (
    RollbackThresholds,
    RolloutStageMetrics,
    evaluate_rollout_thresholds,
    run_report_index_rollback_rehearsal,
    simulate_llm_endpoint_failover_drill,
)


def test_evaluate_rollout_thresholds_passes_when_all_metrics_within_limits():
    result = evaluate_rollout_thresholds(
        stages=[
            RolloutStageMetrics(10, 10, 10, 0, 120.0, 80.0),
            RolloutStageMetrics(50, 50, 50, 0, 180.0, 110.0),
            RolloutStageMetrics(100, 100, 100, 1, 220.0, 130.0),
        ],
        citation_coverage=0.98,
        thresholds=RollbackThresholds(max_5xx_ratio=0.02, p95_regression_factor=2.0, min_citation_coverage=0.95),
    )

    assert result["pass"] is True
    assert result["rollback_triggered"] is False
    assert result["rollback_stage_percent"] is None


def test_evaluate_rollout_thresholds_triggers_rollback_on_5xx_and_citation():
    result = evaluate_rollout_thresholds(
        stages=[
            RolloutStageMetrics(10, 10, 10, 0, 100.0, 60.0),
            RolloutStageMetrics(50, 50, 47, 3, 190.0, 120.0),
        ],
        citation_coverage=0.90,
        thresholds=RollbackThresholds(max_5xx_ratio=0.02, p95_regression_factor=2.0, min_citation_coverage=0.95),
    )

    assert result["pass"] is False
    assert result["rollback_triggered"] is True
    assert result["rollback_stage_percent"] == 10

    stage_10 = [s for s in result["stages"] if s["stage_percent"] == 10][0]
    assert stage_10["pass_stage"] is False
    assert any("citation_coverage_below_threshold" in reason for reason in stage_10["rollback_reasons"])

    stage_50 = [s for s in result["stages"] if s["stage_percent"] == 50][0]
    assert stage_50["pass_stage"] is False
    assert any("5xx_ratio_exceeded" in reason for reason in stage_50["rollback_reasons"])
    assert any("citation_coverage_below_threshold" in reason for reason in stage_50["rollback_reasons"])


def test_run_report_index_rollback_rehearsal_restores_snapshot(tmp_path: Path):
    result = run_report_index_rollback_rehearsal(work_dir=tmp_path)

    assert result["pass"] is True
    assert result["verification"]["pass_data_restore"] is True
    assert result["verification"]["pass_schema_rollback"] is True


def test_simulate_llm_endpoint_failover_drill_passes():
    result = simulate_llm_endpoint_failover_drill()

    assert result["pass"] is True
    assert result["pass_failover"] is True
    assert result["pass_recovery"] is True
    assert result["selected_after_primary_failure"] == "backup"

"""预算变化须重新测量双方，不能复用旧预算的试跑或部分阶段。"""
import json
from pathlib import Path

import pytest

from . import run_frozen_comparison as comparison


def isolated(tmp_path, monkeypatch):
    monkeypatch.setattr(comparison, "RESULTS", tmp_path)
    monkeypatch.setattr(comparison, "ROOT", tmp_path)
    monkeypatch.setattr(comparison, "implementation", lambda: {"run_frozen_eval.py": "frozen-driver"})
    monkeypatch.setattr(comparison, "environment", lambda: {})


def test_explicit_budget_is_forwarded_to_both_runtime_commands(tmp_path, monkeypatch):
    isolated(tmp_path, monkeypatch)
    commands = []

    class Process:
        pid = 101

        def __init__(self, command, **_kwargs):
            commands.append(command)
            self.output = Path(command[command.index("--output") + 1])

        def wait(self):
            self.output.write_text(json.dumps({"results": [
                {"structure": {"completed": True}} for _ in comparison.PILOT_CASES
            ]}), encoding="utf-8")
            return 2  # 尚未评分不能宣称质量通过。

    monkeypatch.setattr(comparison.subprocess, "Popen", Process)
    args = comparison.build_parser().parse_args([
        "--phase", "pilot", "--generation", "quality_priority", "--timeout", "300",
        "--latency-policy", "report_only"
    ])
    assert comparison.main(args) == 0
    assert [command[command.index("--timeout") + 1] for command in commands] == ["300.0", "300.0"]
    assert [command[command.index("--latency-policy") + 1] for command in commands] == ["report_only", "report_only"]
    state = json.loads((tmp_path / "apikl_frozen_pilot_execution_quality_priority.json").read_text())
    assert state["timeout_seconds"] == 300
    assert state["latency_policy"] == "report_only"
    assert state["status"] == "collected_requires_quality_review"


def test_full_measurement_rejects_pilot_from_other_budget(tmp_path, monkeypatch):
    isolated(tmp_path, monkeypatch)
    pilot = {"results": [{} for _ in comparison.PILOT_CASES], "harness_config": {
        "timeout_seconds": 180, "frozen_provider": {"driver_source_sha256": "frozen-driver"}
    }}
    for runtime in ("current", "baseline"):
        (tmp_path / f"m3_apikl_frozen_{runtime}_pilot_quality_priority.json").write_text(json.dumps(pilot))
    args = comparison.build_parser().parse_args([
        "--phase", "full", "--generation", "quality_priority", "--timeout", "300"
    ])
    with pytest.raises(ValueError, match="measurement_timeout_changed_requires_new_generation"):
        comparison.main(args)


def test_resumed_phase_cannot_change_budget(tmp_path, monkeypatch):
    isolated(tmp_path, monkeypatch)
    state = {"implementation": {"run_frozen_eval.py": "frozen-driver"}, "timeout_seconds": 180}
    (tmp_path / "apikl_frozen_full_execution_quality_priority.json").write_text(json.dumps(state))
    args = comparison.build_parser().parse_args([
        "--phase", "full", "--generation", "quality_priority", "--timeout", "300", "--resume"
    ])
    with pytest.raises(ValueError, match="timeout_changed_requires_new_measurement_generation"):
        comparison.main(args)


def test_resumed_phase_cannot_change_latency_policy(tmp_path, monkeypatch):
    isolated(tmp_path, monkeypatch)
    state = {"implementation": {"run_frozen_eval.py": "frozen-driver"},
             "timeout_seconds": 300, "latency_policy": "non_regression"}
    (tmp_path / "apikl_frozen_full_execution_quality_priority.json").write_text(json.dumps(state))
    args = comparison.build_parser().parse_args([
        "--phase", "full", "--generation", "quality_priority", "--timeout", "300", "--resume",
        "--latency-policy", "report_only"
    ])
    with pytest.raises(ValueError, match="latency_policy_changed_requires_new_measurement_generation"):
        comparison.main(args)


@pytest.mark.parametrize("phase", ["full", "grade"])
def test_later_phase_cannot_relabel_strict_measurement_as_quality_priority(tmp_path, monkeypatch, phase):
    isolated(tmp_path, monkeypatch)
    report = {"results": [{} for _ in comparison.PILOT_CASES], "harness_config": {
        "timeout_seconds": 300, "latency_policy": "non_regression",
        "frozen_provider": {"driver_source_sha256": "frozen-driver"}
    }}
    qualifier = "pilot" if phase == "full" else "replay"
    for runtime in ("current", "baseline"):
        (tmp_path / f"m3_apikl_frozen_{runtime}_{qualifier}_quality_priority.json").write_text(json.dumps(report))
    args = comparison.build_parser().parse_args([
        "--phase", phase, "--generation", "quality_priority", "--timeout", "300",
        "--latency-policy", "report_only"
    ])
    with pytest.raises(ValueError, match="measurement_latency_policy_changed_requires_new_generation"):
        comparison.main(args)


def test_cli_rejects_unknown_latency_policy():
    with pytest.raises(SystemExit):
        comparison.build_parser().parse_args(["--phase", "pilot", "--latency-policy", "ignore_quality"])


def test_resumed_phase_cannot_change_explicit_artifact_root(tmp_path, monkeypatch):
    isolated(tmp_path, monkeypatch)
    configured = tmp_path / "new-artifacts"
    monkeypatch.setenv("FINSIGHT_EVAL_ARTIFACT_ROOT", str(configured))
    state = {"implementation": {"run_frozen_eval.py": "frozen-driver"},
             "timeout_seconds": 300, "latency_policy": "report_only", "artifact_root": str(tmp_path / "old-artifacts")}
    (tmp_path / "apikl_frozen_full_execution_quality_priority.json").write_text(json.dumps(state))
    args = comparison.build_parser().parse_args([
        "--phase", "full", "--generation", "quality_priority", "--timeout", "300", "--resume",
        "--latency-policy", "report_only"
    ])
    with pytest.raises(ValueError, match="artifact_root_changed_requires_new_measurement_generation"):
        comparison.main(args)


def test_full_measurement_stops_when_confirmed_budget_boundary_still_fails_in_pilot(tmp_path, monkeypatch):
    isolated(tmp_path, monkeypatch)
    report = {"results": [{"id": case, "structure": {"completed": case != "valuation-03"}}
                          for case in comparison.PILOT_CASES], "harness_config": {
        "timeout_seconds": 300, "latency_policy": "report_only",
        "frozen_provider": {"driver_source_sha256": "frozen-driver"}
    }}
    for runtime in ("current", "baseline"):
        (tmp_path / f"m3_apikl_frozen_{runtime}_pilot_quality_priority.json").write_text(json.dumps(report))
    args = comparison.build_parser().parse_args([
        "--phase", "full", "--generation", "quality_priority", "--timeout", "300",
        "--latency-policy", "report_only"
    ])
    with pytest.raises(ValueError, match="pilot_budget_finalization_boundary_failed_before_full"):
        comparison.main(args)

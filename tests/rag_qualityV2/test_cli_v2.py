from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = [
    PROJECT_ROOT / "tests" / "rag_qualityV2" / "run_layer1_v2.py",
    PROJECT_ROOT / "tests" / "rag_qualityV2" / "run_layer2_v2.py",
    PROJECT_ROOT / "tests" / "rag_qualityV2" / "run_layer3_v2.py",
]
THRESHOLDS = PROJECT_ROOT / "tests" / "rag_qualityV2" / "thresholds_v2.json"


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        cmd,
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def test_three_layers_mock_gate_pass(tmp_path: Path) -> None:
    for idx, script in enumerate(SCRIPTS, 1):
        output = tmp_path / f"layer{idx}.json"
        result = _run(
            [
                sys.executable,
                str(script),
                "--mock",
                "--gate",
                "--thresholds",
                str(THRESHOLDS),
                "--output",
                str(output),
                "--delay",
                "0",
                "--intra-case-delay",
                "0",
            ]
        )
        assert result.returncode == 0, result.stderr + "\n" + result.stdout
        assert output.exists()


def test_save_baseline(tmp_path: Path) -> None:
    script = PROJECT_ROOT / "tests" / "rag_qualityV2" / "run_layer1_v2.py"
    output = tmp_path / "report.json"
    baseline = tmp_path / "baseline.json"
    result = _run(
        [
            sys.executable,
            str(script),
            "--mock",
            "--save-baseline",
            "--thresholds",
            str(THRESHOLDS),
            "--baseline",
            str(baseline),
            "--output",
            str(output),
            "--delay",
            "0",
            "--intra-case-delay",
            "0",
        ]
    )
    assert result.returncode == 0, result.stderr + "\n" + result.stdout
    assert baseline.exists()
    payload = json.loads(baseline.read_text(encoding="utf-8"))
    assert "overall_metrics" in payload


def test_gate_failure_exit_code(tmp_path: Path) -> None:
    script = PROJECT_ROOT / "tests" / "rag_qualityV2" / "run_layer1_v2.py"
    strict_thresholds = tmp_path / "strict.json"
    cfg = json.loads(THRESHOLDS.read_text(encoding="utf-8"))
    cfg["metrics"]["keypoint_coverage"]["min"] = 0.99
    strict_thresholds.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    result = _run(
        [
            sys.executable,
            str(script),
            "--mock",
            "--gate",
            "--thresholds",
            str(strict_thresholds),
            "--output",
            str(tmp_path / "strict-report.json"),
            "--delay",
            "0",
            "--intra-case-delay",
            "0",
        ]
    )
    assert result.returncode == 1

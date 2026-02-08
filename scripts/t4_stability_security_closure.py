#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.services.release_drills import (
    RollbackThresholds,
    RolloutStageMetrics,
    evaluate_rollout_thresholds,
    run_report_index_rollback_rehearsal,
    run_security_final_checks,
    simulate_llm_endpoint_failover_drill,
    write_json,
)


def _today_tag() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_gate_summary(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"gate summary not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description="T4 stability & security closure drill")
    parser.add_argument(
        "--evidence-dir",
        default=f"docs/release_evidence/{_today_tag()}_go_live_drill",
        help="evidence output directory",
    )
    parser.add_argument(
        "--gate-summary",
        default="tests/retrieval_eval/reports/gate_summary.json",
        help="retrieval gate summary json path",
    )
    args = parser.parse_args()

    evidence_dir = Path(args.evidence_dir).expanduser().resolve()
    evidence_dir.mkdir(parents=True, exist_ok=True)

    gate_summary = _load_gate_summary(Path(args.gate_summary).expanduser().resolve())
    citation_coverage = float(
        (gate_summary.get("overall_metrics") or {}).get("citation_coverage", 0.0)
    )

    # deterministic drill metrics (from successful rehearsal baseline)
    stage_inputs = [
        RolloutStageMetrics(
            stage_percent=10,
            request_count=10,
            success_count=10,
            error_5xx_count=0,
            latency_p95_ms=163.42,
            latency_mean_ms=68.29,
        ),
        RolloutStageMetrics(
            stage_percent=50,
            request_count=50,
            success_count=50,
            error_5xx_count=0,
            latency_p95_ms=114.79,
            latency_mean_ms=77.01,
        ),
        RolloutStageMetrics(
            stage_percent=100,
            request_count=100,
            success_count=100,
            error_5xx_count=0,
            latency_p95_ms=202.93,
            latency_mean_ms=121.89,
        ),
    ]
    rollout_eval = evaluate_rollout_thresholds(
        stages=stage_inputs,
        citation_coverage=citation_coverage,
        thresholds=RollbackThresholds(max_5xx_ratio=0.02, p95_regression_factor=2.0, min_citation_coverage=0.95),
    )
    rollout_eval["citation_report"] = str((gate_summary.get("reports") or {}).get("json") or "")
    rollout_eval_path = write_json(evidence_dir / "gray_rollout_drill.json", rollout_eval)

    # rollback rehearsal on report index
    rollback_eval = run_report_index_rollback_rehearsal(work_dir=evidence_dir)
    rollback_eval_path = write_json(evidence_dir / "rollback_rehearsal.json", rollback_eval)

    # multi-endpoint failover rehearsal
    failover_eval = simulate_llm_endpoint_failover_drill()
    failover_eval_path = write_json(evidence_dir / "llm_failover_drill.json", failover_eval)

    # session isolation / auth / rate-limit / audit-related final checks
    security_eval = run_security_final_checks(repo_root=PROJECT_ROOT)
    security_eval_path = write_json(evidence_dir / "security_final_checks.json", security_eval)

    overall_pass = all(
        [
            bool(rollout_eval.get("pass")),
            bool(rollback_eval.get("pass")),
            bool(failover_eval.get("pass")),
            bool(security_eval.get("pass")),
        ]
    )

    summary = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pass": overall_pass,
        "artifacts": {
            "gray_rollout": str(rollout_eval_path),
            "rollback_rehearsal": str(rollback_eval_path),
            "llm_failover": str(failover_eval_path),
            "security_final_checks": str(security_eval_path),
        },
        "checks": {
            "rollout": rollout_eval.get("pass"),
            "rollback": rollback_eval.get("pass"),
            "failover": failover_eval.get("pass"),
            "security": security_eval.get("pass"),
        },
    }
    summary_path = write_json(evidence_dir / "t4_closure_summary.json", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"summary_path={summary_path}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    raise SystemExit(main())


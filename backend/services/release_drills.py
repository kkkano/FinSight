from __future__ import annotations

import importlib
import json
import sqlite3
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True)
class RollbackThresholds:
    max_5xx_ratio: float = 0.02
    p95_regression_factor: float = 2.0
    min_citation_coverage: float = 0.95


@dataclass(frozen=True)
class RolloutStageMetrics:
    stage_percent: int
    request_count: int
    success_count: int
    error_5xx_count: int
    latency_p95_ms: float
    latency_mean_ms: float | None = None

    @property
    def error_5xx_ratio(self) -> float:
        if self.request_count <= 0:
            return 0.0
        return self.error_5xx_count / self.request_count


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def evaluate_rollout_thresholds(
    *,
    stages: Sequence[RolloutStageMetrics],
    citation_coverage: float,
    thresholds: RollbackThresholds | None = None,
) -> dict[str, Any]:
    if not stages:
        raise ValueError("stages must not be empty")

    gate = thresholds or RollbackThresholds()
    baseline_p95 = max(float(stages[0].latency_p95_ms), 1e-6)

    evaluations: list[dict[str, Any]] = []
    rollback_stage_percent: int | None = None

    for stage in stages:
        ratio = float(stage.error_5xx_ratio)
        pass_5xx = ratio <= gate.max_5xx_ratio
        pass_p95 = float(stage.latency_p95_ms) <= baseline_p95 * gate.p95_regression_factor
        pass_citation = float(citation_coverage) >= gate.min_citation_coverage
        pass_stage = pass_5xx and pass_p95 and pass_citation

        reasons: list[str] = []
        if not pass_5xx:
            reasons.append(f"5xx_ratio_exceeded:{ratio:.4f}>{gate.max_5xx_ratio:.4f}")
        if not pass_p95:
            reasons.append(
                "p95_regression_exceeded:"
                f"{float(stage.latency_p95_ms):.2f}>{baseline_p95 * gate.p95_regression_factor:.2f}"
            )
        if not pass_citation:
            reasons.append(
                "citation_coverage_below_threshold:"
                f"{float(citation_coverage):.4f}<{gate.min_citation_coverage:.4f}"
            )

        item = {
            "stage_percent": int(stage.stage_percent),
            "request_count": int(stage.request_count),
            "success_count": int(stage.success_count),
            "error_5xx_count": int(stage.error_5xx_count),
            "error_5xx_ratio": ratio,
            "latency_p95_ms": float(stage.latency_p95_ms),
            "latency_mean_ms": float(stage.latency_mean_ms) if stage.latency_mean_ms is not None else None,
            "pass_5xx": pass_5xx,
            "pass_p95": pass_p95,
            "pass_citation": pass_citation,
            "pass_stage": pass_stage,
            "rollback_reasons": reasons,
        }
        evaluations.append(item)

        if rollback_stage_percent is None and not pass_stage:
            rollback_stage_percent = int(stage.stage_percent)

    passed = rollback_stage_percent is None
    return {
        "generated_at": _utc_now(),
        "thresholds": asdict(gate),
        "citation_coverage": float(citation_coverage),
        "baseline_p95_ms": baseline_p95,
        "stages": evaluations,
        "pass": passed,
        "rollback_triggered": not passed,
        "rollback_stage_percent": rollback_stage_percent,
    }


def run_report_index_rollback_rehearsal(*, work_dir: Path) -> dict[str, Any]:
    from scripts.report_index_migrate import run_migration
    from scripts.report_index_rollback import run_rollback

    work_dir.mkdir(parents=True, exist_ok=True)
    db_path = (work_dir / "report_index_release_drill.sqlite").resolve()
    backup_path = (work_dir / "report_index_release_drill.sqlite.pre_migration.bak").resolve()

    cleanup_paths = [
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
        Path(f"{db_path}-journal"),
        backup_path,
    ]
    for candidate in cleanup_paths:
        if candidate.exists():
            candidate.unlink()

    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE legacy_state(id INTEGER PRIMARY KEY, note TEXT)")
        conn.execute("INSERT INTO legacy_state(note) VALUES (?)", ("before-migrate",))
        conn.commit()

    backup_path.write_bytes(db_path.read_bytes())

    migration_result = run_migration(db_path=db_path, backup_path=backup_path)

    # emulate post-migration breakage to ensure rollback truly restores snapshot
    db_path.write_bytes(b"corrupted-report-index")

    rollback_result = run_rollback(db_path=db_path, backup_path=backup_path)

    with sqlite3.connect(db_path) as conn:
        table_names = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        restored_rows = conn.execute("SELECT note FROM legacy_state ORDER BY id ASC").fetchall()

    pass_data_restore = "legacy_state" in table_names and restored_rows == [("before-migrate",)]
    pass_schema_rollback = "report_index" not in table_names and "citation_index" not in table_names

    return {
        "generated_at": _utc_now(),
        "db_path": str(db_path),
        "backup_path": str(backup_path),
        "migration": migration_result,
        "rollback": rollback_result,
        "verification": {
            "table_names": sorted(table_names),
            "legacy_rows": [list(row) for row in restored_rows],
            "pass_data_restore": pass_data_restore,
            "pass_schema_rollback": pass_schema_rollback,
        },
        "pass": bool(pass_data_restore and pass_schema_rollback),
    }


def simulate_llm_endpoint_failover_drill() -> dict[str, Any]:
    import backend.llm_config as llm_config

    llm_config = importlib.reload(llm_config)

    now = {"t": 1_000.0}
    original_time_fn = llm_config.time.time
    llm_config.time.time = lambda: now["t"]

    try:
        primary = llm_config.EndpointConfig(
            name="primary",
            provider="openai_compatible",
            api_base="https://primary.example.com/v1",
            api_key="sk-primary-1234567890",
            model="drill-primary",
            weight=4,
            enabled=True,
            cooldown_sec=60,
        )
        backup = llm_config.EndpointConfig(
            name="backup",
            provider="openai_compatible",
            api_base="https://backup.example.com/v1",
            api_key="sk-backup-1234567890",
            model="drill-backup",
            weight=1,
            enabled=True,
            cooldown_sec=60,
        )
        manager = llm_config.EndpointManager(
            endpoints=[llm_config.EndpointRuntime(cfg=primary), llm_config.EndpointRuntime(cfg=backup)],
            fingerprint="t4-failover-drill",
        )

        first_selected = manager.select().name

        manager.report_failure("primary", reason="drill-primary-down")
        selected_after_failure = manager.select().name

        now["t"] += 61
        manager.report_success("primary")

        recovery_window = [manager.select().name for _ in range(6)]
        available_after_recovery = sorted([ep.cfg.name for ep in manager.endpoints if ep.is_available])

        pass_failover = selected_after_failure == "backup"
        pass_recovery = "primary" in recovery_window and "primary" in available_after_recovery

        return {
            "generated_at": _utc_now(),
            "first_selected": first_selected,
            "selected_after_primary_failure": selected_after_failure,
            "recovery_window": recovery_window,
            "available_after_recovery": available_after_recovery,
            "pass_failover": pass_failover,
            "pass_recovery": pass_recovery,
            "pass": bool(pass_failover and pass_recovery),
        }
    finally:
        llm_config.time.time = original_time_fn


def run_security_final_checks(
    *,
    repo_root: Path,
    pytest_targets: Sequence[str] | None = None,
) -> dict[str, Any]:
    targets = list(
        pytest_targets
        or [
            "backend/tests/test_security_gate_auth_rate_limit.py",
            "backend/tests/test_trace_and_session_security.py",
            "backend/tests/test_llm_rotation.py",
        ]
    )

    cmd = [sys.executable, "-m", "pytest", "-q", *targets]
    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    stdout_tail = "\n".join(stdout.strip().splitlines()[-40:])
    stderr_tail = "\n".join(stderr.strip().splitlines()[-40:])

    return {
        "generated_at": _utc_now(),
        "command": cmd,
        "targets": targets,
        "exit_code": int(proc.returncode),
        "pass": proc.returncode == 0,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
    }


def write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path

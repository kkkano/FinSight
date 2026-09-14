# -*- coding: utf-8 -*-
"""Execute-plan 职责拆分门禁。"""
from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_execute_plan_pipeline_is_an_orchestration_entrypoint() -> None:
    limits = {
        "backend/graph/execution/plan_pipeline.py": 600,
        "backend/graph/execution/evidence_pipeline.py": 900,
        "backend/graph/execution/evidence_tools.py": 900,
        "backend/rag/execution_observability.py": 900,
        "backend/rag/execution_pipeline.py": 900,
        "backend/rag/execution_support.py": 900,
    }

    violations: list[str] = []
    for relative, limit in limits.items():
        path = REPO_ROOT / relative
        if not path.exists():
            violations.append(f"{relative}:missing")
            continue
        lines = len(path.read_text(encoding="utf-8-sig").splitlines())
        if lines > limit:
            violations.append(f"{relative}:{lines}>{limit}")

    assert violations == []

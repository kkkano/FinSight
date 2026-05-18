# -*- coding: utf-8 -*-
from pathlib import Path
from types import SimpleNamespace

from backend.agents.base_agent import EvidenceItem


def test_agent_quality_eval_dataset_has_first_wave_agents():
    from scripts.agent_quality_eval import load_cases

    cases = load_cases(Path("tests/eval/agent_quality_cases.json"))

    assert len(cases) >= 3
    agents = {case["agent"] for case in cases}
    assert {"fundamental", "news", "risk_agent"}.issubset(agents)


def test_agent_quality_eval_runs_deterministic_agent_cases():
    from scripts.agent_quality_eval import evaluate_cases, load_cases

    cases = load_cases(Path("tests/eval/agent_quality_cases.json"))
    result = evaluate_cases(cases, run_id="unit")

    assert result["summary"]["case_count"] == len(cases)
    assert result["summary"]["fail_count"] == 0
    by_id = {row["id"]: row for row in result["cases"]}
    assert all(row["verdict"] == "PASS" for row in result["cases"])
    assert by_id["fundamental-aapl-quality"]["metrics"]["evidence_count"] >= 4
    assert by_id["news-aapl-quality"]["metrics"]["evidence_count"] >= 2
    assert by_id["risk-nvda-quality"]["metrics"]["risk_count"] >= 1
    assert result["summary"]["agent_averages"]["claim_source_ratio"] >= 0.9
    assert result["summary"]["agent_averages"]["self_check_pass_rate"] == 1.0
    assert all(row["metrics"]["self_check_status"] == "pass" for row in result["cases"])


def test_agent_quality_eval_fails_when_quality_hard_gates_are_missed():
    from scripts.agent_quality_eval import _grade_case

    case = {
        "id": "weak-quality",
        "agent": "fixture",
        "ticker": "AAPL",
        "expect": {
            "min_claim_source_ratio": 1.0,
            "require_agent_quality_status": "pass",
            "require_self_check_status": "pass",
        },
    }
    output = SimpleNamespace(
        agent_name="fixture",
        summary="AAPL has an unsupported claim.",
        evidence=[
            EvidenceItem(
                text="Revenue evidence",
                source="fixture",
                timestamp="2026-05-18T00:00:00Z",
                meta={"source_id": "source-1"},
            )
        ],
        claims=[
            {
                "claim": "Unsupported claim",
                "evidence_ids": ["missing-source"],
            }
        ],
        risks=[],
        data_sources=["fixture"],
        confidence=0.6,
        fallback_used=False,
        evidence_quality={
            "agent_quality": {"status": "warn"},
            "agent_self_check": {"status": "warn", "gaps": [{"code": "attach_sources"}]},
        },
    )

    row = _grade_case(case, output)

    assert row["verdict"] == "FAIL"
    assert any("claim_source_ratio" in issue for issue in row["issues"])
    assert any("agent_quality_status" in issue for issue in row["issues"])
    assert any("self_check_status" in issue for issue in row["issues"])


def test_agent_quality_eval_compare_reports_metric_deltas():
    from scripts.agent_quality_eval import compare_runs

    before = {
        "summary": {"agent_averages": {"claim_count": 0.0, "claim_source_ratio": 0.0}},
        "cases": [],
    }
    after = {
        "summary": {"agent_averages": {"claim_count": 3.0, "claim_source_ratio": 0.8}},
        "cases": [],
    }

    comparison = compare_runs(before, after)

    assert comparison["deltas"]["claim_count"] == 3.0
    assert comparison["deltas"]["claim_source_ratio"] == 0.8
    assert comparison["verdict"] == "PASS"

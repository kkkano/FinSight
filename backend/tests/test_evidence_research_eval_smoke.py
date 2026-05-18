# -*- coding: utf-8 -*-
from pathlib import Path


def test_evidence_research_eval_dataset_has_required_cases():
    from scripts.evidence_research_eval import load_cases

    cases = load_cases(Path("tests/eval/evidence_research_cases.json"))

    assert len(cases) >= 8
    case_ids = {case["id"] for case in cases}
    assert {
        "aapl-deep-report",
        "nvda-debate",
        "msft-risk-report",
        "tsla-form4",
        "berkshire-aapl-overlap",
        "portfolio-nvda-msft-aapl",
        "cn-sec-holdings-reject",
        "unsafe-insider-boundary",
    }.issubset(case_ids)


def test_evidence_research_eval_grades_contract_metrics():
    from scripts.evidence_research_eval import evaluate_cases, load_cases

    cases = load_cases(Path("tests/eval/evidence_research_cases.json"))
    result = evaluate_cases(cases, run_id="unit")

    assert result["summary"]["case_count"] == len(cases)
    assert result["summary"]["fail_count"] == 0
    assert result["summary"]["pass_count"] == len(cases)

    by_id = {row["id"]: row for row in result["cases"]}
    assert by_id["nvda-debate"]["metrics"]["debate_artifact_present"] is True
    assert by_id["tsla-form4"]["metrics"]["holdings_latency_disclosed"] is True
    assert by_id["unsafe-insider-boundary"]["metrics"]["unsafe_insider_request_blocked"] is True

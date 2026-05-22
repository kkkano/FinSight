# -*- coding: utf-8 -*-
from scripts.skill_python_eval import evaluate_cases, load_cases


def test_skill_python_eval_cases_cover_core_query_shapes():
    cases = load_cases("tests/eval/skill_python_query_cases.json")
    case_ids = {case["id"] for case in cases}

    assert {
        "price_short_path",
        "technical_short_path",
        "earnings_performance",
        "earnings_price_impact",
        "investment_opinion",
        "valuation_sanity",
        "earnings_good_price_down",
    }.issubset(case_ids)


def test_skill_python_eval_gate_passes_expected_policy_planner_contracts():
    cases = load_cases("tests/eval/skill_python_query_cases.json")
    failures = evaluate_cases(cases)

    assert failures == []

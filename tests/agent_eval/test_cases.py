"""评测资产的协议与结构校验；自然语言要求由判分模型判断。"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent
GROUP_COUNTS = {
    "facts": 6, "valuation": 6, "attribution": 6, "news": 5,
    "statistics": 6, "comparison": 5, "multiturn": 6, "concepts": 4,
    "failures": 5, "local_markets": 4, "reports": 4, "actions": 3,
}


def load_asset(name: str) -> dict:
    return json.loads((ROOT / name).read_text(encoding="utf-8"))


def test_dataset_contains_exactly_sixty_cases():
    assert len(load_asset("cases.json")["cases"]) == 60


@pytest.mark.parametrize("group,count", GROUP_COUNTS.items())
def test_each_capability_group_has_the_planned_case_count(group, count):
    actual = Counter(case["group"] for case in load_asset("cases.json")["cases"])
    assert actual[group] == count


def test_declared_groups_match_the_plan():
    assert load_asset("cases.json")["groups"] == GROUP_COUNTS


def test_case_identifiers_are_unique():
    identifiers = [case["id"] for case in load_asset("cases.json")["cases"]]
    assert len(identifiers) == len(set(identifiers))


def test_every_case_contains_nonempty_turns():
    assert all(
        isinstance(case["turns"], list) and case["turns"]
        and all(isinstance(turn, str) and turn.strip() for turn in case["turns"])
        for case in load_asset("cases.json")["cases"]
    )


@pytest.mark.parametrize("field", ["must", "must_not"])
def test_semantic_requirements_remain_natural_language_lists(field):
    assert all(
        isinstance(case[field], list)
        and all(isinstance(requirement, str) and requirement.strip() for requirement in case[field])
        for case in load_asset("cases.json")["cases"]
    )


def test_artifact_requirements_use_structured_types():
    assert all(
        isinstance(case["expects"]["artifacts"], list)
        and set(case["expects"]["artifacts"]) <= {"chart", "table", "report", "action"}
        for case in load_asset("cases.json")["cases"]
    )


def test_fixture_paths_are_case_local_relative_paths():
    assert all(
        case["fixtures"] == "fixtures/" + case["id"]
        for case in load_asset("cases.json")["cases"]
    )


def test_concept_cases_explicitly_require_no_data_tools():
    assert all(
        case["expects"]["no_data_tools"] is True
        for case in load_asset("cases.json")["cases"] if case["group"] == "concepts"
    )


def test_report_cases_explicitly_select_report_mode():
    assert all(
        case["mode"] == "investment_report"
        for case in load_asset("cases.json")["cases"] if case["group"] == "reports"
    )


def test_failure_cases_define_machine_addressed_faults():
    assert all(
        isinstance(case["tool_faults"], dict) and case["tool_faults"]
        and all(
            isinstance(name, str) and fault["status"] in {"empty", "error"}
            and isinstance(fault["code"], str)
            for name, fault in case["tool_faults"].items()
        )
        for case in load_asset("cases.json")["cases"] if case["group"] == "failures"
    )


def test_review_data_is_explicitly_synthetic():
    assert load_asset("review_cases.json")["synthetic"] is True


def test_review_dataset_contains_at_least_twelve_pairs():
    assert len(load_asset("review_cases.json")["cases"]) >= 12


def test_review_identifiers_are_unique():
    identifiers = [case["id"] for case in load_asset("review_cases.json")["cases"]]
    assert len(identifiers) == len(set(identifiers))


def test_review_pairs_preserve_clean_and_injected_answers():
    assert all(
        isinstance(case["clean"]["answer"], str) and case["clean"]["answer"]
        and isinstance(case["injected"]["answer"], str) and case["injected"]["answer"]
        and case["clean"]["answer"] != case["injected"]["answer"]
        for case in load_asset("review_cases.json")["cases"]
    )


def test_review_dataset_covers_numeric_direction_and_source_errors():
    actual = {case["injected"]["injection"]["kind"] for case in load_asset("review_cases.json")["cases"]}
    assert actual == {"number", "direction", "source"}


def test_each_review_injection_changes_only_the_declared_span():
    assert all(
        case["clean"]["answer"].replace(
            case["injected"]["injection"]["before"],
            case["injected"]["injection"]["after"], 1,
        ) == case["injected"]["answer"]
        for case in load_asset("review_cases.json")["cases"]
    )


def test_review_fixture_results_use_typed_envelopes():
    assert all(
        result["status"] == "ok"
        and result["kind"] in {"quote", "series", "table", "news", "document", "computation", "chart", "control"}
        and result["handle"].startswith("h_")
        and result["sources"]
        and all(type(source["id"]) is int and source["id"] > 0 for source in result["sources"])
        for case in load_asset("review_cases.json")["cases"] for result in case["fixtures"]
    )


def test_clean_reviews_expect_no_findings():
    assert all(
        case["clean"]["expected"] == {"verdict": "pass", "findings": []}
        for case in load_asset("review_cases.json")["cases"]
    )


def test_injected_review_quotes_are_verbatim_answer_spans():
    assert all(
        finding["quote"] in case["injected"]["answer"]
        for case in load_asset("review_cases.json")["cases"]
        for finding in case["injected"]["expected"]["findings"]
    )


def test_injected_reviews_expect_actionable_findings():
    assert all(
        case["injected"]["expected"]["verdict"] == "revise"
        and case["injected"]["expected"]["findings"]
        and all(finding["evidence_source_id"] in {source["id"] for result in case["fixtures"] for source in result["sources"]}
                for finding in case["injected"]["expected"]["findings"])
        for case in load_asset("review_cases.json")["cases"]
    )

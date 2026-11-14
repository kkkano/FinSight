"""资源容忍只调整有证据且交付有效的操作指标，原评分/报告不可变。"""
from copy import deepcopy
import hashlib
import json

import pytest

from .acceptance import ResourcePolicy, evaluate_acceptance, evaluate_files
from .scoring import summarize


def fixture_report(runtime):
    rows = []
    for index in range(60):
        rows.append({"id": f"fixture-{index}", "group": "facts", "elapsed_seconds": 100,
            "score": {"answered": 2, "numbers": 2, "limitations": 1, "presentation": 1,
                      "no_internal_identifiers": 1, "reasons": ["独立合成判分。"], "total": 7, "model": "fixture-judge"},
            "structure": {"completed": True, "single_terminal_per_turn": True, "references_valid": True,
                          "artifacts_met": True, "no_data_tools_met": True, "no_actions_met": True,
                          "tokens": 90000, "rounds": 1, "tool_error_rate": 0},
            "turns": [{"model_calls": 1, "terminal_count": 1,
                       "terminal": {"type": "done", "response": "合成价格42美元。[1]", "answer_status": "answered",
                                    "metrics": {"total_tokens": 90000, "stopped": "completed"}}}],
            "model_call_outcomes": [{"status": "completed", "model": "fixture-model"}]})
    return {"runtime": runtime, "mode": "replay", "ready": True, "expected_cases": 60,
        "subject": {"model": "fixture-model", "base_url": "https://fixture.invalid/v1"},
        "harness_config": {"latency_policy": "report_only", "timeout_seconds": 300,
                           "model_quotas": {"run_token_budget": 160000}},
        "judge": {"model": "fixture-judge", "base_url": "https://judge.invalid/v1",
                  "context_window": 131072, "max_output": 8192, "protocol": "tools"},
        "cases_sha256": "fixture-cases", "fixtures_sha256": "fixture-data",
        "judge_prompt_sha256": "fixture-rubric", "results": rows, "groups": summarize(rows)}


def pair():
    return fixture_report("baseline"), fixture_report("current")


def budget_terminal(report):
    row = report["results"][0]
    row["structure"]["completed"] = False
    row["turns"][0]["terminal"].update(type="error", error_code="run_token_budget_exhausted",
                                       answer_status="partial")
    return row


def refresh(report):
    report["groups"] = summarize(report["results"])


def test_reasonable_budget_terminal_with_full_delivery_is_separately_accepted():
    before, after = pair()
    row = budget_terminal(after)
    row["elapsed_seconds"] = 330
    row["turns"][0]["terminal"]["metrics"]["total_tokens"] = 168000
    refresh(after)
    original = deepcopy((before, after))
    result = evaluate_acceptance(before, after)
    assert not result["raw_strict_comparison"]["passed"]
    assert result["passed"] and result["status"] == "accepted"
    assert result["ignored_resource_regressions"] == ["facts:completed_rate"]
    assert result["adjusted_metrics"]["current"]["facts"]["accepted_budget_terminal_cases"] == 1
    assert (before, after) == original


def test_confirmed_final_internal_deadline_cancel_is_not_counted_as_provider_failure():
    before, after = pair()
    row = after["results"][0]
    row["turns"][0]["terminal"]["metrics"]["stopped"] = "continuation_deadline"
    row["model_call_outcomes"].append({"status": "cancelled", "model": "fixture-model"})
    row["turns"][0]["model_calls"] = 2
    refresh(after)
    result = evaluate_acceptance(before, after)
    assert result["passed"]
    assert result["ignored_resource_regressions"] == ["facts:model_failure_rate"]
    audit = result["case_audits"]["current"][0]
    assert audit["ignored_budget_outcome_indices"] == [1]
    assert audit["budget_attributions"][0]["reason"] == "continuation_deadline"


def test_unknown_cancel_is_uncertain_and_requires_review_without_budget_attribution():
    before, after = pair()
    row = after["results"][0]
    row["model_call_outcomes"] = [{"status": "cancelled"}]
    refresh(after)
    result = evaluate_acceptance(before, after)
    assert not result["passed"] and result["status"] == "needs_review"
    assert result["operational_uncertain"] == [{"runtime": "current", "case_id": "fixture-0", "outcome_indices": [0]}]
    assert not result["ignored_resource_regressions"] and not result["quality_regressions"]


def test_generic_model_timeout_is_not_inferred_to_be_a_budget_failure():
    before, after = pair()
    row = after["results"][0]
    row["model_call_outcomes"] = [{"status": "failed", "error_code": "model_timeout"}]
    row["turns"][0]["terminal"]["metrics"]["stopped"] = "deadline"
    refresh(after)
    result = evaluate_acceptance(before, after)
    assert not result["passed"] and result["status"] == "needs_review"
    assert result["case_audits"]["current"][0]["ignored_budget_outcome_indices"] == []


def test_http_failure_is_never_hidden_by_a_budget_marker():
    before, after = pair()
    row = after["results"][0]
    row["model_call_outcomes"] = [{"status": "failed", "error_code": "model_http_502"}]
    row["turns"][0]["terminal"]["metrics"]["stopped"] = "deadline"
    refresh(after)
    result = evaluate_acceptance(before, after)
    assert not result["passed"] and result["status"] == "rejected"
    assert result["non_budget_protocol_failure_cases"] == ["fixture-0"]
    assert not result["ignored_resource_regressions"]


def test_transport_layer_http_error_without_an_outcome_still_blocks_automatic_acceptance():
    before, after = pair()
    after["results"][0]["transport_errors"] = [{"code": "model_http_502"}]
    result = evaluate_acceptance(before, after)
    assert not result["passed"] and result["status"] == "rejected"
    assert result["non_budget_protocol_failure_cases"] == ["fixture-0"]


def test_completed_body_with_unattributed_transport_timeout_still_requires_review():
    before, after = pair()
    after["results"][0]["transport_errors"] = [{"code": "model_timeout"}]
    result = evaluate_acceptance(before, after)
    assert not result["passed"] and result["status"] == "needs_review"
    assert result["operational_uncertain"][0]["transport_error_codes"] == ["model_timeout"]


@pytest.mark.parametrize("field", ["answered", "numbers", "limitations", "presentation", "no_internal_identifiers"])
def test_content_quality_regression_remains_rejected(field):
    before, after = pair()
    row = budget_terminal(after)
    row["score"][field] -= 1
    row["score"]["total"] -= 1
    refresh(after)
    result = evaluate_acceptance(before, after)
    assert not result["passed"] and result["status"] == "rejected"
    assert "facts:" + field in result["quality_regressions"]


def test_empty_answer_cannot_become_success_even_if_score_claims_full_delivery():
    before, after = pair()
    row = budget_terminal(after)
    row["turns"][0]["terminal"]["response"] = ""
    refresh(after)
    result = evaluate_acceptance(before, after)
    assert not result["passed"] and result["status"] == "rejected"
    assert result["critical_budget_delivery_cases"] == ["fixture-0"]
    assert not result["ignored_resource_regressions"]


@pytest.mark.parametrize("kind", ["time", "tokens"])
def test_large_budget_variation_requires_review_and_is_not_called_quality_failure(kind):
    before, after = pair()
    row = budget_terminal(after)
    if kind == "time":
        row["elapsed_seconds"] = 400
    else:
        row["turns"][0]["terminal"]["metrics"]["total_tokens"] = 210000
    refresh(after)
    result = evaluate_acceptance(before, after)
    assert not result["passed"] and result["status"] == "needs_review"
    assert not result["quality_regressions"] and not result["ignored_resource_regressions"]
    assert result["requires_manual_review"]


def test_missing_scores_cannot_pass_resource_acceptance():
    before, after = pair()
    after["results"][0]["score"] = None
    after["ready"] = False
    refresh(after)
    result = evaluate_acceptance(before, after)
    assert not result["passed"] and result["status"] == "incomplete_or_invalid_inputs"
    assert "current:fixture-0:missing_or_invalid_score" in result["integrity_errors"]


def test_score_needs_a_verified_judge_binding():
    before, after = pair()
    after["results"][0]["score"].pop("model")
    result = evaluate_acceptance(before, after)
    assert not result["passed"] and "current:fixture-0:missing_or_invalid_score" in result["integrity_errors"]


def test_duplicate_terminal_and_missing_required_artifact_are_never_waived():
    before, after = pair()
    row = budget_terminal(after)
    row["structure"].update(single_terminal_per_turn=False, artifacts_met=False)
    row["turns"][0]["terminal_count"] = 2
    refresh(after)
    result = evaluate_acceptance(before, after)
    assert not result["passed"] and result["status"] == "rejected"
    assert "facts:single_terminal_rate" in result["quality_regressions"]
    assert "facts:artifacts_met_rate" in result["quality_regressions"]


def test_time_tolerance_is_explicitly_case_aggregate_not_per_turn():
    before, after = pair()
    row = budget_terminal(after)
    row["turns"].append(deepcopy(before["results"][0]["turns"][0]))
    row["model_call_outcomes"].append({"status": "completed"})
    row["elapsed_seconds"] = 700
    refresh(after)
    result = evaluate_acceptance(before, after)
    audit = result["case_audits"]["current"][0]
    assert audit["resources"]["time_scope"] == "case_aggregate_only"
    assert audit["resources"]["case_time_ratio"] == pytest.approx(700 / 600)
    assert result["passed"]


def test_original_file_bytes_and_input_hashes_are_preserved(tmp_path):
    before, after = pair()
    budget_terminal(after)
    refresh(after)
    a, b = tmp_path / "before.json", tmp_path / "after.json"
    a.write_text(json.dumps(before, indent=2), encoding="utf-8")
    b.write_text(json.dumps(after, indent=4), encoding="utf-8")
    original = (a.read_bytes(), b.read_bytes())
    result = evaluate_files(a, b)
    assert result["passed"] and (a.read_bytes(), b.read_bytes()) == original
    assert result["inputs"]["baseline"]["sha256"] == hashlib.sha256(original[0]).hexdigest()
    assert result["inputs"]["current"]["sha256"] == hashlib.sha256(original[1]).hexdigest()
    assert result["inputs"]["current"]["kind"] == "file_bytes"


def test_case_identity_mismatch_and_invalid_policy_are_rejected():
    before, after = pair()
    after["results"][0]["id"] = "other-case"
    result = evaluate_acceptance(before, after)
    assert not result["passed"] and "case_id_sets_differ" in result["integrity_errors"]
    with pytest.raises(ValueError, match="invalid_resource_tolerance"):
        ResourcePolicy(max_overrun_ratio=float("inf"))

"""评分协议必须拒绝缺失、伪造类型和不可比的基线。"""
from copy import deepcopy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent_eval.scoring import ContentScore, JUDGE_SYSTEM, ScoreSubmissionError, compare, judge_answer, judge_prompt, structural_score, summarize


SCORE = {"answered": 2, "numbers": 2, "limitations": 1, "presentation": 1,
         "no_internal_identifiers": 1, "reasons": ["依据录制资料逐条核对。"]}


class JSONJudge:
    def __init__(self, content=None, finish="stop"):
        self.config = SimpleNamespace(model="fixture-judge", context_window=131072, max_output=8192)
        self.content = json.dumps(SCORE) if content is None else content
        self.finish, self.requests = finish, []

    async def complete_json(self, messages, **kwargs):
        self.requests.append((messages, kwargs))
        return {"choices": [{"message": {"content": self.content}, "finish_reason": self.finish}],
                "usage": {"prompt_tokens": 123, "completion_tokens": 10}}


def score_input():
    case = {"id": "fixture", "turns": ["用户问题"], "must": ["核对录制数字"], "must_not": ["编造数字"]}
    result = {"model": "fixture-subject", "turns": [{"query": "用户问题", "terminal": {"response": "原始回答"}}]}
    recordings = [{"tool": "fixture_tool", "arguments": {"ticker": "AAPL"},
                   "result": {"status": "ok", "data": [1, 2, 3]}, "injected": False}]
    return case, result, recordings


@pytest.mark.asyncio
async def test_json_judge_keeps_full_inputs_and_uses_strict_rubric_schema():
    transport = JSONJudge()
    case, result, recordings = score_input()
    unchanged = deepcopy((case, result, recordings))
    score = await judge_answer(transport, case, result, recordings, protocol="json")
    assert score["total"] == 7 and score["model"] == transport.config.model
    messages, kwargs = transport.requests[0]
    assert kwargs["timeout"] == 90
    payload = json.loads(messages[1]["content"])
    assert payload["case"] == case and payload["recordings"] == recordings
    assert payload["answers"][0]["answer"] == result["turns"][0]["terminal"]["response"]
    assert (case, result, recordings) == unchanged
    assert json.dumps(ContentScore.model_json_schema(), ensure_ascii=False, sort_keys=True) in messages[0]["content"]


@pytest.mark.asyncio
@pytest.mark.parametrize("content", ["不是 JSON", "```json\n" + json.dumps(SCORE) + "\n```",
                                    "<think>过程</think>" + json.dumps(SCORE),
                                    json.dumps({**SCORE, "total": 7}), json.dumps({**SCORE, "answered": True}),
                                    json.dumps({"answered": 2})])
async def test_json_judge_rejects_non_json_wrappers_extra_fields_and_invalid_scores(content):
    with pytest.raises(ValidationError):
        await judge_answer(JSONJudge(content), *score_input(), protocol="json")


@pytest.mark.asyncio
async def test_json_judge_rejects_length_even_if_content_is_valid_json():
    with pytest.raises(ScoreSubmissionError) as caught:
        await judge_answer(JSONJudge(finish="length"), *score_input(), protocol="json")
    assert caught.value.code == "judge_incomplete_submission"
    assert caught.value.details["finish_reason"] == "length"


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["tools", "json", "external"])
async def test_independent_judge_is_required_for_both_protocols(protocol):
    transport = JSONJudge()
    case, result, recordings = score_input()
    result["model"] = transport.config.model
    with pytest.raises(ValueError, match="^judge_must_differ_from_subject$"):
        await judge_answer(transport, case, result, recordings, protocol=protocol)
    assert transport.requests == []


@pytest.mark.asyncio
async def test_default_judge_protocol_keeps_native_submit_score_semantics():
    seen = []

    class NativeJudge:
        config = SimpleNamespace(model="fixture-judge", context_window=131072, max_output=8192)

        async def stream(self, messages, tools, **kwargs):
            seen.append((messages, tools, kwargs))
            yield {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {
                "name": "submit_score", "arguments": json.dumps(SCORE)}}]}, "finish_reason": "tool_calls"}]}

    score = await judge_answer(NativeJudge(), *score_input())
    assert score["total"] == 7 and seen[0][0][0]["content"] == JUDGE_SYSTEM
    assert seen[0][2]["tool_choice"] == {"type": "function", "function": {"name": "submit_score"}}
    assert judge_prompt("tools") == JUDGE_SYSTEM


def test_judge_protocol_and_prompt_are_part_of_comparison_configuration():
    judge = {"model": "fixture-judge", "base_url": "https://judge.invalid", "context_window": 131072,
             "max_output": 8192, "protocol": "tools"}
    before = {"mode": "replay", "harness_config": {}, "judge": judge, "cases_sha256": "same",
              "fixtures_sha256": "same", "judge_prompt_sha256": "tools-prompt", "ready": True, "groups": {}}
    assert compare(before, before)["passed"] is True
    assert compare(before, {**before, "judge": {**judge, "protocol": "json"}})["reason"] == "judge_configuration_differs"
    assert compare(before, {**before, "judge_prompt_sha256": "json-prompt"})["reason"] == "evaluation_inputs_differ"
    assert compare(before, {**before, "judge": {key: value for key, value in judge.items() if key != "protocol"}})["passed"] is False


def test_content_score_requires_all_rubric_fields():
    with pytest.raises(ValidationError):
        ContentScore.model_validate({"answered": 2})


@pytest.mark.parametrize("value", [True, "2", 3, -1])
def test_content_score_rejects_non_integer_or_out_of_range(value):
    with pytest.raises(ValidationError):
        ContentScore(answered=value, numbers=2, limitations=1, presentation=1,
                     no_internal_identifiers=1, reasons=["依据样本核对。"])


def test_unknown_integer_reference_and_missing_artifact_are_reported():
    result = structural_score({"turns": ["fixture"], "expects": {"artifacts": ["chart"]}},
        [{"terminal": {"type": "done", "response": "资料[2]", "evidence_pool": [{"source_id": 1}]}}], [])
    assert result["unknown_references"] == ["2"]
    assert result["missing_artifacts"] == ["chart"]


def test_unjudged_result_is_not_given_zero_or_full_score():
    groups = summarize([{"group": "facts", "score": None, "elapsed_seconds": 1,
        "structure": {"completed": False, "references_valid": True, "artifacts_met": True,
                      "tokens": 0, "rounds": 0, "tool_error_rate": 0}}])
    assert groups["facts"]["judged"] == 0
    assert groups["facts"]["scores"]["total"] is None


def test_different_fixture_sets_cannot_pass_comparison():
    assert compare({"cases_sha256": "same", "fixtures_sha256": "a"},
                   {"cases_sha256": "same", "fixtures_sha256": "b"})["passed"] is False


def test_different_request_pacing_cannot_pass_comparison():
    before = {"mode": "replay", "harness_config": {"request_interval_seconds": 6.1, "jobs": 1}}
    after = {**before, "harness_config": {"request_interval_seconds": 0, "jobs": 1}}
    assert compare(before, after)["reason"] == "evaluation_scheduler_differs"


def test_different_evaluation_compute_configuration_cannot_pass_comparison():
    before = {"mode": "replay", "harness_config": {"analysis_worker_enabled": True}}
    after = {**before, "harness_config": {"analysis_worker_enabled": False}}
    assert compare(before, after)["reason"] == "evaluation_scheduler_differs"


def test_different_judge_models_or_budgets_cannot_pass_comparison():
    before = {"mode": "replay", "judge": {"model": "fixture-judge", "max_output": 8192}}
    changed_model = {**before, "judge": {"model": "another-judge", "max_output": 8192}}
    changed_budget = {**before, "judge": {"model": "fixture-judge", "max_output": 16384}}
    assert compare(before, changed_model)["reason"] == "judge_configuration_differs"
    assert compare(before, changed_budget)["reason"] == "judge_configuration_differs"


def test_incomplete_evaluation_cannot_pass_comparison():
    report = {"cases_sha256": "same", "fixtures_sha256": "same", "judge_prompt_sha256": "same", "ready": False, "groups": {}}
    assert compare(report, report)["passed"] is False


def test_explicit_no_actions_contract_checks_proposals():
    case = {"turns": ["fixture"], "expects": {"artifacts": [], "no_actions": True}}
    turns = [{"terminal": {"type": "done", "response": "fixture"}}]
    assert structural_score(case, turns, [{"runtime_type": "action.proposed"}])["no_actions_met"] is False


def test_loading_skill_is_not_counted_as_research_data():
    case = {"turns": ["fixture"], "expects": {"no_data_tools": True}}
    event = {"runtime_type": "tool.result", "payload": {"name": "use_skill", "data_refs": ["control"]}}
    assert structural_score(case, [{"terminal": {"type": "done"}}], [event])["no_data_tools_met"] is True


@pytest.mark.parametrize("failure", ["model_timeout", "duplicate_terminal"])
@pytest.mark.parametrize("policy", ["non_regression", "report_only"])
def test_model_or_terminal_protocol_regression_cannot_pass_comparison(failure, policy):
    row = {"group": "facts", "score": {**SCORE, "total": 7}, "elapsed_seconds": 1,
           "structure": {"completed": True, "single_terminal_per_turn": True, "references_valid": True,
                         "artifacts_met": True, "no_actions_met": True, "tokens": 10, "rounds": 1, "tool_error_rate": 0},
           "model_call_outcomes": [{"model": "fixture-subject", "status": "completed", "received_chunks": 1}]}
    report = {"mode": "replay", "harness_config": {}, "judge": {"model": "fixture-judge", "base_url": "https://fixture.invalid",
              "context_window": 131072, "max_output": 8192, "protocol": "tools"}, "cases_sha256": "same",
              "fixtures_sha256": "same", "judge_prompt_sha256": "same", "ready": True, "groups": summarize([row])}
    changed = deepcopy(row)
    report["harness_config"]["latency_policy"] = policy
    if failure == "model_timeout":
        changed["model_call_outcomes"] = [{"model": "fixture-subject", "status": "failed", "error_code": "model_timeout", "received_chunks": 0}]
    else:
        changed["structure"].update(single_terminal_per_turn=False, completed=False)
    after = {**report, "groups": summarize([changed])}
    assert compare(report, report)["passed"] is True
    result = compare(report, after)
    expected = "facts:model_failure_rate" if failure == "model_timeout" else "facts:single_terminal_rate"
    assert result["passed"] is False and expected in result["regressions"]


def latency_fixture(policy=None):
    row = {"group": "facts", "score": {**SCORE, "total": 7}, "elapsed_seconds": 1,
           "structure": {"completed": True, "single_terminal_per_turn": True, "references_valid": True,
                         "artifacts_met": True, "no_actions_met": True, "tokens": 10, "rounds": 1, "tool_error_rate": 0},
           "model_call_outcomes": [{"model": "fixture-subject", "status": "completed"}]}
    report = {"mode": "replay", "harness_config": {}, "judge": {"model": "fixture-judge", "base_url": "https://fixture.invalid",
              "context_window": 131072, "max_output": 8192, "protocol": "tools"}, "cases_sha256": "same",
              "fixtures_sha256": "same", "judge_prompt_sha256": "same", "ready": True, "groups": summarize([row])}
    if policy is not None:
        report["harness_config"]["latency_policy"] = policy
    return row, report


def test_legacy_reports_keep_strict_latency_regression_gate():
    row, before = latency_fixture()
    changed = {**row, "elapsed_seconds": 10}
    result = compare(before, {**before, "groups": summarize([changed])})
    assert result["passed"] is False
    assert "facts:median_seconds" in result["regressions"]
    assert result["latency_policy"] == "non_regression"


def test_quality_priority_keeps_latency_delta_visible_without_rejecting_slower_answer():
    row, before = latency_fixture("report_only")
    after = {**before, "groups": summarize([{**row, "elapsed_seconds": 100}])}
    unchanged = deepcopy((before, after))
    result = compare(before, after)
    assert result["passed"] is True and result["deltas"]["facts"]["median_seconds"] == 99
    assert result["latency_policy"] == "report_only"
    assert (before, after) == unchanged


@pytest.mark.parametrize("field", ["answered", "numbers", "limitations", "presentation", "no_internal_identifiers"])
def test_quality_priority_cannot_hide_content_quality_regressions(field):
    row, before = latency_fixture("report_only")
    changed = deepcopy(row)
    changed["score"][field] -= 1
    changed["score"]["total"] -= 1
    changed["elapsed_seconds"] = 100
    result = compare(before, {**before, "groups": summarize([changed])})
    assert result["passed"] is False and f"facts:{field}" in result["regressions"]
    assert result["deltas"]["facts"]["median_seconds"] == 99


def test_latency_policies_must_match_and_unknown_policy_cannot_disable_gate():
    _, before = latency_fixture("report_only")
    assert compare(before, {**before, "harness_config": {"latency_policy": "non_regression"}})["reason"] == "evaluation_latency_policy_differs"
    invalid = {**before, "harness_config": {"latency_policy": "ignore_quality"}}
    assert compare(invalid, invalid)["reason"] == "evaluation_latency_policy_invalid"


def test_legacy_policy_defaults_to_explicit_non_regression_without_mutating_reports():
    _, legacy = latency_fixture()
    explicit = {**legacy, "harness_config": {"latency_policy": "non_regression"}}
    assert compare(legacy, explicit)["passed"] is True
    assert legacy["harness_config"] == {}

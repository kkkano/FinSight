"""独立资源验收投影；不修改原始报告、分数或严格比较。

25% 是本层的默认资源波动容忍，不提高实跑预算或费用。无逐轮耗时时，
时间只按 case 总耗时 / (每轮预算 × 轮数) 判断，不能推定每轮均未超限。
没有有效交付、缺评分、质量退步和不能确证的取消均不能借预算获得通过。
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path

from .scoring import ContentScore, SCORE_FIELDS, compare, summarize


BUDGET_ERRORS = {"run_token_budget_exhausted", "run_deadline_exceeded"}
BUDGET_STOPS = {"deadline", "token_budget", "revision_deadline", "continuation_deadline",
                "revision_token_budget", "continuation_token_budget"}
DEADLINE_STOPS = {"deadline", "revision_deadline", "continuation_deadline"}
FAILURE_STATUSES = {"failed", "cancelled"}
STRUCTURE_FLAGS = ("completed", "single_terminal_per_turn", "references_valid", "artifacts_met",
                   "no_data_tools_met", "no_actions_met")


@dataclass(frozen=True)
class ResourcePolicy:
    max_overrun_ratio: float = 0.25
    expected_cases: int = 60
    version: str = "resource-tolerance-v1"

    def __post_init__(self):
        if (isinstance(self.max_overrun_ratio, bool) or not isinstance(self.max_overrun_ratio, (int, float))
                or not math.isfinite(self.max_overrun_ratio) or not 0 <= self.max_overrun_ratio <= 1):
            raise ValueError("invalid_resource_tolerance")
        if type(self.expected_cases) is not int or self.expected_cases != 60:
            raise ValueError("complete_60_case_policy_required")


def _number(value):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and value >= 0)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _score_valid(row, report):
    score = row.get("score")
    if not isinstance(score, dict):
        return False
    try:
        parsed = ContentScore.model_validate({key: score[key] for key in (*SCORE_FIELDS, "reasons")})
    except (KeyError, ValueError):
        return False
    return (type(score.get("total")) is int and score["total"] == sum(getattr(parsed, key) for key in SCORE_FIELDS)
            and (score.get("model") == report.get("judge", {}).get("model") or
                 "external_judge" in row and row.get("external_judge_verified") is True)
            and ("external_judge" not in row or row.get("external_judge_verified") is True))


def _integrity_errors(baseline, current, policy):
    errors, identities = [], []
    if not baseline.get("subject") or baseline.get("subject") != current.get("subject"):
        errors.append("subject_model_configuration_differs_or_missing")
    for name, report in (("baseline", baseline), ("current", current)):
        rows = report.get("results", [])
        ids = [row.get("id") for row in rows]
        identities.append(set(ids))
        if (report.get("expected_cases") != policy.expected_cases or len(rows) != policy.expected_cases
                or len(set(ids)) != len(ids) or any(not isinstance(value, str) or not value for value in ids)):
            errors.append(name + ":incomplete_case_set")
        if report.get("ready") is not True:
            errors.append(name + ":not_ready")
        judge = report.get("judge", {})
        if not judge.get("model") or judge.get("model") == (report.get("subject") or {}).get("model"):
            errors.append(name + ":independent_judge_required")
        rows_valid = True
        for row in rows:
            prefix = name + ":" + str(row.get("id"))
            if not _score_valid(row, report):
                errors.append(prefix + ":missing_or_invalid_score")
            structure = row.get("structure", {})
            if (any(type(structure.get(key)) is not bool for key in STRUCTURE_FLAGS)
                    or not all(_number(structure.get(key)) for key in ("tokens", "rounds", "tool_error_rate"))
                    or not _number(row.get("elapsed_seconds")) or not row.get("group")):
                errors.append(prefix + ":invalid_structure")
                rows_valid = False
            turns = row.get("turns", [])
            if not turns or any(not isinstance(turn.get("terminal"), dict) or turn["terminal"].get("type") not in
                   {"done", "error", "cancelled"} for turn in turns):
                errors.append(prefix + ":invalid_terminal")
            if structure.get("single_terminal_per_turn") is True and any(turn.get("terminal_count") != 1 for turn in turns):
                errors.append(prefix + ":terminal_count_mismatch")
        if rows_valid and rows:
            derived = summarize(rows)
            if report.get("groups") != derived:
                errors.append(name + ":group_summary_does_not_match_rows")
    if identities[0] != identities[1]:
        errors.append("case_id_sets_differ")
    elif {row["id"]: row.get("group") for row in baseline.get("results", [])} != {
            row["id"]: row.get("group") for row in current.get("results", [])}:
        errors.append("case_group_bindings_differ")
    return errors


def _budget_reasons(terminal):
    reasons = []
    if terminal.get("error_code") in BUDGET_ERRORS:
        reasons.append(terminal["error_code"])
    stopped = (terminal.get("metrics") or {}).get("stopped")
    if stopped in BUDGET_STOPS:
        reasons.append(stopped)
    review = (terminal.get("quality") or {}).get("review") or {}
    if review.get("error_code") == "review_timeout":
        reasons.append("review_timeout")
    return reasons


def _valid_delivery(row):
    structure, score = row.get("structure", {}), row.get("score") or {}
    if (score.get("answered") != 2 or score.get("numbers") != 2 or score.get("no_internal_identifiers") != 1
            or any(structure.get(key) is not True for key in STRUCTURE_FLAGS if key != "completed")):
        return False
    turns = row.get("turns", [])
    return bool(turns) and all(turn.get("terminal_count") == 1
        and isinstance(turn["terminal"].get("response"), str) and bool(turn["terminal"]["response"].strip())
        and turn["terminal"].get("answer_status") != "unavailable" for turn in turns)


def _resource_observation(row, config, policy):
    turns = row.get("turns", [])
    timeout = config.get("timeout_seconds")
    token_limit = (config.get("model_quotas") or {}).get("run_token_budget")
    tokens = [(turn.get("terminal", {}).get("metrics") or {}).get("total_tokens") for turn in turns]
    complete = (bool(turns) and _number(timeout) and timeout > 0 and _number(token_limit) and token_limit > 0
                and all(_number(value) for value in tokens))
    time_ratio = row["elapsed_seconds"] / (timeout * len(turns)) if complete else None
    token_ratios = [value / token_limit for value in tokens] if complete else []
    return {"measurement_complete": complete, "time_scope": "case_aggregate_only",
            "elapsed_seconds": row["elapsed_seconds"], "turn_count": len(turns),
            "per_turn_time_budget_seconds": timeout, "case_time_ratio": time_ratio,
            "per_turn_token_budget": token_limit, "per_turn_tokens": tokens, "per_turn_token_ratios": token_ratios,
            "within_tolerance": bool(complete and time_ratio <= 1 + policy.max_overrun_ratio
                                      and all(ratio <= 1 + policy.max_overrun_ratio for ratio in token_ratios))}


def _classify(row, config, policy):
    turns, outcomes = row.get("turns", []), row.get("model_call_outcomes", [])
    reasons = [_budget_reasons(turn.get("terminal", {})) for turn in turns]
    resources = _resource_observation(row, config, policy)
    valid = _valid_delivery(row)
    eligible = bool(valid and resources["within_tolerance"])
    counts = [turn.get("model_calls") for turn in turns]
    mapped = (all(type(count) is int and count >= 0 for count in counts) and sum(counts) == len(outcomes))
    ignored, uncertain, attribution, non_budget = [], [], [], []
    offset = 0
    if mapped:
        for turn_index, (turn, count) in enumerate(zip(turns, counts)):
            for index in range(offset, offset + count):
                outcome = outcomes[index]
                if outcome.get("status") not in FAILURE_STATUSES:
                    continue
                explicit = outcome.get("error_code") in BUDGET_ERRORS
                stopped = (turn["terminal"].get("metrics") or {}).get("stopped")
                final_budget_cancel = (outcome.get("status") == "cancelled" and outcome.get("error_code") is None
                    and index == offset + count - 1
                    and (stopped in DEADLINE_STOPS or "review_timeout" in reasons[turn_index])
                    and turn["terminal"].get("type") != "cancelled")
                if eligible and (explicit or final_budget_cancel):
                    ignored.append(index)
                    attribution.append({"outcome_index": index, "turn_index": turn_index,
                        "status": outcome["status"], "reason": outcome.get("error_code") if explicit else
                        stopped if stopped in DEADLINE_STOPS else "review_timeout"})
                elif outcome.get("status") == "cancelled" or outcome.get("error_code") == "model_timeout":
                    uncertain.append(index)
                else:
                    non_budget.append(index)
            offset += count
    else:
        uncertain = [index for index, outcome in enumerate(outcomes) if outcome.get("status") in FAILURE_STATUSES
                     and (outcome.get("status") == "cancelled" or outcome.get("error_code") in
                          BUDGET_ERRORS | {"model_timeout"})]
        non_budget = [index for index, outcome in enumerate(outcomes) if outcome.get("status") == "failed"
                      and outcome.get("error_code") not in BUDGET_ERRORS | {"model_timeout"}]
    accepted_terminal = eligible and not row["structure"]["completed"] and all(
        turn["terminal"].get("type") == "done" or (turn["terminal"].get("type") == "error"
        and turn["terminal"].get("error_code") in BUDGET_ERRORS) for turn in turns)
    transport_uncertain, transport_failures = [], []
    for error in row.get("transport_errors", []):
        code = error.get("code")
        if code == "model_timeout":
            transport_uncertain.append(code)
        elif code not in BUDGET_ERRORS:
            transport_failures.append(code or "unknown_transport_error")
    review_reasons = []
    if uncertain or transport_uncertain:
        review_reasons.append("budget_attribution_uncertain")
    if any(reasons) and not resources["measurement_complete"]:
        review_reasons.append("resource_measurement_incomplete")
    elif resources["measurement_complete"] and not resources["within_tolerance"]:
        review_reasons.append("resource_variation_above_automatic_reference")
    return {"case_id": row["id"], "group": row["group"], "valid_delivery": valid,
            "budget_reasons_by_turn": reasons, "resources": resources,
            "raw_completed": row["structure"]["completed"], "accepted_budget_terminal": accepted_terminal,
            "ignored_budget_outcome_indices": ignored, "budget_attributions": attribution,
            "operational_uncertain": uncertain, "requires_operational_review": bool(uncertain or transport_uncertain),
            "uncertain_transport_error_codes": transport_uncertain, "non_budget_transport_error_codes": transport_failures,
            "resource_review_reasons": review_reasons, "non_budget_failure_indices": non_budget,
            "model_outcomes_mapped_to_turns": mapped,
            "raw_failed_model_calls": sum(outcome.get("status") in FAILURE_STATUSES for outcome in outcomes)}


def _project(report, policy):
    projected, audits, grouped = deepcopy(report), [], defaultdict(list)
    for row in report["results"]:
        audit = _classify(row, report.get("harness_config") or {}, policy)
        audits.append(audit)
        grouped[row["group"]].append((row, audit))
    metrics = {}
    for group, rows in grouped.items():
        calls = sum(len(row.get("model_call_outcomes", [])) for row, _ in rows)
        failures = sum(audit["raw_failed_model_calls"] for _, audit in rows)
        ignored = sum(len(audit["ignored_budget_outcome_indices"]) for _, audit in rows)
        raw_completed = sum(row["structure"]["completed"] and row["structure"]["single_terminal_per_turn"] for row, _ in rows)
        tolerated = sum(audit["accepted_budget_terminal"] for _, audit in rows)
        projected["groups"][group]["completed_rate"] = (raw_completed + tolerated) / len(rows)
        projected["groups"][group]["failed_model_calls"] = failures - ignored
        projected["groups"][group]["model_failure_rate"] = (failures - ignored) / calls if calls else 0.0
        metrics[group] = {"cases": len(rows), "model_calls": calls, "raw_completed_cases": raw_completed,
                         "accepted_budget_terminal_cases": tolerated, "accepted_delivery_cases": raw_completed + tolerated,
                         "raw_failed_model_calls": failures, "ignored_budget_model_calls": ignored,
                         "adjusted_failed_model_calls": failures - ignored}
    return projected, audits, metrics


def evaluate_acceptance(baseline: dict, current: dict, policy: ResourcePolicy | None = None, *, input_identities=None) -> dict:
    """只在深拷贝分组指标上比较；模型结果、答案和评分完全不改。"""
    policy = policy or ResourcePolicy()
    strict = compare(baseline, current)
    errors = _integrity_errors(baseline, current, policy)
    result = {"schema_version": 1, "policy": asdict(policy),
              "policy_basis": "用户允许合理预算波动；25%是明确记录的独立验收默认值，不增加实际预算或费用。",
              "implementation_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "inputs": input_identities or {name: {"sha256": _digest(report), "kind": "canonical_json"}
                                             for name, report in (("baseline", baseline), ("current", current))},
              "raw_strict_comparison": strict, "passed": False, "integrity_errors": errors,
              "adjusted_metrics": {}, "case_audits": {}, "ignored_resource_regressions": [],
              "operational_uncertain": [], "original_reports_modified": False}
    if errors:
        result["status"] = "incomplete_or_invalid_inputs"
        return result
    before, baseline_audits, baseline_metrics = _project(baseline, policy)
    after, current_audits, current_metrics = _project(current, policy)
    adjusted = compare(before, after)
    ignored = sorted(set(strict.get("regressions", [])) - set(adjusted.get("regressions", [])))
    operational_regressions = [value for value in adjusted.get("regressions", [])
                              if value.rsplit(":", 1)[-1] in {"completed_rate", "model_failure_rate", "median_seconds"}]
    quality_regressions = [value for value in adjusted.get("regressions", []) if value not in operational_regressions]
    critical_budget_deliveries = [audit["case_id"] for audit in current_audits
                                 if any(audit["budget_reasons_by_turn"]) and not audit["valid_delivery"]]
    non_budget_failures = [audit["case_id"] for audit in current_audits
                          if audit["non_budget_failure_indices"] or audit["non_budget_transport_error_codes"]]
    reviews = [{"case_id": audit["case_id"], "reasons": audit["resource_review_reasons"]}
               for audit in current_audits if audit["resource_review_reasons"]]
    hard_failure = bool(quality_regressions or adjusted.get("reason") or critical_budget_deliveries or non_budget_failures)
    manual = bool(not hard_failure and (operational_regressions or reviews))
    status = "rejected" if hard_failure else "needs_review" if manual else "accepted"
    result.update(passed=status == "accepted", status=status,
        acceptance_comparison=adjusted, ignored_resource_regressions=ignored,
        quality_regressions=quality_regressions, unresolved_operational_regressions=operational_regressions,
        critical_budget_delivery_cases=critical_budget_deliveries, non_budget_protocol_failure_cases=non_budget_failures,
        resource_reviews=reviews, requires_manual_review=manual,
        adjusted_metrics={"baseline": baseline_metrics, "current": current_metrics},
        case_audits={"baseline": baseline_audits, "current": current_audits},
        operational_uncertain=[{"runtime": name, "case_id": audit["case_id"],
                                "outcome_indices": audit["operational_uncertain"],
                                **({"transport_error_codes": audit["uncertain_transport_error_codes"]}
                                   if audit["uncertain_transport_error_codes"] else {})}
            for name, audits in (("baseline", baseline_audits), ("current", current_audits))
            for audit in audits if audit["requires_operational_review"]])
    return result


def evaluate_files(baseline_path: str | Path, current_path: str | Path, policy: ResourcePolicy | None = None) -> dict:
    """读取不可变报告原件；SHA按原始文件字节计算，不写任何文件。"""
    paths = {"baseline": Path(baseline_path), "current": Path(current_path)}
    raw = {name: path.read_bytes() for name, path in paths.items()}
    identities = {name: {"path": str(paths[name]), "sha256": hashlib.sha256(value).hexdigest(), "kind": "file_bytes"}
                  for name, value in raw.items()}
    return evaluate_acceptance(json.loads(raw["baseline"]), json.loads(raw["current"]), policy,
                               input_identities=identities)

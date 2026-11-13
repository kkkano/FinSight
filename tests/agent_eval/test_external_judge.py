"""外部判分完整性、冻结输入与部分导入合同；不调用模型或 HTTP。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from . import run as runner
from .external_judge import ExternalJudgmentError, checksum, import_judgment, request_document, write_request
from .scoring import EXTERNAL_JUDGE, compare, judge_metadata, judge_prompt, summarize
from .tapes import ToolTape, canonical_json


SCORE = {"answered": 2, "numbers": 2, "limitations": 1, "presentation": 1,
         "no_internal_identifiers": 1, "reasons": ["已逐条核对完整录制。"]}


@pytest.fixture
def external_batch(tmp_path_factory):
    def create(count=2, faults=None):
        eval_dir = tmp_path_factory.mktemp("ej") / "w" / "tests" / "agent_eval"
        eval_dir.mkdir(parents=True, exist_ok=True)
        fixtures = eval_dir / "fixtures"
        rows, cases, recordings = [], [], {}
        for index in range(count):
            case = {"id": "external-" + str(index + 1), "group": "facts", "turns": ["完整问题"],
                    "must": ["说明录制数字"], "must_not": ["编造来源"], "expects": {}}
            if faults:
                case["tool_faults"] = deepcopy(faults)
            tape = ToolTape(fixtures / case["id"], "record")
            tape.invoke("fixture_tool", {"ticker": "AAPL"}, lambda _args: {"status": "ok", "kind": "table",
                "data": [{"value": 1}, {"value": 2}], "sources": [{"title": "完整来源"}]})
            if faults:
                tape = ToolTape(fixtures / case["id"], "record", faults=faults)
                tape.invoke("fixture_tool", {"ticker": "AAPL"}, lambda _args: None)
            row = {"id": case["id"], "group": "facts", "model": "fixture-subject", "score": None,
                   "elapsed_seconds": 1, "tape": {"misses": 0}, "transport_errors": [],
                   "model_call_outcomes": [{"model": "fixture-subject", "status": "completed", "received_chunks": 1,
                                            "synthetic": True}],
                   "turns": [{"run_id": "original-run-" + str(index), "query": "完整问题",
                              "terminal_count": 1, "model_calls": 1,
                              "terminal": {"type": "done", "response": "原始交付：1。", "artifacts": [],
                                           "evidence_pool": [{"source_id": 1, "title": "完整来源"}]}}],
                   "structure": {"completed": True, "references_valid": True, "artifacts_met": True,
                                 "no_actions_met": True, "single_terminal_per_turn": True,
                                 "tokens": 5, "rounds": 1, "tool_error_rate": 0},
                   "external_judge_verified": False}
            recordings[case["id"]] = tape.records()
            row["external_judge"] = write_request(case, row, tape.records(), eval_dir, "fixture-run")
            rows.append(row)
            cases.append(case)
        corpus = {"cases": cases}
        runner.write_json(eval_dir / "cases.json", corpus)
        report = {"run_id": "fixture-run", "mode": "replay", "judge": deepcopy(EXTERNAL_JUDGE),
                  "judge_prompt_sha256": hashlib.sha256(judge_prompt("external").encode()).hexdigest(),
                  "cases_sha256": hashlib.sha256((eval_dir / "cases.json").read_bytes()).hexdigest(),
                  "fixtures_root": "fixtures",
                  "fixtures_sha256": runner.digest_files(list(fixtures.rglob("*.json")), fixtures),
                  "harness_config": {"jobs": 4, "request_interval_seconds": 6.1},
                  "expected_cases": count, "ready": False, "groups": {}, "results": rows}
        source, output, judgments = eval_dir / "source.json", eval_dir / "graded.json", eval_dir / "judgments"
        runner.write_json(source, report)
        judgments.mkdir()
        return SimpleNamespace(eval_dir=eval_dir, cases=cases, rows=rows, recordings=recordings,
                               corpus=corpus, report=report, source=source, output=output,
                               judgments=judgments, judge=SimpleNamespace(**EXTERNAL_JUDGE))
    return create


def score_file(batch, index=0, score=None):
    row = batch.rows[index]
    payload = {"request_sha256": row["external_judge"]["request_sha256"], "judge": deepcopy(EXTERNAL_JUDGE),
               "score": deepcopy(SCORE if score is None else score)}
    path = batch.judgments / (row["id"] + ".json")
    runner.write_json(path, payload)
    return path, payload


def test_request_keeps_complete_inputs_and_honest_native_metadata(external_batch):
    batch = external_batch(1)
    row, case = batch.rows[0], batch.cases[0]
    ref = row["external_judge"]
    path = batch.eval_dir.parent.parent / ref["request_path"]
    request = json.loads(path.read_text(encoding="utf-8"))
    assert ref["request_sha256"] == hashlib.sha256(canonical_json(request).encode()).hexdigest()
    assert request["input"] == {"case": case, "answers": row["turns"], "recordings": batch.recordings[row["id"]]}
    assert request["bindings"]["case_sha256"] == checksum(case)
    assert request["bindings"]["answers_sha256"] == checksum(row["turns"])
    assert request["judge"] == EXTERNAL_JUDGE
    assert request["judge"]["context_window"] is None and request["judge"]["max_output"] is None
    assert "reasons" in request["response_schema"]["$defs"]["ContentScore"]["required"]
    assert row["score"] is None and row["external_judge_verified"] is False


def test_request_cannot_be_overwritten_with_different_delivery(external_batch):
    batch = external_batch(1)
    batch.rows[0]["turns"][0]["terminal"]["response"] = "不同交付"
    with pytest.raises(ExternalJudgmentError, match="^external_judge_request_already_exists$"):
        write_request(batch.cases[0], batch.rows[0], batch.recordings[batch.rows[0]["id"]], batch.eval_dir, "fixture-run")


def test_same_model_is_rejected_before_external_request_is_written(external_batch):
    batch = external_batch(1)
    batch.rows[0]["model"] = EXTERNAL_JUDGE["model"]
    with pytest.raises(ExternalJudgmentError, match="^judge_must_differ_from_subject$"):
        request_document(batch.cases[0], batch.rows[0], [])


@pytest.mark.parametrize("changed", ["case", "answers", "recordings", "prompt", "judge", "bindings"])
def test_import_rejects_changed_request_inputs_and_bindings(external_batch, changed):
    batch = external_batch(1)
    row, case = batch.rows[0], batch.cases[0]
    score_file(batch)
    path = batch.eval_dir.parent.parent / row["external_judge"]["request_path"]
    request = json.loads(path.read_text(encoding="utf-8"))
    if changed in {"case", "answers", "recordings"}:
        request["input"][changed] = {} if changed == "case" else []
    elif changed == "prompt":
        request["prompt"] = "不同提示"
    elif changed == "judge":
        request["judge"]["role"] = "executor"
    else:
        request["bindings"]["case_sha256"] = "0" * 64
    runner.write_json(path, request)
    with pytest.raises(ExternalJudgmentError, match="^external_judge_request_mismatch$"):
        import_judgment(case, row, batch.recordings[row["id"]], batch.eval_dir, batch.judgments)


@pytest.mark.parametrize("changed", ["case", "answer", "recordings", "reference"])
def test_import_rejects_report_or_current_data_disagreeing_with_request(external_batch, changed):
    batch = external_batch(1)
    row, case = batch.rows[0], batch.cases[0]
    score_file(batch)
    records = deepcopy(batch.recordings[row["id"]])
    if changed == "case":
        case["must"].append("新的要求")
    elif changed == "answer":
        row["turns"][0]["terminal"]["response"] = "新的回答"
    elif changed == "recordings":
        records[0]["raw_output"]["data"][0]["value"] = 999
    else:
        row["external_judge"]["request_sha256"] = "0" * 64
    with pytest.raises(ExternalJudgmentError, match="^external_judge_request_mismatch$"):
        import_judgment(case, row, records, batch.eval_dir, batch.judgments)


@pytest.mark.parametrize("changed", ["stale", "extra", "identity", "budget", "score_extra", "score_bool", "score_missing"])
def test_import_rejects_stale_or_invalid_external_judgments(external_batch, changed):
    batch = external_batch(1)
    row, case = batch.rows[0], batch.cases[0]
    path, value = score_file(batch)
    if changed == "stale":
        value["request_sha256"] = "0" * 64
    elif changed == "extra":
        value["extra"] = True
    elif changed == "identity":
        value["judge"]["provider"] = "unknown"
    elif changed == "budget":
        value["judge"]["max_output"] = 8192
    elif changed == "score_extra":
        value["score"]["total"] = 7
    elif changed == "score_bool":
        value["score"]["answered"] = True
    else:
        value["score"].pop("numbers")
    runner.write_json(path, value)
    with pytest.raises(ExternalJudgmentError, match="^external_judgment_(invalid|mismatch)$"):
        import_judgment(case, row, batch.recordings[row["id"]], batch.eval_dir, batch.judgments)


@pytest.mark.asyncio
async def test_partial_import_stays_unready_and_full_import_does_not_use_http(external_batch, monkeypatch):
    batch = external_batch()
    score_file(batch, 0)

    def forbidden_http(*_args, **_kwargs):
        raise AssertionError("原生外部判分导入不得构造 HTTP client")

    monkeypatch.setattr(httpx, "AsyncClient", forbidden_http)
    assert await runner.grade_report(batch.source, batch.output, batch.corpus, batch.judge, batch.eval_dir,
                                    judge_protocol="external", external_judgments_dir=batch.judgments) == 2
    partial = json.loads(batch.output.read_text(encoding="utf-8"))
    assert partial["groups"]["facts"]["judged"] == 1 and partial["ready"] is False
    assert partial["results"][1]["score"] is None
    assert partial["results"][1]["judge_error"] == "external_judgment_missing"
    previous = deepcopy(partial["results"][0]["score"])
    score_file(batch, 1)
    assert await runner.grade_report(batch.output, batch.source, batch.corpus, batch.judge, batch.eval_dir,
                                    judge_protocol="external", external_judgments_dir=batch.judgments) == 0
    complete = json.loads(batch.source.read_text(encoding="utf-8"))
    assert complete["ready"] is True and complete["groups"]["facts"]["judged"] == 2
    assert complete["results"][0]["score"] == previous
    assert complete["judge"] == batch.report["judge"]
    assert complete["fixtures_sha256"] == batch.report["fixtures_sha256"]
    assert compare(complete, complete)["passed"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("valid_file", [False, True])
async def test_claimed_existing_score_requires_matching_external_proof(external_batch, valid_file):
    batch = external_batch(1)
    row = batch.rows[0]
    row["score"] = {**SCORE, "total": 7, "model": EXTERNAL_JUDGE["model"],
                    "request_sha256": row["external_judge"]["request_sha256"]}
    row["external_judge_verified"] = True
    batch.report["ready"] = True
    runner.write_json(batch.source, batch.report)
    if valid_file:
        score_file(batch, score={**SCORE, "answered": 0})
    assert await runner.grade_report(batch.source, batch.output, batch.corpus, batch.judge, batch.eval_dir,
                                    judge_protocol="external", external_judgments_dir=batch.judgments) == 2
    rejected = json.loads(batch.output.read_text(encoding="utf-8"))
    assert rejected["ready"] is False and rejected["groups"]["facts"]["judged"] == 0
    assert rejected["results"][0]["external_judge_verified"] is False
    assert rejected["results"][0]["judge_error"] == (
        "external_judgment_existing_score_mismatch" if valid_file else "external_judgment_missing")


@pytest.mark.parametrize("status", ["error", "empty"])
def test_frozen_fault_overlay_is_restored_from_bound_snapshot(external_batch, status):
    batch = external_batch(1, {"fixture_tool": {"status": status, "code": "provider_timeout"}})
    row, case = batch.rows[0], batch.cases[0]
    score_file(batch)
    current = ToolTape(batch.eval_dir / "fixtures" / row["id"], "replay", faults=case["tool_faults"]).records()
    assert current[0]["injected"] is False and batch.recordings[row["id"]][0]["injected"] is True
    accepted = import_judgment(case, row, current, batch.eval_dir, batch.judgments)
    assert accepted["total"] == 7


def test_fault_overlay_must_match_current_declared_fault(external_batch):
    batch = external_batch(1, {"fixture_tool": {"status": "error", "code": "provider_timeout"}})
    row, case = batch.rows[0], batch.cases[0]
    case["tool_faults"]["fixture_tool"]["code"] = "another_code"
    with pytest.raises(ExternalJudgmentError, match="^external_judge_injected_record_mismatch$"):
        import_judgment(case, row, [], batch.eval_dir, batch.judgments)


@pytest.mark.parametrize("faults", [None, {"fixture_tool": {"status": "error", "code": "provider_timeout"}}])
def test_late_record_does_not_change_bound_scoring_input(external_batch, faults):
    batch = external_batch(1, faults)
    row, case = batch.rows[0], batch.cases[0]
    score_file(batch)
    request_path = batch.eval_dir.parent.parent / row["external_judge"]["request_path"]
    original = request_path.read_bytes()
    tape = ToolTape(batch.eval_dir / "fixtures" / row["id"], "record")
    tape.invoke("late_fixture_tool", {}, lambda _: {"status": "ok", "value": 999, "synthetic": True})
    current = tape.records()
    assert len(current) == 2
    accepted = import_judgment(case, row, current, batch.eval_dir, batch.judgments)
    assert accepted["total"] == 7
    assert request_path.read_bytes() == original
    assert all(record["tool"] != "late_fixture_tool" for record in json.loads(original)["input"]["recordings"])


def test_bound_record_cannot_disappear_from_final_library(external_batch):
    batch = external_batch(1)
    score_file(batch)
    with pytest.raises(ExternalJudgmentError, match="^external_judge_request_mismatch$"):
        import_judgment(batch.cases[0], batch.rows[0], [], batch.eval_dir, batch.judgments)


def test_unverified_external_score_is_not_counted_in_group_table(external_batch):
    batch = external_batch(1)
    batch.rows[0]["score"] = {**SCORE, "total": 7}
    assert summarize(batch.rows)["facts"]["judged"] == 0
    assert runner.report_ready(batch.report) is False


def test_external_judge_metadata_rejects_invented_api_budgets():
    metadata = judge_metadata(SimpleNamespace(**EXTERNAL_JUDGE), "external")
    assert metadata == EXTERNAL_JUDGE
    invalid = SimpleNamespace(**{**EXTERNAL_JUDGE, "context_window": 131072})
    with pytest.raises(ValueError, match="^external_judge_identity_invalid$"):
        judge_metadata(invalid, "external")

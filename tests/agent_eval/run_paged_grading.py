"""统一完整证据分页评分；不改测量报告、原模型回答、资料或研究耗时。"""
import argparse
import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))
from agent_eval import run as runner
from agent_eval.scoring import summarize
from agent_eval.tapes import ToolTape
from backend.agent_runtime.config import ModelConfig


def sibling(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


paged = sibling("paged_judge")
budgeted = sibling("grade_apikl_budgeted")
frozen_module = sibling("frozen_corpus_provider")


async def main(args):
    source, output = Path(args.source).resolve(), Path(args.output).resolve()
    if output.exists() and not args.resume:
        raise ValueError("existing_paged_grading_requires_resume")
    original = json.loads(source.read_text(encoding="utf-8"))
    if not args.trial and (original.get("mode") != "replay" or len(original.get("results", [])) != 60):
        raise ValueError("formal_grading_requires_full_replay")
    if args.case and not args.trial:
        raise ValueError("partial_case_selection_is_trial_only")
    case_path = ROOT / "tests/agent_eval/cases.json"
    if original["cases_sha256"] != hashlib.sha256(case_path.read_bytes()).hexdigest():
        raise ValueError("measurement_case_dataset_changed")
    cases = {case["id"]: case for case in json.loads(case_path.read_text(encoding="utf-8"))["cases"]}
    fixture_base = ROOT / "tests/agent_eval" / original["fixtures_root"]
    current_digest = runner.digest_files(list(fixture_base.rglob("*.json")), fixture_base)
    if not args.trial and current_digest != original["fixtures_sha256"]:
        raise ValueError("frozen_common_evidence_changed")
    settings = dotenv_values(ROOT / ".env.runtime.local")
    declared = original["judge"]
    config = ModelConfig(declared["model"], declared["base_url"], settings["FINSIGHT_EVAL_APIKL_API_KEY"],
                         context_window=declared["context_window"], max_output=declared["max_output"])
    if config.model != "gpt-6.1-sol" or config.base_url != settings["FINSIGHT_EVAL_APIKL_API_BASE"]:
        raise ValueError("independent_judge_configuration_changed")
    prompt_hash = paged.digest({"reading": paged.READ_SYSTEM, "final": paged.FINAL_SYSTEM,
                               "read_tool": paged.READ_TOOL, "finish_tool": paged.FINISH_TOOL, "score_tool": paged.SCORE_TOOL,
                               "corpus_tool": paged.CORPUS_TOOL})
    shared_corpus = None
    if original.get("harness_config", {}).get("frozen_provider"):
        shared_corpus = frozen_module.FrozenCorpus(fixture_base)
        if shared_corpus.identity != original["harness_config"]["frozen_provider"]["manifest_sha256"]:
            raise ValueError("measurement_shared_corpus_changed")
    implementation = {"kind": "complete_evidence_readonly_paged_native_judge", "version": 1,
        "reader": Path(paged.__file__).relative_to(ROOT).as_posix(),
        "reader_sha256": hashlib.sha256(Path(paged.__file__).read_bytes()).hexdigest(),
        "transport": Path(budgeted.__file__).relative_to(ROOT).as_posix(),
        "transport_sha256": hashlib.sha256(Path(budgeted.__file__).read_bytes()).hexdigest(),
        "model": config.model, "native_submit_tool": "submit_score", "prompt_sha256": prompt_hash,
        "shared_account_quota": str(Path(args.shared_quota).resolve()), "rpm": 30, "tpm": 250000,
        "minimum_request_interval_seconds": 10, "case_reading_token_budget": 600000,
        "context_window": config.context_window, "max_output": config.max_output,
        "artifact_root": str(runner.evaluation_artifact_root()),
        "original_subject_measurements_changed": False, "evidence_keyword_selection": False}
    report = deepcopy(original)
    if args.trial:
        report["results"] = [row for row in report["results"] if not args.case or row["id"] in args.case]
        if args.case and len(report["results"]) != len(set(args.case)):
            raise ValueError("unknown_trial_case")
        report["expected_cases"] = len(report["results"])
    if args.resume:
        report = json.loads(output.read_text(encoding="utf-8"))
        if report.get("judge_prompt_sha256") != prompt_hash or report.get("judge_execution") != implementation:
            raise ValueError("paged_judge_implementation_changed_requires_new_batch")
        archive = output.with_name(output.stem + "_before_resume_" + hashlib.sha256(output.read_bytes()).hexdigest()[:12] + ".json")
        if not archive.exists():
            archive.write_bytes(output.read_bytes())
    report.update(graded_from=str(source), raw_measurement_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                  judge_prompt_sha256=prompt_hash, judge_execution=implementation,
                  trial=args.trial, actual_fixture_sha256_at_grading=current_digest,
                  graded_at=datetime.now(timezone.utc).isoformat())
    attempts = []
    transport = budgeted.quota_transport_class(Path(args.shared_quota).resolve(), attempts)(config)
    environment = {"FINSIGHT_AGENT_MODEL_CONCURRENCY": "2", "FINSIGHT_AGENT_RPM_LIMIT": "30",
        "FINSIGHT_AGENT_TPM_LIMIT": "250000", "FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS": "10",
        "FINSIGHT_AGENT_TOKEN_BUDGET": "160000"}
    with patch.dict(os.environ, environment):
        for row in report["results"]:
            if row.get("score") is not None:
                continue
            case = cases[row["id"]]
            if shared_corpus is not None:
                reference = row["frozen_provider"]
                path = runner.resolve_evaluation_file(reference["actual_calls_path"])
                if reference.get("actual_calls_sha256") is None:
                    records = []
                elif hashlib.sha256(path.read_bytes()).hexdigest() != reference["actual_calls_sha256"]:
                    raise ValueError("measurement_actual_call_sources_changed")
                else:
                    records = json.loads(path.read_text(encoding="utf-8"))
            else:
                records = ToolTape(fixture_base / case["id"], "replay", faults=case.get("tool_faults")).records()
            work = (runner.evaluation_artifact_root() / "_paged_judge" if os.getenv("FINSIGHT_EVAL_ARTIFACT_ROOT")
                    else ROOT / "tests/agent_eval/requests/paged_judge") / output.stem / case["id"]
            before = len(attempts)
            if row.get("judge_error"):
                row.setdefault("previous_judge_errors", []).append({"error": row["judge_error"], "details": row.get("judge_details")})
            try:
                row["score"] = await paged.judge_with_pages(transport, case, row, records, work, corpus=shared_corpus)
                row.pop("judge_error", None)
                row.pop("judge_details", None)
            except Exception as exc:
                row["score"] = None
                row["judge_error"] = getattr(exc, "code", str(exc))[:250].replace(config.api_key, "[REDACTED]")
                row["judge_details"] = {"exception_type": type(exc).__name__, "source_data_retained": True}
            row["paged_judge_artifacts"] = runner.evaluation_file_reference(work)
            row["judge_transport_attempts"] = deepcopy(attempts[before:])
            report["groups"] = summarize(report["results"])
            report["ready"] = False if args.trial else runner.report_ready(report)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            print(json.dumps({"case": row["id"], "score": row.get("score", {}).get("total") if row.get("score") else None,
                              "reading_rounds": row.get("score", {}).get("reading_rounds") if row.get("score") else None,
                              "judge_error": row.get("judge_error")}, ensure_ascii=False), flush=True)
    return 0 if (args.trial and all(row.get("score") for row in report["results"])) or report.get("ready") else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--shared-quota", required=True)
    parser.add_argument("--trial", action="store_true")
    parser.add_argument("--case", action="append")
    parser.add_argument("--resume", action="store_true", help="只补失败项，成功评分不重跑；原失败输出保留")
    raise SystemExit(asyncio.run(main(parser.parse_args())))

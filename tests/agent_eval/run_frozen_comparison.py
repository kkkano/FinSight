"""同冻结资料双方评测与统一分页评分；阶段独立留证，任何不通过均原样报告。"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
RESULTS = ROOT / "tests/agent_eval/results"
SUFFIX = "20261113_isolated"
CORPUS = "fixtures/apikl-frozen-provider-20261113"
PILOT_CASES = ["facts-02", "news-01", "statistics-01", "comparison-01", "concepts-01"]


def report_path(runtime, *, pilot=False, graded=False):
    qualifier = "pilot" if pilot else "paged" if graded else "replay"
    return RESULTS / f"m3_apikl_frozen_{runtime}_{qualifier}_{SUFFIX}.json"


def environment():
    values = dotenv_values(ROOT / ".env.runtime.local")
    env = dict(os.environ)
    env.update({key: value for key, value in values.items() if value is not None})
    env.update(PYTHONIOENCODING="utf-8", FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS="10",
        FINSIGHT_EVAL_JUDGE_MODEL="gpt-6.1-sol",
        FINSIGHT_EVAL_JUDGE_API_BASE=values["FINSIGHT_EVAL_APIKL_API_BASE"],
        FINSIGHT_EVAL_JUDGE_API_KEY=values["FINSIGHT_EVAL_APIKL_API_KEY"],
        FINSIGHT_EVAL_JUDGE_CONTEXT_WINDOW="131072", FINSIGHT_EVAL_JUDGE_MAX_OUTPUT="8192")
    return env


def implementation():
    names = ["run_frozen_comparison.py", "run_frozen_eval.py", "frozen_corpus_provider.py",
             "frozen_offline_worker.py", "materialize.py", "run_paged_grading.py",
             "paged_judge.py", "grade_apikl_budgeted.py"]
    return {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in names}


def save(path, state):
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main(args):
    state_path = RESULTS / f"apikl_frozen_{args.phase}_execution_{SUFFIX}.json"
    binding = implementation()
    if state_path.exists():
        if not args.resume:
            raise ValueError("existing_comparison_phase_requires_review_and_resume")
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state["implementation"] != binding:
            raise ValueError("implementation_changed_requires_new_measurement_generation")
    else:
        state = {"phase": args.phase, "status": "started", "pid": os.getpid(),
                 "implementation": binding, "stages": []}
    save(state_path, state)
    commands = []
    if args.phase in {"pilot", "full"}:
        if args.phase == "full":
            for runtime in ("current", "baseline"):
                pilot = json.loads(report_path(runtime, pilot=True).read_text(encoding="utf-8"))
                if len(pilot["results"]) != len(PILOT_CASES):
                    raise ValueError("complete_both_pilots_required_before_full_measurement")
                if pilot["harness_config"]["frozen_provider"]["driver_source_sha256"] != binding["run_frozen_eval.py"]:
                    raise ValueError("pilot_driver_changed")
        for runtime in ("current", "baseline"):
            command = [sys.executable, "-B", "-X", "utf8", "tests/agent_eval/run_frozen_eval.py",
                "--provider", "apikl", "--runtime", runtime, "--mode", "replay", "--jobs", "2",
                "--request-interval", "6.1", "--timeout", "180", "--model-protocol", "sse",
                "--no-judge", "--judge-protocol", "tools", "--fixtures-root", CORPUS,
                "--output", str(report_path(runtime, pilot=args.phase == "pilot"))]
            if args.phase == "pilot":
                for case in PILOT_CASES:
                    command += ["--case", case]
            commands.append((runtime, command))
    elif args.phase == "grade":
        for runtime in ("current", "baseline"):
            command = [sys.executable, "-B", "-X", "utf8", "tests/agent_eval/run_paged_grading.py",
                "--source", str(report_path(runtime)), "--output", str(report_path(runtime, graded=True)),
                "--shared-quota", str(ROOT / "tmp/r261113/shared_judge_quota.sqlite")]
            if args.resume and report_path(runtime, graded=True).exists():
                command += ["--resume"]
            commands.append((runtime, command))
    else:
        sys.path.insert(0, str(ROOT / "tests"))
        from agent_eval.scoring import compare
        baseline = json.loads(report_path("baseline", graded=True).read_text(encoding="utf-8"))
        current = json.loads(report_path("current", graded=True).read_text(encoding="utf-8"))
        comparison = compare(baseline, current)
        state.update(status="passed" if comparison["passed"] else "failed", comparison=comparison,
            baseline_sha256=hashlib.sha256(report_path("baseline", graded=True).read_bytes()).hexdigest(),
            current_sha256=hashlib.sha256(report_path("current", graded=True).read_bytes()).hexdigest())
        save(state_path, state)
        print(json.dumps(comparison, ensure_ascii=False), flush=True)
        return 0 if comparison["passed"] else 2
    env = environment()
    for name, command in commands:
        previous = next((stage for stage in reversed(state["stages"]) if stage["name"] == name), None)
        if previous and previous["status"] == "collected":
            continue
        if previous and args.phase != "grade":
            raise ValueError("incomplete_generation_requires_review_without_overwriting_partial_measurement")
        stage = {"name": name, "status": "running", "safe_command": command}
        state["stages"].append(stage)
        state.update(status=name, pid=os.getpid())
        save(state_path, state)
        log_path = RESULTS / f"{args.phase}_{name}_{SUFFIX}.log"
        with log_path.open("a", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
            stage["child_pid"] = process.pid
            save(state_path, state)
            print("START", args.phase, name, process.pid, flush=True)
            exit_code = process.wait()
        output = report_path(name, pilot=args.phase == "pilot", graded=args.phase == "grade")
        report = json.loads(output.read_text(encoding="utf-8"))
        count = len(report["results"])
        expected = len(PILOT_CASES) if args.phase == "pilot" else 60
        judged = sum(row.get("score") is not None for row in report["results"])
        complete = count == expected and (args.phase != "grade" or judged == expected)
        stage.update(status="collected" if complete else "incomplete", exit_code=exit_code,
                     cases=count, completed=sum(row["structure"]["completed"] for row in report["results"]),
                     judged=judged,
                     output_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
        save(state_path, state)
        print("FINISHED", args.phase, name, json.dumps(stage, ensure_ascii=False), flush=True)
        if not complete:
            state["status"] = "incomplete_requires_review"
            save(state_path, state)
            return 1
    state["status"] = "collected_requires_quality_review"
    save(state_path, state)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--phase", required=True, choices=("pilot", "full", "grade", "compare"))
    parser.add_argument("--resume", action="store_true")
    raise SystemExit(main(parser.parse_args()))

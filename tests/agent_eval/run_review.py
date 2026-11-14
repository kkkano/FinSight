"""用真实模型运行成对注错题；报告检出、误报与不可用，不把不可用算通过。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import time
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from agent_eval.run import evaluation_model, evaluation_artifact_root, evaluation_file_reference, isolated_environment, write_json, runtime_digest, model_quota_configuration
from agent_eval.eval_transport import observe_chunks


def summarize(rows):
    clean = [row for row in rows if row["variant"] == "clean"]
    injected = [row for row in rows if row["variant"] == "injected"]
    return {"runs": len(rows), "completed": sum(row["review"]["status"] == "completed" for row in rows),
        "clean_cases": len(clean), "false_positive_count": sum(bool(row["review"].get("findings")) for row in clean),
        "injected_cases": len(injected), "annotated_injected_span_count": sum(row["annotated_injected_span"] for row in injected),
        "semantic_detection_adjudication": "pending_independent_review",
        "false_positive_rate": sum(bool(row["review"].get("findings")) for row in clean) / len(clean) if clean else None,
        "unavailable_count": sum(row["review"]["status"] != "completed" for row in rows)}


async def main(args):
    from dotenv import load_dotenv
    load_dotenv(REPO / ".env.runtime.local", override=False)
    from backend.agent_runtime.config import resolve_model
    from backend.agent_runtime.envelope import ToolResult
    from backend.agent_runtime.loop import AgentRuntime
    from backend.agent_runtime.model import ModelTransport
    from backend.agent_runtime.limits import LeaseLimiter
    from backend.agent_runtime.diagnostics import safe_code
    from backend.agent_runtime.verifier import review_answer
    from backend.services.run_context import RunContext

    dataset_path = Path(__file__).with_name("review_cases.json")
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    cases = [case for case in dataset["cases"] if not args.case or case["id"] in args.case]
    if args.limit:
        cases = cases[:args.limit]
    base = None if args.provider in {"stepfun", "moxuna", "vectide", "apikl"} else resolve_model()
    model = evaluation_model(base, args.provider)
    run_id = time.strftime("review-%Y%m%d-%H%M%S")
    output = REPO / args.output
    review_timeout = args.review_timeout
    work = evaluation_artifact_root() / run_id
    shared_quota = Path(args.shared_quota).resolve() if args.shared_quota else None
    report = {"run_id": run_id, "provider": args.provider, "model": model.model, "synthetic": True,
        "harness_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "dataset_sha256": hashlib.sha256(dataset_path.read_bytes()).hexdigest(),
        "runtime_sha256": runtime_digest(REPO / "backend/agent_runtime"),
        "expected_variants": len(cases) * 2, "collection_status": "running", "rows": [],
        "review_timeout_seconds": review_timeout, "context_budget_seconds": review_timeout + 5,
        "artifact_root": str(evaluation_artifact_root()), "raw_artifacts": evaluation_file_reference(work),
        "shared_quota": str(shared_quota) if shared_quota else None}
    work.mkdir(parents=True, exist_ok=True)
    class ObservedTransport(ModelTransport):
        def __init__(self, config):
            super().__init__(config)
            self.failures = []
            self.call_outcomes = []

        async def stream(self, *args, **kwargs):
            outcome = {}
            self.call_outcomes.append(outcome)
            try:
                async for chunk in observe_chunks(super().stream(*args, **kwargs), outcome):
                    yield chunk
            except Exception as exc:
                self.failures.append({"code": safe_code(getattr(exc, "code", "model_error")),
                                      "http_status": getattr(exc, "status", None)})
                raise
    environment = isolated_environment(work)
    if shared_quota:
        environment.update(FINSIGHT_AGENT_MODEL_CONCURRENCY="2", FINSIGHT_AGENT_RPM_LIMIT="30",
                           FINSIGHT_AGENT_TPM_LIMIT="250000", FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS="10")
    with patch.dict(os.environ, environment):
        report["model_quotas"] = model_quota_configuration()
        for case in cases:
            for variant in ("clean", "injected"):
                events = []
                async def emit(kind, payload, agent_id):
                    events.append({"type": kind, "payload": payload, "agent_id": agent_id})
                context = RunContext.create(owner="review-eval", entry="review", budget_seconds=review_timeout + 5)
                context.quota_checker = lambda _owner: None
                runtime = AgentRuntime(context=context, session_id=run_id, query=case["query"],
                    model=ObservedTransport(model), emit=emit, tools={},
                    limiter=LeaseLimiter(shared_quota) if shared_quota else None)
                for fixture in case["fixtures"]:
                    envelope = ToolResult.model_validate({key: value for key, value in fixture.items() if key != "handle"} | {
                        "sources": [{key: value for key, value in source.items() if key != "id"} for source in fixture["sources"]]})
                    runtime.data.record("synthetic_fixture", {}, envelope.data, envelope=envelope)
                started = time.monotonic()
                answer = case[variant]["answer"]
                try:
                    review = await review_answer(runtime, answer, max_seconds=review_timeout)
                finally:
                    await runtime.close()
                # 这里只测已知注入片段是否被标注，语义检出由独立评审另行确认。
                changed = case["injected"]["injection"]["after"]
                span_flagged = variant == "injected" and any(changed in finding["quote"] for finding in review.get("findings", []))
                row = {"case_id": case["id"], "variant": variant, "query": case["query"], "answer": answer,
                    "fixtures": case["fixtures"], "review": review, "annotated_injected_span": span_flagged,
                    "elapsed_seconds": round(time.monotonic() - started, 3), "usage": context.usage.summary(), "events": events,
                    "model_failures": runtime.model.failures, "model_call_outcomes": runtime.model.call_outcomes}
                report["rows"].append(row)
                report["summary"] = summarize(report["rows"])
                limit = getattr(args, "stop_after_initial_failures", 0)
                initial_failure_stop = limit and len(report["rows"]) == limit and all(
                    item["review"].get("error_code") == "review_timeout" or any(
                        failure["code"] == "model_http_502" for failure in item["model_failures"])
                    for item in report["rows"])
                if initial_failure_stop:
                    report["collection_status"] = "partial_stopped_after_initial_provider_failures"
                write_json(output, report)
                print(json.dumps({"case_id": case["id"], "variant": variant, "status": review["status"],
                    "verdict": review.get("verdict"), "findings": len(review.get("findings", [])),
                    "seconds": row["elapsed_seconds"], "model_failures": runtime.model.failures}), flush=True)
                if initial_failure_stop:
                    print(json.dumps({"collection_status": report["collection_status"], **report["summary"]}), flush=True)
                    return
    report["collection_status"] = "completed"
    write_json(output, report)
    print(json.dumps(report["summary"]), flush=True)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", choices=("configured", "fallback", "stepfun", "moxuna", "vectide", "apikl"), default="moxuna")
    parser.add_argument("--case", action="append")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--stop-after-initial-failures", type=int, default=0)
    parser.add_argument("--review-timeout", type=float, default=45, help="核查预算（秒），父上下文额外保留5秒")
    parser.add_argument("--shared-quota", help="显式复用评测账户的SQLite配额库")
    parser.add_argument("--output", required=True)
    return parser


if __name__ == "__main__":
    logging.basicConfig(level=logging.ERROR)
    asyncio.run(main(build_parser().parse_args()))

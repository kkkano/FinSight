"""独立评分后处理：保留测量与评分payload，只补上同账号配额和实际用量记录。"""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import time
from unittest.mock import patch

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
import sys
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from agent_eval import run as runner
from agent_eval.scoring import ContentScore, JUDGE_SYSTEM
from agent_eval.tapes import ToolTape
from backend.agent_runtime.config import ModelConfig
from backend.agent_runtime.context import tokens
from backend.agent_runtime.limits import LeaseLimiter, TokenReservations
from backend.agent_runtime.model import BudgetedModel, ModelProtocolError, ModelTransport as OriginalTransport
from backend.services.run_context import RunContext


def checksum(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def scoring_input(case, row, records):
    """与现有judge_answer保持相同投影，仅用于完整证据容量审计。"""
    answers = [{"query": turn["query"], "answer": turn["terminal"].get("response", ""),
                "artifacts": turn["terminal"].get("artifacts", []),
                "actions": turn["terminal"].get("actions", []),
                "sources": turn["terminal"].get("evidence_pool", [])} for turn in row["turns"]]
    evidence = [{key: record[key] for key in ("tool", "arguments", "result", "injected") if key in record}
                for record in records]
    payload = {"case": case, "answers": answers, "recordings": evidence}
    messages = [{"role": "system", "content": JUDGE_SYSTEM},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
    schema = {"type": "function", "function": {"name": "submit_score",
              "description": "提交独立评测的结构化分数与理由。", "parameters": ContentScore.model_json_schema()}}
    return payload, messages, schema


def inspect_capacity(report, corpus, judge):
    fixture_base = ROOT / "tests/agent_eval" / report.get("fixtures_root", "fixtures")
    by_id = {case["id"]: case for case in corpus["cases"]}
    rows = []
    for row in report["results"]:
        case = by_id[row["id"]]
        records = ToolTape(fixture_base / case["id"], "replay", faults=case.get("tool_faults")).records()
        payload, messages, schema = scoring_input(case, row, records)
        amount = tokens(messages) + tokens(schema) + judge.max_output
        rows.append({"case_id": row["id"], "group": case["group"], "complete_recordings": len(records),
                     "scoring_input_sha256": checksum(payload), "configured_total_token_estimate": amount,
                     "context_window": judge.context_window, "fits_configured_window": amount <= judge.context_window,
                     "answer_bytes": sum(len(turn["terminal"].get("response", "").encode()) for turn in row["turns"])})
    return {"estimator": "backend.agent_runtime.context.tokens; matches current judge_answer preflight",
            "actual_service_tokenization_verified": False, "cases": len(rows), "rows": rows,
            "exceeded_cases": [row["case_id"] for row in rows if not row["fits_configured_window"]],
            "maximum_configured_total_token_estimate": max(row["configured_total_token_estimate"] for row in rows)}


class WaitingLeaseLimiter(LeaseLimiter):
    """在已有配额窗口释放前等待，不跳过或改小预占。"""
    def __init__(self, path, context, events):
        super().__init__(path)
        self.context, self.events = context, events

    def reserve_window(self, bucket, amount, **kwargs):
        started = time.monotonic()
        identity = super().reserve_window(bucket, amount, **kwargs)
        if bucket.startswith("provider:"):
            while identity is None and self.context.remaining_seconds > 0:
                time.sleep(min(0.1, self.context.remaining_seconds))
                identity = super().reserve_window(bucket, amount, **kwargs)
            self.events.append({"bucket": bucket, "reserved_tokens": amount,
                                "maximum": kwargs["maximum"], "requests": kwargs["requests"],
                                "reservation_succeeded": identity is not None,
                                "wait_seconds": round(time.monotonic() - started, 3)})
        return identity


def quota_transport_class(shared_quota, attempts, *, budgeted_model_class=BudgetedModel, context_seconds=180):
    class QuotaJudgeTransport:
        def __init__(self, config, *, client=None):
            self.config = config
            self.target = OriginalTransport(config, client=client)

        async def stream(self, messages, tools, **kwargs):
            context = RunContext(owner="isolated-independent-judge", entry="judge", deadline=time.monotonic() + context_seconds)
            context.quota_checker = lambda _owner: None
            reservations = TokenReservations(int(os.getenv("FINSIGHT_AGENT_TOKEN_BUDGET", "160000")))
            events = []
            runtime = SimpleNamespace(context=context, budget=reservations,
                limiter=WaitingLeaseLimiter(shared_quota, context, events), model_duration_seconds={}, model=self.target)
            spec = SimpleNamespace(model=self.target, agent_id="independent_judge", role="judge")
            attempt = {"requested_model": self.config.model, "request_sha256": checksum({"messages": messages, "tools": tools}),
                       "provider_identity": self.config.provider_identity(), "events": events, "reported_models": [],
                       "started_at": datetime.now(timezone.utc).isoformat()}
            attempts.append(attempt)
            reported = set()
            try:
                async for chunk in budgeted_model_class(runtime, spec).stream(messages, tools, **kwargs):
                    if chunk.get("model"):
                        reported.add(chunk["model"])
                    if chunk.get("usage"):
                        attempt["usage"] = chunk["usage"]
                    yield chunk
                if reported != {self.config.model}:
                    raise ModelProtocolError("judge_returned_model_mismatch")
                attempt["status"] = "completed"
            except Exception as exc:
                attempt["status"] = "failed"
                attempt["error_code"] = getattr(exc, "code", type(exc).__name__)
                raise
            finally:
                attempt.update(reported_models=sorted(reported), budget_spent=reservations.spent,
                               budget_reserved_remaining=reservations.reserved,
                               completed_at=datetime.now(timezone.utc).isoformat())
    return QuotaJudgeTransport


async def main(args):
    source, output = Path(args.source).resolve(), Path(args.output).resolve()
    if source == output and not args.resume:
        raise ValueError("original_measurement_must_not_be_overwritten")
    if output.exists() and not args.resume:
        raise ValueError("existing_grading_output_requires_resume")
    if args.resume:
        source = output
    report = json.loads(source.read_text(encoding="utf-8"))
    if report.get("mode") != "replay" or len(report["results"]) != 60:
        raise ValueError("full_replay_measurement_required")
    values = dotenv_values(ROOT / ".env.runtime.local")
    declared = report["judge"]
    if declared["protocol"] != "tools" or declared["base_url"] != values["FINSIGHT_EVAL_APIKL_API_BASE"]:
        raise ValueError("judge_protocol_or_endpoint_changed")
    judge = ModelConfig(declared["model"], declared["base_url"], values["FINSIGHT_EVAL_APIKL_API_KEY"],
                        context_window=declared["context_window"], max_output=declared["max_output"])
    corpus = json.loads((ROOT / "tests/agent_eval/cases.json").read_text(encoding="utf-8"))
    capacity = inspect_capacity(report, corpus, judge)
    audit = output.with_name(output.stem + "_capacity.json")
    audit.write_text(json.dumps(capacity, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": capacity["cases"], "input_exceeds_configuration": capacity["exceeded_cases"]}), flush=True)
    attempts = []
    shared_quota = Path(args.shared_quota).resolve()
    implementation = {"wrapper": Path(__file__).relative_to(ROOT).as_posix(),
                      "sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      "source_input_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
                      "scoring_module_sha256": hashlib.sha256((ROOT / "tests/agent_eval/scoring.py").read_bytes()).hexdigest(),
                      "scoring_protocol": "tools", "scoring_tool": "submit_score",
                      "transport": "existing BudgetedModel + WaitingLeaseLimiter",
                      "shared_account_quota": str(shared_quota), "rpm": 30, "tpm": 250000,
                      "minimum_request_interval_seconds": 10, "per_call_token_budget": 160000,
                      "four_subject_measurements_changed": False}
    if args.resume:
        archive = output.with_name(output.stem + "_pre_resume_" + hashlib.sha256(source.read_bytes()).hexdigest()[:12] + ".json")
        if not archive.exists():
            archive.write_bytes(source.read_bytes())
        implementation["resumed_from"] = archive.name
    environment = runner.isolated_environment(ROOT / "tmp/r261113/grading") | {
        "FINSIGHT_AGENT_MODEL_CONCURRENCY": "2", "FINSIGHT_AGENT_RPM_LIMIT": "30",
        "FINSIGHT_AGENT_TPM_LIMIT": "250000", "FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS": "10",
        "FINSIGHT_AGENT_TOKEN_BUDGET": "160000"}
    import backend.agent_runtime.model as model_module
    with patch.dict(os.environ, environment), patch.object(model_module, "ModelTransport", quota_transport_class(shared_quota, attempts)):
        result = await runner.grade_report(source, output, corpus, judge, ROOT / "tests/agent_eval",
                                          runner.RequestPacer(6.1), "tools")
    graded = json.loads(output.read_text(encoding="utf-8"))
    graded["judge_execution"] = implementation
    graded["judge_transport_attempts"] = attempts
    graded["complete_scoring_input_capacity_audit"] = audit.name
    output.write_text(json.dumps(graded, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--shared-quota", required=True)
    parser.add_argument("--resume", action="store_true", help="仅补判失败提交，已有有效评分保留并归档前次输出")
    raise SystemExit(asyncio.run(main(parser.parse_args())))

"""核查评测的显式预算、共享配额和外部产物目录不改变成对输入。"""
import json
from pathlib import Path

import pytest

from . import run as runner
from . import run_review as review_runner


@pytest.mark.asyncio
async def test_review_budget_shared_quota_and_external_artifacts_are_recorded(tmp_path, monkeypatch):
    from backend.agent_runtime.config import ModelConfig
    from backend.agent_runtime import verifier

    workspace = tmp_path / "workspace"
    artifact_root = tmp_path / "external-artifacts"
    quota = tmp_path / "shared-quota.sqlite"
    monkeypatch.setattr(review_runner, "REPO", workspace)
    monkeypatch.setattr(runner, "REPO", workspace)
    monkeypatch.setenv("FINSIGHT_EVAL_ARTIFACT_ROOT", str(artifact_root))
    monkeypatch.setattr(review_runner, "evaluation_model", lambda *_args: ModelConfig(
        "fixture-model", "https://fixture.invalid/v1", "fixture-key"))
    monkeypatch.setattr(review_runner, "runtime_digest", lambda _path: "fixture-runtime-hash")
    observed = []

    async def review(runtime, answer, *, max_seconds):
        observed.append(answer)
        assert max_seconds == 90
        assert 94 < runtime.context.remaining_seconds <= 95
        assert runtime.limiter.path == quota
        return {"status": "completed", "verdict": "pass", "findings": []}

    monkeypatch.setattr(verifier, "review_answer", review)
    args = review_runner.build_parser().parse_args([
        "--provider", "apikl", "--limit", "1", "--review-timeout", "90",
        "--shared-quota", str(quota), "--output", "results/review.json"
    ])
    await review_runner.main(args)
    report = json.loads((workspace / args.output).read_text(encoding="utf-8"))
    assert report["synthetic"] and report["collection_status"] == "completed"
    assert len(report["rows"]) == 2 and [row["answer"] for row in report["rows"]] == observed
    assert report["review_timeout_seconds"] == 90 and report["context_budget_seconds"] == 95
    assert report["shared_quota"] == str(quota)
    assert Path(report["raw_artifacts"]).is_relative_to(artifact_root)
    assert report["model_quotas"]["minimum_request_interval_seconds"] == 10


def test_default_review_budget_preserves_previous_45_second_contract():
    args = review_runner.build_parser().parse_args(["--output", "fixture.json"])
    assert args.review_timeout == 45 and args.shared_quota is None

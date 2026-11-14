"""评测入口必须经过完整服务边界，并隔离账户和所有落盘目录。"""
from copy import deepcopy
import builtins
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
from types import SimpleNamespace
import asyncio
from threading import Lock
import time

import httpx
import pytest

from . import run as runner


def test_cli_defaults_to_current_and_exposes_only_current_and_baseline():
    parser = runner.build_parser()
    assert parser.parse_args([]).runtime == "current"
    assert parser.parse_args(["--runtime", "current"]).runtime == "current"
    assert parser.parse_args(["--runtime", "baseline"]).runtime == "baseline"
    runtime_option = next(action for action in parser._actions if action.dest == "runtime")
    assert set(runtime_option.choices) == {"current", "baseline"}


@pytest.mark.parametrize("provider,model,window", [("vectide", "deepseek-v4.1-flash-1017", 1048576), ("apikl", "gpt-6-luna", 131072)])
def test_isolated_provider_is_explicit_and_does_not_mutate_production(monkeypatch, provider, model, window):
    from backend.agent_runtime.config import ModelConfig

    for name, value in {"MODEL": model, "API_BASE": "https://isolated.invalid/v1/",
                        "API_KEY": "fixture-key", "CONTEXT_WINDOW": str(window), "MAX_OUTPUT": "16384"}.items():
        monkeypatch.setenv("FINSIGHT_EVAL_" + provider.upper() + "_" + name, value)
    base = ModelConfig("production", "https://production.invalid/v1", "production-key", effort="high")
    selected = runner.evaluation_model(base, provider)
    assert runner.build_parser().parse_args(["--provider", provider]).provider == provider
    assert selected.model == model
    assert selected.base_url == "https://isolated.invalid/v1"
    assert selected.api_key == "fixture-key"
    assert (selected.context_window, selected.max_output, selected.effort) == (window, 16384, None)
    assert (base.model, base.api_key, base.effort) == ("production", "production-key", "high")
    assert "api_key" not in selected.public_metadata()


@pytest.mark.parametrize("missing", ["MODEL", "API_BASE", "API_KEY"])
@pytest.mark.parametrize("provider", ["vectide", "apikl"])
def test_isolated_provider_missing_configuration_cannot_borrow_production_credentials(monkeypatch, missing, provider):
    for name, value in {"MODEL": "deepseek-v4.1-flash-1017", "API_BASE": "https://vectide.invalid/v1",
                        "API_KEY": "fixture-key"}.items():
        monkeypatch.setenv("FINSIGHT_EVAL_" + provider.upper() + "_" + name, value)
    monkeypatch.delenv("FINSIGHT_EVAL_" + provider.upper() + "_" + missing)
    with pytest.raises(ValueError, match="^evaluation_" + provider + "_configuration_incomplete$"):
        runner.evaluation_model(None, provider)


@pytest.mark.parametrize("retired", ["agent", "agent1", "agent2", "v1", "v2"])
def test_cli_rejects_retired_runtime_choices(retired, capsys):
    with pytest.raises(SystemExit) as captured:
        runner.build_parser().parse_args(["--runtime", retired, "--list"])
    assert captured.value.code == 2
    assert "invalid choice" in capsys.readouterr().err
    with pytest.raises(ValueError, match="^unknown_evaluation_runtime$"):
        runner.activate_runtime(retired)


def test_runtime_tool_factories_are_independent_and_current_is_default(monkeypatch):
    import backend.agent_runtime as runtime_package
    from backend.agent_runtime import registry
    from agent_eval.baseline_runtime import tools as baseline_tools

    current_specs, baseline_specs = {"current": object()}, {"baseline": object()}
    monkeypatch.setattr(registry, "financial_tools", lambda: current_specs)
    monkeypatch.setattr(baseline_tools, "financial_tools", lambda: baseline_specs)
    before = list(runtime_package.__path__)
    assert runner.financial_tool_specs() is current_specs
    assert runner.financial_tool_specs("current") is current_specs
    assert runner.financial_tool_specs("baseline") is baseline_specs
    assert list(runtime_package.__path__) == before


def _shared_pacing_worker(shared_state, barrier, observations):
    async def requests():
        pacer = runner.RequestPacer(0.15, shared_state)
        marker = str(os.getpid())
        os.environ["FINSIGHT_EVAL_PROCESS_MARKER"] = marker

        class Transport:
            def __init__(self, name):
                self.config = SimpleNamespace(model=name)

            async def stream(self, *_args, **_kwargs):
                observations.append({"pid": os.getpid(), "marker": os.environ["FINSIGHT_EVAL_PROCESS_MARKER"],
                                     "model": self.config.model, "started": time.monotonic()})
                yield {"choices": [{"delta": {"content": "协议片段"}}]}

        for name in ("research", "judge"):
            stream = runner.PacedTransport(Transport(name), pacer)
            async for _chunk in stream.stream([], []):
                pass

    barrier.wait(timeout=15)
    asyncio.run(requests())


def test_fallback_provider_is_explicit_and_preserves_production_configuration(monkeypatch):
    from backend.agent_runtime.config import ModelConfig

    base = ModelConfig("production", "https://production.invalid/v1", "production-fixture-key", effort="high")
    values = {"MODEL": "fallback", "API_BASE": "https://fallback.invalid/v1/", "API_KEY": "fallback-fixture-key",
              "CONTEXT_WINDOW": "1000000", "MAX_OUTPUT": "16384"}
    for name, value in values.items():
        monkeypatch.setenv("FINSIGHT_EVAL_FALLBACK_" + name, value)
    assert runner.evaluation_model(base, "configured") is base
    selected = runner.evaluation_model(base, "fallback")
    assert selected.model == "fallback" and selected.base_url == "https://fallback.invalid/v1"
    assert selected.api_key == "fallback-fixture-key" and selected.effort is None
    assert (selected.context_window, selected.max_output) == (1000000, 16384)
    assert base.model == "production" and base.api_key == "production-fixture-key" and base.effort == "high"


def test_incomplete_fallback_is_rejected_without_echoing_secrets(monkeypatch):
    from backend.agent_runtime.config import ModelConfig

    monkeypatch.setenv("FINSIGHT_EVAL_FALLBACK_MODEL", "fallback")
    monkeypatch.setenv("FINSIGHT_EVAL_FALLBACK_API_KEY", "private-fixture-key")
    monkeypatch.delenv("FINSIGHT_EVAL_FALLBACK_API_BASE", raising=False)
    with pytest.raises(ValueError, match="^evaluation_fallback_configuration_incomplete$"):
        runner.evaluation_model(ModelConfig("production", "https://example.invalid", "production-key"), "fallback")


def test_stepfun_provider_uses_only_research_key_with_official_low_effort_model(monkeypatch):
    monkeypatch.setenv("FINSIGHT_AGENT_STEPFUN_API_KEY", "research-stepfun-fixture-key")
    monkeypatch.setenv("STEPFUN_API_KEY", "frozen-forecast-fixture-key")
    selected = runner.evaluation_model(None, "stepfun")
    assert selected.model == "step-5-preview" and selected.base_url == "https://api.stepfun.com/v1"
    assert selected.api_key == "research-stepfun-fixture-key" and selected.effort == "low"
    assert selected.context_window == 1000000 and selected.max_output == 4096
    assert os.environ["STEPFUN_API_KEY"] == "frozen-forecast-fixture-key"


def test_missing_stepfun_research_key_does_not_borrow_frozen_prediction_key(monkeypatch):
    monkeypatch.delenv("FINSIGHT_AGENT_STEPFUN_API_KEY", raising=False)
    monkeypatch.setenv("STEPFUN_API_KEY", "frozen-forecast-fixture-key")
    with pytest.raises(ValueError, match="^evaluation_stepfun_configuration_incomplete$"):
        runner.evaluation_model(None, "stepfun")


@pytest.mark.parametrize("model", [None, "explicit-alternate-model"])
def test_moxuna_provider_uses_isolated_configuration_and_preserves_requested_model(monkeypatch, model):
    from backend.agent_runtime.config import ModelConfig

    production = ModelConfig("production", "https://production.invalid/v1", "production-fixture-key", effort="high")
    monkeypatch.setenv("FINSIGHT_EVAL_MOXUNA_API_BASE", "https://moxuna.invalid/v1/")
    monkeypatch.setenv("FINSIGHT_EVAL_MOXUNA_API_KEY", "moxuna-fixture-key")
    monkeypatch.setenv("FINSIGHT_EVAL_FALLBACK_API_KEY", "fallback-fixture-key")
    monkeypatch.setenv("FINSIGHT_AGENT_STEPFUN_API_KEY", "stepfun-fixture-key")
    if model is None:
        monkeypatch.delenv("FINSIGHT_EVAL_MOXUNA_MODEL", raising=False)
    else:
        monkeypatch.setenv("FINSIGHT_EVAL_MOXUNA_MODEL", model)
    environment = dict(os.environ)

    selected = runner.evaluation_model(production, "moxuna")
    assert selected.model == (model or "deepseek-v4.1-flash")
    assert selected.base_url == "https://moxuna.invalid/v1" and selected.api_key == "moxuna-fixture-key"
    assert selected.endpoint_name == "evaluation-moxuna" and selected.effort is None
    assert (selected.context_window, selected.max_output) == (32768, 4096)
    assert runner.evaluation_model(production, "configured") is production
    assert production.model == "production" and production.api_key == "production-fixture-key" and production.effort == "high"
    assert dict(os.environ) == environment


@pytest.mark.parametrize("missing", ["API_BASE", "API_KEY"])
def test_missing_moxuna_credentials_do_not_borrow_other_provider_configuration(monkeypatch, missing):
    from backend.agent_runtime.config import ModelConfig

    values = {"API_BASE": "https://fixture.invalid/v1", "API_KEY": "private-fixture-key", "MODEL": "explicit-model"}
    for provider in ("MOXUNA", "FALLBACK"):
        for name, value in values.items():
            monkeypatch.setenv("FINSIGHT_EVAL_" + provider + "_" + name, value)
    monkeypatch.setenv("FINSIGHT_AGENT_STEPFUN_API_KEY", "stepfun-fixture-key")
    monkeypatch.delenv("FINSIGHT_EVAL_MOXUNA_" + missing)
    with pytest.raises(ValueError, match="^evaluation_moxuna_configuration_incomplete$"):
        runner.evaluation_model(ModelConfig("production", "https://production.invalid/v1", "production-key"), "moxuna")


@pytest.mark.asyncio
@pytest.mark.parametrize("model,limits", [("deepseek-v4.1-flash", (None, None)),
                                          ("explicit-alternate-model", (65536, 8192))])
async def test_moxuna_main_starts_without_production_model_and_records_actual_metadata(tmp_path, monkeypatch, model, limits):
    from backend.agent_runtime import config

    eval_dir = tmp_path / "agent_eval"
    eval_dir.mkdir()
    case = {"id": "fixture-1", "group": "facts", "turns": ["协议输入"], "expects": {}}
    (eval_dir / "cases.json").write_text(json.dumps({"cases": [case]}), encoding="utf-8")
    monkeypatch.setattr(runner, "__file__", str(eval_dir / "run.py"))
    monkeypatch.setattr(runner, "REPO", tmp_path)
    monkeypatch.setattr(runner, "activate_runtime", lambda _name: eval_dir)
    monkeypatch.setattr(config, "load_local_config", lambda: None)
    monkeypatch.setattr(runner.subprocess, "check_output", lambda *_args, **_kwargs: "fixture-head\n")
    monkeypatch.setenv("FINSIGHT_EVAL_MOXUNA_API_BASE", "https://moxuna.invalid/v1/")
    monkeypatch.setenv("FINSIGHT_EVAL_MOXUNA_API_KEY", "moxuna-private-fixture-key")
    monkeypatch.setenv("FINSIGHT_EVAL_MOXUNA_MODEL", model)

    def unavailable_production_model():
        raise AssertionError("独立评测端点不得依赖生产模型配置")

    async def isolated_case(seen_case, subject, judge, args, directory, pacer):
        assert seen_case == case and directory == eval_dir
        assert subject.api_key == "moxuna-private-fixture-key" and subject.model == model
        assert judge.model == runner.EXTERNAL_JUDGE["model"] and judge.model != subject.model
        assert isinstance(pacer, runner.RequestPacer) and pacer.interval == 2.5
        result = synthetic_measurement_report()["results"][0]
        result["model"] = subject.model
        result["model_call_outcomes"][0]["model"] = subject.model
        result["score"] = None
        return result

    monkeypatch.setattr(config, "resolve_model", unavailable_production_model)
    monkeypatch.setattr(runner, "run_case", isolated_case)
    output = tmp_path / "result.json"
    args = SimpleNamespace(runtime="current", provider="moxuna", model_protocol="sse", request_interval=2.5,
                           case=None, list=False, limit=None, context_window=limits[0], max_output=limits[1],
                           judge_protocol="external", output=str(output), grade_report=None,
                           mode="replay", fixtures_root="fixtures", seed_tapes=None, jobs=1, baseline=None, timeout=180)
    assert await runner.main(args) == 2  # 未导入外部评分，结果仍待判分。
    report_text = output.read_text(encoding="utf-8")
    report = json.loads(report_text)
    expected = {"model": model, "base_url": "https://moxuna.invalid/v1", "effort": None, "temperature": None,
                "context_window": limits[0] or 32768, "max_output": limits[1] or 4096}
    assert report["subject"] == report["harness_config"]["model_configuration"] == expected
    assert report["harness_config"]["model_protocol"] == "sse"
    assert report["harness_config"]["timeout_seconds"] == 180
    assert report["harness_config"]["timeout_scope"] == "per_turn"
    assert report["harness_config"]["model_quota_scope"] == "run_shared"
    assert report["harness_config"]["step5_cost_pricing"] is None
    assert report["judge"]["model"] == runner.EXTERNAL_JUDGE["model"]
    assert report["results"][0]["model"] == model
    assert report["runtime"] == "current"
    assert "moxuna-private-fixture-key" not in report_text


def test_quota_metadata_records_actual_model_limits(monkeypatch):
    values = {"FINSIGHT_AGENT_MODEL_CONCURRENCY": "3", "FINSIGHT_AGENT_RPM_LIMIT": "17",
              "FINSIGHT_AGENT_TPM_LIMIT": "120000", "FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS": "2.5",
              "FINSIGHT_AGENT_TOKEN_BUDGET": "140000"}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert runner.model_quota_configuration() == {"concurrency": 3, "rpm": 17, "tpm": 120000,
                                                  "minimum_request_interval_seconds": 2.5, "run_token_budget": 140000}


@pytest.mark.asyncio
async def test_pacer_serializes_concurrent_requests_without_real_wait(monkeypatch):
    clock = [100.0]
    waits = []

    async def sleep(delay):
        waits.append(delay)
        clock[0] += delay

    monkeypatch.setattr(runner.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(runner.asyncio, "sleep", sleep)
    pacer = runner.RequestPacer(6.1)
    await asyncio.gather(pacer.wait(), pacer.wait(), pacer.wait())
    assert waits == pytest.approx([6.1, 6.1])


@pytest.mark.asyncio
async def test_shared_pacer_rechecks_global_clock_after_delayed_wakeup(monkeypatch):
    clock, waits = [100.0], []
    shared = SimpleNamespace(next_allowed=SimpleNamespace(value=106.1), lock=Lock())

    async def sleep(delay):
        waits.append(delay)
        clock[0] += delay
        if len(waits) == 1:
            # 本进程迟到时，另一个进程已获得当前请求机会。
            clock[0] += 20
            shared.next_allowed.value = clock[0] + 6.1

    monkeypatch.setattr(runner.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(runner.asyncio, "sleep", sleep)
    await runner.RequestPacer(6.1, shared).wait()
    assert waits == pytest.approx([6.1, 6.1])
    assert shared.next_allowed.value == pytest.approx(clock[0] + 6.1)


def test_spawned_processes_share_research_and_judge_pacing():
    context = multiprocessing.get_context("spawn")
    with context.Manager() as manager:
        shared = SimpleNamespace(next_allowed=manager.Value("d", 0.0), lock=manager.Lock())
        barrier, observations = manager.Barrier(2), manager.list()
        processes = [context.Process(target=_shared_pacing_worker, args=(shared, barrier, observations))
                     for _ in range(2)]
        try:
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=20)
            assert all(process.exitcode == 0 for process in processes)
            rows = sorted(list(observations), key=lambda row: row["started"])
            assert len(rows) == 4 and len({row["pid"] for row in rows}) == 2
            assert all(row["marker"] == str(row["pid"]) for row in rows)
            assert all(second["started"] - first["started"] >= 0.13 for first, second in zip(rows, rows[1:]))
            for pid in {row["pid"] for row in rows}:
                assert {row["model"] for row in rows if row["pid"] == pid} == {"research", "judge"}
        finally:
            for process in processes:
                if process.is_alive():
                    process.terminate()
                process.join()


def test_worker_constructs_its_pacer_with_shared_state(monkeypatch):
    shared = SimpleNamespace(next_allowed=SimpleNamespace(value=0.0), lock=Lock())
    args = SimpleNamespace(request_interval=6.1)

    async def observed_case(case, subject, judge, seen_args, directory, pacer):
        assert (case, subject, judge, seen_args, directory) == ("case", "subject", "judge", args, "directory")
        assert pacer.interval == 6.1 and pacer._shared_state is shared
        return "isolated-case-result"

    monkeypatch.setattr(runner, "run_case", observed_case)
    assert runner.run_case_in_process("case", "subject", "judge", args, "directory", shared) == "isolated-case-result"


@pytest.mark.asyncio
async def test_paced_transport_preserves_protocol_and_model_configuration():
    seen = []
    config = object()

    class Transport:
        async def stream(self, messages, tools, **kwargs):
            seen.append((messages, tools, kwargs))
            yield {"choices": [{"delta": {"content": "协议正文"}}]}

    transport = Transport()
    transport.config = config
    paced = runner.PacedTransport(transport, runner.RequestPacer())
    messages, tools = [{"role": "user", "content": "协议输入"}], [{"type": "function"}]
    chunks = [chunk async for chunk in paced.stream(messages, tools, max_tokens=42)]
    assert paced.config is config
    assert seen[0][:2] == (messages, tools)
    assert seen[0][2]["max_tokens"] == 42
    assert 0 < seen[0][2]["timeout"] <= 60
    assert chunks == [{"choices": [{"delta": {"content": "协议正文"}}]}]


@pytest.mark.asyncio
@pytest.mark.parametrize("received", [False, True])
async def test_connection_retry_is_allowed_only_before_the_first_stream_chunk(received):
    from backend.agent_runtime.model import ModelProtocolError

    calls, errors, chunks = [], [], []

    async def stream(messages, tools, **kwargs):
        calls.append((messages, tools, kwargs))
        if len(calls) == 1:
            if received:
                yield {"choices": [{"delta": {"content": "已经交付"}}]}
            raise ModelProtocolError("model_connection_error")
        yield {"choices": [{"delta": {"content": "重连成功"}}]}

    iterator = runner.evaluation_stream(stream, runner.RequestPacer(), errors, ["协议消息"], ["协议工具"])
    if received:
        with pytest.raises(ModelProtocolError):
            async for chunk in iterator:
                chunks.append(chunk)
        assert len(calls) == 1 and errors == []
        assert chunks == [{"choices": [{"delta": {"content": "已经交付"}}]}]
    else:
        chunks = [chunk async for chunk in iterator]
        assert len(calls) == 2 and calls[0][:2] == calls[1][:2]
        assert calls[1][2]["timeout"] <= calls[0][2]["timeout"]
        assert errors == [{"code": "model_connection_error", "cause": None, "recovered": True}]
        assert chunks == [{"choices": [{"delta": {"content": "重连成功"}}]}]


def test_isolated_watchlist_keeps_each_owners_items_separate():
    store = runner.IsolatedWatchlist()
    store.add_item("AAPL", user_id="first", note="first-only")
    store.add_item("AAPL", user_id="second", note="second-only")
    assert store.list_items("first") == [{"ticker": "AAPL", "note": "first-only"}]
    assert store.list_items("second") == [{"ticker": "AAPL", "note": "second-only"}]
    assert store.remove_item("AAPL", user_id="first") is True
    assert store.list_items("first") == []
    assert store.list_items("second") == [{"ticker": "AAPL", "note": "second-only"}]
    assert store.list_items("unknown") == []


def test_evaluation_worker_is_mapped_only_inside_case_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("FINSIGHT_ANALYSIS_WORKER_URL", "https://production-worker.invalid")
    monkeypatch.setenv("FINSIGHT_ANALYSIS_WORKER_TOKEN", "production-fixture-secret")
    monkeypatch.setenv("FINSIGHT_EVAL_ANALYSIS_WORKER_URL", "https://evaluation-worker.invalid")
    monkeypatch.setenv("FINSIGHT_EVAL_ANALYSIS_WORKER_TOKEN", "evaluation-fixture-secret")
    values = runner.isolated_environment(tmp_path)
    assert values["FINSIGHT_ANALYSIS_WORKER_URL"] == "https://evaluation-worker.invalid"
    assert values["FINSIGHT_ANALYSIS_WORKER_TOKEN"] == "evaluation-fixture-secret"
    assert os.environ["FINSIGHT_ANALYSIS_WORKER_URL"] == "https://production-worker.invalid"
    assert os.environ["FINSIGHT_ANALYSIS_WORKER_TOKEN"] == "production-fixture-secret"
    with runner.patch.dict(os.environ, values):
        assert os.environ["FINSIGHT_ANALYSIS_WORKER_TOKEN"] == "evaluation-fixture-secret"
    assert os.environ["FINSIGHT_ANALYSIS_WORKER_TOKEN"] == "production-fixture-secret"


@pytest.mark.parametrize("missing", ["URL", "TOKEN"])
def test_incomplete_evaluation_worker_does_not_override_production(monkeypatch, tmp_path, missing):
    monkeypatch.setenv("FINSIGHT_EVAL_ANALYSIS_WORKER_URL", "https://evaluation-worker.invalid")
    monkeypatch.setenv("FINSIGHT_EVAL_ANALYSIS_WORKER_TOKEN", "evaluation-fixture-secret")
    monkeypatch.delenv("FINSIGHT_EVAL_ANALYSIS_WORKER_" + missing)
    assert runner.evaluation_analysis_worker() == {}
    values = runner.isolated_environment(tmp_path)
    assert "FINSIGHT_ANALYSIS_WORKER_URL" not in values and "FINSIGHT_ANALYSIS_WORKER_TOKEN" not in values


@pytest.fixture
def grading_inputs(tmp_path):
    from backend.agent_runtime.config import ModelConfig

    case = {"id": "grade-1", "group": "concepts", "turns": ["协议输入"], "expects": {}}
    corpus = {"cases": [case]}
    (tmp_path / "cases.json").write_text(json.dumps(corpus), encoding="utf-8")
    fixtures = tmp_path / "fixtures"
    fixtures.mkdir()
    judge = ModelConfig("fixture-judge", "https://judge.invalid/v1", "fixture-judge-key",
                        context_window=131072, max_output=8192)
    report = {"cases_sha256": hashlib.sha256((tmp_path / "cases.json").read_bytes()).hexdigest(),
              "judge_prompt_sha256": hashlib.sha256(runner.JUDGE_SYSTEM.encode()).hexdigest(),
              "judge": {"model": judge.model, "base_url": judge.base_url,
                        "context_window": judge.context_window, "max_output": judge.max_output, "protocol": "tools"},
              "fixtures_root": "fixtures", "fixtures_sha256": runner.digest_files([], fixtures),
              "expected_cases": 1, "ready": False, "groups": {},
              "results": [{"id": case["id"], "group": case["group"], "model": "fixture-subject",
                           "score": None, "tape": {"misses": 0}, "elapsed_seconds": 1,
                           "transport_errors": [],
                           "turns": [{"query": "协议输入", "terminal": {"type": "done", "response": "合成回答"},
                                      "terminal_count": 1, "model_calls": 1}],
                           "model_call_outcomes": [{"model": "fixture-subject", "status": "completed", "received_chunks": 1, "synthetic": True}],
                           "structure": {"completed": False, "references_valid": True, "artifacts_met": True,
                                         "no_actions_met": True, "single_terminal_per_turn": True,
                                         "tokens": 0, "rounds": 1, "tool_error_rate": 0}}]}
    source = tmp_path / "source.json"
    source.write_text(json.dumps(report), encoding="utf-8")
    return source, tmp_path / "graded.json", corpus, judge, tmp_path, report


@pytest.mark.asyncio
@pytest.mark.parametrize("changed_field", ["model", "base_url", "context_window", "max_output", "protocol", "missing_base_url"])
async def test_grading_rejects_changed_or_missing_judge_configuration(grading_inputs, changed_field):
    source, output, corpus, judge, directory, report = grading_inputs
    if changed_field == "missing_base_url":
        report["judge"].pop("base_url")
    else:
        report["judge"][changed_field] = "different" if changed_field in {"model", "base_url", "protocol"} else 1
    source.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="^judge_changed_requires_new_evaluation$"):
        await runner.grade_report(source, output, corpus, judge, directory)
    assert not output.exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("changed", [False, True])
async def test_grading_rejects_missing_or_changed_frozen_fixtures(grading_inputs, changed):
    source, output, corpus, judge, directory, report = grading_inputs
    if changed:
        (directory / "fixtures" / "new-record.json").write_text("{}", encoding="utf-8")
    else:
        report.pop("fixtures_sha256")
        source.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="^evaluation_fixtures_changed_requires_new_evaluation$"):
        await runner.grade_report(source, output, corpus, judge, directory)
    assert not output.exists()


@pytest.mark.asyncio
async def test_grading_preserves_frozen_metadata_and_existing_scores(grading_inputs, monkeypatch):
    source, output, corpus, judge, directory, report = grading_inputs
    previous_score = {"answered": 1, "numbers": 1, "limitations": 1, "presentation": 0,
                      "no_internal_identifiers": 0, "total": 3, "reasons": ["原始判分"], "model": judge.model}
    report["results"][0]["score"] = previous_score
    second = deepcopy(report["results"][0])
    second.update(id="grade-2", score=None)
    report["results"].append(second)
    report["expected_cases"] = 2
    corpus["cases"].append({**corpus["cases"][0], "id": "grade-2"})
    (directory / "cases.json").write_text(json.dumps(corpus), encoding="utf-8")
    report["cases_sha256"] = hashlib.sha256((directory / "cases.json").read_bytes()).hexdigest()
    source.write_text(json.dumps(report), encoding="utf-8")
    seen = []

    async def score(transport, case, result, recordings, protocol="tools"):
        assert transport.config is judge
        assert protocol == "tools"
        seen.append(case["id"])
        return {**previous_score, "answered": 2, "numbers": 2, "total": 5}

    async def forbidden_send(*_args, **_kwargs):
        raise AssertionError("补判合同测试不得联网")

    monkeypatch.setattr(runner, "judge_answer", score)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden_send)
    assert await runner.grade_report(source, output, corpus, judge, directory) == 0
    graded = json.loads(output.read_text(encoding="utf-8"))
    assert seen == ["grade-2"] and graded["results"][0]["score"] == previous_score
    assert graded["judge"] == report["judge"] and graded["fixtures_sha256"] == report["fixtures_sha256"]
    assert graded["ready"] is True


@pytest.mark.asyncio
async def test_grading_requires_matching_json_protocol_and_prompt(grading_inputs, monkeypatch):
    source, output, corpus, judge, directory, report = grading_inputs
    report["judge"]["protocol"] = "json"
    report["judge_prompt_sha256"] = hashlib.sha256(runner.judge_prompt("json").encode()).hexdigest()
    source.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(ValueError, match="^judge_changed_requires_new_evaluation$"):
        await runner.grade_report(source, output, corpus, judge, directory)
    seen = []

    async def score(transport, case, result, recordings, protocol="tools"):
        seen.append(protocol)
        return {"answered": 0, "numbers": 0, "limitations": 0, "presentation": 0,
                "no_internal_identifiers": 0, "total": 0, "reasons": ["协议样本"], "model": judge.model}

    monkeypatch.setattr(runner, "judge_answer", score)
    assert await runner.grade_report(source, output, corpus, judge, directory, judge_protocol="json") == 0
    assert seen == ["json"]
    graded = json.loads(output.read_text(encoding="utf-8"))
    assert graded["judge"] == report["judge"] and graded["judge_prompt_sha256"] == report["judge_prompt_sha256"]


@pytest.mark.asyncio
async def test_json_posts_share_pacer_with_native_model_requests():
    from backend.agent_runtime.config import ModelConfig
    from backend.agent_runtime.model import ModelTransport

    waits, requests = [], []

    class CountingPacer:
        async def wait(self):
            waits.append("request")

    def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        assert request.method == "POST" and request.url.path == "/v1/chat/completions"
        if body["stream"]:
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"协议片段"}}]}\n\ndata: [DONE]\n\n')
        assert body["response_format"] == {"type": "json_object"}
        assert body["max_tokens"] == 8192 and "tools" not in body
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}]})

    common_pacer = CountingPacer()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        model = ModelTransport(ModelConfig("fixture-model", "https://model.invalid/v1", "fixture-key"), client=client)
        research = runner.PacedTransport(model, common_pacer)
        judge = runner.PacedTransport(model, common_pacer)
        async for _chunk in research.stream([], []):
            pass
        response = await judge.complete_json([{"role": "user", "content": "{}"}])
    assert response["choices"][0]["message"]["content"] == "{}"
    assert waits == ["request", "request"] and [request["stream"] for request in requests] == [True, False]


@pytest.mark.asyncio
@pytest.mark.parametrize("judge_protocol", ["tools", "external"])
@pytest.mark.parametrize("research_provider", ["fixture", "stepfun", "moxuna"])
async def test_run_case_uses_service_boundary_and_preserves_multiturn_failures(tmp_path, monkeypatch, judge_protocol, research_provider):
    from backend.agent_runtime import service, registry
    from backend.agent_runtime.config import ModelConfig
    from backend.agent_runtime.model import ModelTransport
    from backend.services import watchlist_store

    workspace = tmp_path / "workspace"
    eval_dir = workspace / "tests" / "agent_eval"
    monkeypatch.setattr(runner, "REPO", workspace)
    monkeypatch.setenv("FINSIGHT_ARTIFACT_DIR", "unchanged-outer-artifact-setting")
    subject = ModelConfig("fixture-subject", "https://subject.invalid/v1", "fixture-subject-key")
    if research_provider == "stepfun":
        monkeypatch.setenv("FINSIGHT_AGENT_STEPFUN_API_KEY", "research-stepfun-fixture-key")
        subject = runner.evaluation_model(None, "stepfun")
    elif research_provider == "moxuna":
        monkeypatch.setenv("FINSIGHT_EVAL_MOXUNA_API_BASE", "https://moxuna.invalid/v1")
        monkeypatch.setenv("FINSIGHT_EVAL_MOXUNA_API_KEY", "moxuna-fixture-key")
        monkeypatch.setenv("FINSIGHT_EVAL_MOXUNA_MODEL", "deepseek-v4.1-flash")
        subject = runner.evaluation_model(None, "moxuna")
    judge = ModelConfig("fixture-judge", "https://judge.invalid/v1", "fixture-judge-key")
    args = SimpleNamespace(mode="replay", run_id="protocol-fixture", timeout=20, no_judge=True,
                           judge_protocol=judge_protocol)
    case = {"id": "boundary", "group": "multiturn", "turns": ["问题一", "问题二", "问题三"],
            "fixtures": "fixtures/boundary", "expects": {"artifacts": []}}
    work = workspace / "tmp" / "agent-eval" / args.run_id / case["id"]
    service_calls, model_inputs, runtimes = [], [], []

    async def forbidden_send(*_args, **_kwargs):
        raise AssertionError("评测协议测试不得联网")

    def forbidden_database_store(*_args, **_kwargs):
        raise AssertionError("评测不得构造真实自选存储")

    class BoundaryRuntime:
        """只允许完整服务入口构造；不存在可供评测直接调用的简化循环。"""
        def __init__(self, **kwargs):
            self.model = kwargs["model"]
            self.history = kwargs["history"]
            self.context = kwargs["context"]
            self.tools = kwargs["tools"]
            self.limiter = kwargs["limiter"]
            runtimes.append(self)

    async def model_stream(self, messages, schemas, **_kwargs):
        assert self.config is subject
        model_inputs.append(deepcopy(messages))
        yield {"choices": [{"delta": {"content": "保留的公开答案"}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}}

    async def service_pipeline(**kwargs):
        index = len(service_calls)
        service_calls.append(kwargs)
        for name in ("FINSIGHT_ARTIFACT_DIR", "FINSIGHT_ACTION_STORE", "FINSIGHT_RUNTIME_QUOTA_DB"):
            assert Path(os.environ[name]).is_relative_to(work)
        assert os.environ["LANGGRAPH_CHECKPOINTER_BACKEND"] == "memory"
        assert os.environ["MONITOR_REALTIME_ENABLED"] == "false"
        assert kwargs["deps"].persist_run_event is None
        assert service.resolve_model() is subject
        runtime = service.AgentRuntime(context=kwargs["run_context"], session_id=kwargs["thread_id"],
            query=kwargs["query"], model=service.ModelTransport(service.resolve_model()), emit=None,
            history=kwargs["ui_context"]["session_history"], ui_context=kwargs["ui_context"])
        assert runtime.limiter.path.is_relative_to(work)
        assert runtime.tools == {}
        local_store = watchlist_store.get_watchlist_store()
        assert isinstance(local_store, runner.IsolatedWatchlist)
        local_store.add_item("AAPL", user_id="agent-eval", note="evaluation-only")
        local_store.add_item("AAPL", user_id="another-owner", note="must-not-leak")
        async for _chunk in runtime.model.stream([*runtime.history, {"role": "user", "content": kwargs["query"]}], []):
            pass
        kwargs["checkpoint"]({"response": "检查点", "committed_seq": 2})
        # 此调用若未被隔离，会进入生产用量归档。
        await kwargs["run_context"].archive_usage()
        yield {"type": "token", "runtime_type": "content.delta", "seq": 1, "content": "保留的公开答案"}
        yield {"type": "reasoning.delta", "runtime_type": "reasoning.delta", "seq": 2,
               "payload": {"delta": "private-reasoning"}}
        terminal = {"type": ("error", "cancelled", "done")[index], "seq": 3,
                    "response": ("失败前内容", "停止前内容", "最终内容")[index],
                    "run_status": ("failed", "cancelled", "completed")[index],
                    "blocks": [{"kind": "text", "content": "公开块"},
                               {"kind": "reasoning", "content": "private-reasoning"}]}
        if index == 0:
            terminal["code"] = "fixture_provider_error"
        if index == 2:
            # 重复终态不能被吞掉计数，即使最后一个终态仍为完成。
            yield {"type": "error", "seq": 3, "code": "fixture_duplicate_terminal", "response": "早期错误"}
        yield terminal

    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden_send)
    monkeypatch.setattr(watchlist_store, "WatchlistStore", forbidden_database_store)
    monkeypatch.setattr(service, "AgentRuntime", BoundaryRuntime)
    monkeypatch.setattr(service, "run_agent_pipeline", service_pipeline)
    monkeypatch.setattr(registry, "financial_tools", lambda: {})
    monkeypatch.setattr(ModelTransport, "stream", model_stream)
    result = await runner.run_case(case, subject, judge, args, eval_dir)

    assert len(service_calls) == len(runtimes) == 3
    assert [call["query"] for call in service_calls] == case["turns"]
    expected_history = [
        {"role": "user", "content": "问题一"}, {"role": "assistant", "content": "失败前内容"},
        {"role": "user", "content": "问题二"}, {"role": "assistant", "content": "停止前内容"},
    ]
    assert service_calls[0]["ui_context"]["session_history"] == []
    assert service_calls[2]["ui_context"]["session_history"] == expected_history
    assert service_calls[2]["ui_context"]["resume_from_run_id"] == result["turns"][1]["run_id"]
    assert model_inputs[2] == [*expected_history, {"role": "user", "content": "问题三"}]
    assert [turn["terminal"]["type"] for turn in result["turns"]] == ["error", "cancelled", "done"]
    assert result["turns"][0]["terminal"]["code"] == "fixture_provider_error"
    assert [turn["terminal_count"] for turn in result["turns"]] == [1, 1, 2]
    assert [turn["model_calls"] for turn in result["turns"]] == [1, 1, 1]
    assert all(block["kind"] != "reasoning" for turn in result["turns"] for block in turn["terminal"]["blocks"])
    assert result["structure"]["completed"] is False
    assert result["checkpoints"] == 3 and result["score"] is None
    assert result["watchlist"] == [{"ticker": "AAPL", "note": "evaluation-only"}]
    assert result["transport_errors"] == []
    if research_provider == "stepfun":
        assert result["cost_estimate"]["total_cny"] == pytest.approx(0.00039)
        assert result["cost_estimate"]["unpriced_calls"] == 0
    else:
        assert result["cost_estimate"]["total_cny"] is None
        assert result["cost_estimate"]["unpriced_calls"] == 3
    assert len(result["model_call_outcomes"]) == 3
    assert all(outcome["status"] == "completed" and outcome["received_chunks"] == 1
               for outcome in result["model_call_outcomes"])
    if judge_protocol == "external":
        from .external_judge import checksum
        reference = result["external_judge"]
        request = json.loads((workspace / reference["request_path"]).read_text(encoding="utf-8"))
        assert checksum(request) == reference["request_sha256"]
        assert request["input"]["answers"] == result["turns"]
        assert result["external_judge_verified"] is False
    assert os.environ["FINSIGHT_ARTIFACT_DIR"] == "unchanged-outer-artifact-setting"
    assert (workspace / result["events_path"]).is_relative_to(work)
    events = json.loads((workspace / result["events_path"]).read_text(encoding="utf-8"))
    assert [event["type"] for event in events if event["type"] in {"done", "error", "cancelled"}] == [
        "error", "cancelled", "error", "done"]
    assert not any(event["type"] == "reasoning.delta" for event in events)
    assert "private-reasoning" not in json.dumps(events)
    assert json.loads((work / "model_usage.json").read_text(encoding="utf-8")) == [
        {"prompt_tokens": 10, "completion_tokens": 3, "total_tokens": 13}] * 3


@pytest.mark.asyncio
async def test_current_evaluation_runs_real_service_with_isolated_model_protocol(tmp_path, monkeypatch):
    from backend.agent_runtime import registry
    from backend.agent_runtime.config import ModelConfig
    from backend.agent_runtime.model import ModelTransport

    workspace = tmp_path / "workspace"
    eval_dir = workspace / "tests" / "agent_eval"
    monkeypatch.setattr(runner, "REPO", workspace)
    monkeypatch.setattr(registry, "financial_tools", lambda: {})
    for key, value in {"FINSIGHT_AGENT_MIN_REQUEST_INTERVAL_SECONDS": "0",
                       "FINSIGHT_AGENT_TOKEN_BUDGET": "160000", "FINSIGHT_AGENT_TPM_LIMIT": "250000",
                       "FINSIGHT_AGENT_RPM_LIMIT": "30", "FINSIGHT_AGENT_MAX_TURNS": "4"}.items():
        monkeypatch.setenv(key, value)
    model = ModelConfig("fixture-subject", "https://model.invalid/v1", "fixture-key", context_window=65536)
    raw = "概念答案保留原文 12.345，以及 h_reference。"
    requests = []

    async def model_stream(self, messages, tools, **kwargs):
        requests.append((self.config, deepcopy(messages), deepcopy(tools)))
        yield {"choices": [{"delta": {"content": raw}, "finish_reason": "stop"}],
               "usage": {"prompt_tokens": 20, "completion_tokens": 10, "total_tokens": 30}}

    async def forbidden_send(*_args, **_kwargs):
        raise AssertionError("真实服务协议评测不得联网")

    monkeypatch.setattr(ModelTransport, "stream", model_stream)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden_send)
    args = SimpleNamespace(runtime="current", mode="replay", run_id="canonical-service", timeout=30, no_judge=True)
    case = {"id": "concept", "group": "concepts", "turns": ["解释概念"], "expects": {"no_data_tools": True}}
    result = await runner.run_case(case, model, None, args, eval_dir)
    assert result["structure"]["completed"] is True, result["turns"][0]["terminal"]
    assert result["turns"][0]["terminal"]["response"] == raw
    assert result["turns"][0]["terminal_count"] == result["turns"][0]["model_calls"] == 1
    assert len(requests) == 1 and requests[0][0] is model
    assert result["structure"]["tool_calls"] == 0
    assert result["transport_errors"] == []
    assert (workspace / result["events_path"]).is_relative_to(workspace / "tmp" / "agent-eval")


def test_frozen_raw_tool_registry_matches_candidate_without_switching_runtime(monkeypatch):
    import socket
    import backend.agent_runtime as runtime_package
    from backend.agent_runtime import registry
    from agent_eval.baseline_runtime import tools as baseline_tools

    def forbidden(*_args, **_kwargs):
        raise AssertionError("加载工具定义不得联网")
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    candidate_path = list(runtime_package.__path__)
    candidate, baseline = registry.financial_tools(), baseline_tools.financial_tools()
    assert candidate.keys() == baseline.keys()
    assert all(spec.enveloped for spec in candidate.values())
    assert all(not getattr(spec, "enveloped", False) for spec in baseline.values())
    assert list(runtime_package.__path__) == candidate_path


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,enveloped", [("record", True), ("replay", True), ("record", False), ("replay", False)])
async def test_run_case_loads_independent_raw_tools_only_for_candidate_record(tmp_path, monkeypatch, mode, enveloped):
    import backend.agent_runtime as runtime_package
    from backend.agent_runtime import service, registry
    from backend.agent_runtime.config import ModelConfig
    from agent_eval.baseline_runtime import tools as baseline_tools

    candidate_path = list(runtime_package.__path__)
    workspace = tmp_path / "workspace"
    eval_dir = workspace / "tests" / "agent_eval"
    monkeypatch.setattr(runner, "REPO", workspace)
    args = SimpleNamespace(mode=mode, run_id="raw-entry-fixture", timeout=20, no_judge=True)
    case = {"id": "recording", "group": "facts", "turns": ["合成协议输入"], "expects": {}}
    tool_args = {"ticker": "SYNTH"}
    raw = {"status": "ok", "price": 42.25, "currency": "USD"}
    calls, imports = [], []
    def raw_invoke(arguments):
        calls.append(arguments)
        return raw
    def forbidden(*_args, **_kwargs):
        raise AssertionError("录制入口测试不得额外调用工具或联网")
    spec = registry.ToolSpec("get_stock_price", "合成工具", {"type": "object"},
                          forbidden if enveloped or mode == "replay" else raw_invoke, True, enveloped)
    legacy = baseline_tools.ToolSpec(spec.name, spec.description, spec.parameters, raw_invoke, True)
    monkeypatch.setattr(registry, "financial_tools", lambda: {spec.name: spec})
    monkeypatch.setattr(baseline_tools, "financial_tools", lambda: {legacy.name: legacy})
    original_import = builtins.__import__
    def observed_import(name, *positional, **keywords):
        if name == "agent_eval.baseline_runtime.tools":
            assert mode == "record" and enveloped
            imports.append(name)
        return original_import(name, *positional, **keywords)
    monkeypatch.setattr(builtins, "__import__", observed_import)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden)
    monkeypatch.setattr(service, "AgentRuntime", lambda **kwargs: SimpleNamespace(**kwargs))
    tape_path = eval_dir / "fixtures" / case["id"]
    if mode == "replay":
        runner.ToolTape(tape_path, "record").invoke(spec.name, tool_args, lambda _: raw)
    async def pipeline(**kwargs):
        assert kwargs["query"] == case["turns"][0]
        runtime = service.AgentRuntime()
        output = runtime.tools[spec.name].invoke(tool_args)
        assert output["data"] == raw if enveloped else output == raw
        yield {"type": "done", "response": "合成公开答案", "run_status": "completed"}
    monkeypatch.setattr(service, "run_agent_pipeline", pipeline)
    config = ModelConfig("fixture-model", "https://fixture.invalid/v1", "fixture-key")
    result = await runner.run_case(case, config, None, args, eval_dir)

    assert calls == ([tool_args] if mode == "record" else [])
    assert imports == (["agent_eval.baseline_runtime.tools"] if mode == "record" and enveloped else [])
    assert list(runtime_package.__path__) == candidate_path
    assert registry.ToolSpec is not baseline_tools.ToolSpec
    assert runner.ToolTape(tape_path, "replay").records()[0]["raw_output"] == raw
    assert result["turns"][0]["model_calls"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("received", [False, True])
async def test_run_case_persists_cancellation_outcome_without_http_failure_label(tmp_path, monkeypatch, received):
    from backend.agent_runtime import service, registry
    from backend.agent_runtime.config import ModelConfig
    from backend.agent_runtime.model import ModelTransport

    workspace = tmp_path / "w"
    eval_dir = workspace / "tests" / "agent_eval"
    monkeypatch.setattr(runner, "REPO", workspace)
    subject = ModelConfig("fixture-subject", "https://fixture.invalid/v1", "fixture-key")
    args = SimpleNamespace(mode="replay", run_id="cancel-fixture", timeout=20, no_judge=True)
    case = {"id": "cancel", "group": "concepts", "turns": ["协议输入"], "expects": {}}

    class Runtime:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    async def blocked_stream(self, *_args, **_kwargs):
        if received:
            yield {"choices": [{"delta": {"reasoning_content": "private-provider-reasoning"}}]}
        await asyncio.Event().wait()
        yield {}

    async def pipeline(**kwargs):
        runtime = service.AgentRuntime(model=service.ModelTransport(service.resolve_model()),
                                       context=kwargs["run_context"], history=[], emit=None)
        try:
            async with asyncio.timeout(0.01):
                async for _chunk in runtime.model.stream([{"role": "user", "content": "协议输入"}], [], timeout=20):
                    pass
        except TimeoutError:
            yield {"type": "error", "error_code": "fixture_caller_timeout", "response": "", "run_status": "failed"}

    async def forbidden_send(*_args, **_kwargs):
        raise AssertionError("取消观测测试不得联网")

    monkeypatch.setattr(service, "AgentRuntime", Runtime)
    monkeypatch.setattr(service, "run_agent_pipeline", pipeline)
    monkeypatch.setattr(registry, "financial_tools", lambda: {})
    monkeypatch.setattr(ModelTransport, "stream", blocked_stream)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden_send)
    result = await runner.run_case(case, subject, None, args, eval_dir)
    assert result["transport_errors"] == [] and result["structure"]["completed"] is False
    assert result["turns"][0]["terminal"]["error_code"] == "fixture_caller_timeout"
    outcome = result["model_call_outcomes"][0]
    assert outcome["status"] == "cancelled" and outcome["received_chunks"] == int(received)
    assert "error_code" not in outcome
    path = workspace / "tmp" / "agent-eval" / args.run_id / case["id"] / "model_call_outcomes.json"
    assert json.loads(path.read_text(encoding="utf-8")) == result["model_call_outcomes"]
    assert "private-provider-reasoning" not in path.read_text(encoding="utf-8")


def synthetic_measurement_report():
    """完整测量前提的合成数据，不代表已运行的真实模型或真实题目。"""
    score = {"answered": 0, "numbers": 0, "limitations": 0, "presentation": 0,
             "no_internal_identifiers": 0, "reasons": ["合成零分样本"], "total": 0, "model": "fixture-judge"}
    row = {"id": "fixture-1", "group": "facts", "model": "fixture-subject", "score": score,
           "tape": {"misses": 0}, "transport_errors": [], "elapsed_seconds": 1,
           "turns": [{"terminal": {"type": "done", "response": "合成回答"}, "terminal_count": 1, "model_calls": 1}],
           "model_call_outcomes": [{"model": "fixture-subject", "status": "completed", "received_chunks": 1, "synthetic": True}],
           "structure": {"completed": True, "single_terminal_per_turn": True, "references_valid": True,
                         "artifacts_met": True, "no_actions_met": True, "tokens": 10, "rounds": 1, "tool_error_rate": 0}}
    return {"expected_cases": 1, "results": [row], "judge": {"model": "fixture-judge", "protocol": "tools"}}


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime", ["current", "baseline"])
@pytest.mark.parametrize("external_artifacts", [False, True])
async def test_eval_entry_switch_keeps_same_per_turn_budget_for_both_runtimes(tmp_path, monkeypatch, runtime, external_artifacts):
    from backend.agent_runtime import service
    from backend.agent_runtime.config import ModelConfig
    from backend.services.run_context import run_budget_seconds

    monkeypatch.setenv("LANGGRAPH_EXECUTION_TIMEOUT_REPORT_SECONDS", "600")
    assert run_budget_seconds("investment_report") == 600
    workspace = tmp_path / "workspace"
    monkeypatch.setattr(runner, "REPO", workspace)
    if external_artifacts:
        monkeypatch.setenv("FINSIGHT_EVAL_ARTIFACT_ROOT", str(tmp_path / "external-artifacts"))
    args = SimpleNamespace(mode="replay", runtime=runtime, run_id="budget-fixture", timeout=300, no_judge=True)
    case = {"id": "same-budget", "group": "concepts", "turns": ["协议问题一", "协议问题二"], "expects": {}}
    seen = []

    async def pipeline(**kwargs):
        context = kwargs["run_context"]
        original_deadline = context.deadline
        context.select_entry("investment_report")
        assert context.entry == "investment_report"
        assert context.deadline == pytest.approx(original_deadline, abs=0.01)
        context.select_entry("chat")
        assert context.deadline == pytest.approx(original_deadline, abs=0.01)
        seen.append(context.remaining_seconds)
        yield {"type": "done", "response": "合成协议答案", "run_status": "completed"}

    async def forbidden_send(*_args, **_kwargs):
        raise AssertionError("预算边界验证不得联网")

    monkeypatch.setattr(service, "run_agent_pipeline", pipeline)
    monkeypatch.setattr(httpx.AsyncClient, "send", forbidden_send)
    model = ModelConfig("fixture", "https://fixture.invalid/v1", "fixture-key")
    result = await runner.run_case(case, model, None, args, workspace / "tests/agent_eval")
    assert len(seen) == 2 and all(299 < seconds <= 300 for seconds in seen)
    assert result["structure"]["completed"] is True
    assert run_budget_seconds("investment_report") == 600
    event_path = runner.resolve_evaluation_file(result["events_path"])
    assert event_path.is_relative_to(runner.evaluation_artifact_root()) and event_path.is_file()
    assert Path(result["events_path"]).is_absolute() is external_artifacts


def test_external_artifact_references_cannot_escape_explicit_root(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "REPO", tmp_path / "workspace")
    configured = tmp_path / "external-artifacts"
    monkeypatch.setenv("FINSIGHT_EVAL_ARTIFACT_ROOT", str(configured))
    path = configured / "case/events.json"
    reference = runner.evaluation_file_reference(path)
    assert Path(reference).is_absolute() and runner.resolve_evaluation_file(reference) == path
    outside = tmp_path / "unrelated-file.json"
    with pytest.raises(ValueError, match="evaluation_artifact_reference_outside_configured_root"):
        runner.evaluation_file_reference(outside)
    with pytest.raises(ValueError, match="evaluation_artifact_reference_outside_configured_root"):
        runner.resolve_evaluation_file(str(outside))


def test_measured_model_timeout_keeps_zero_score_and_reduced_completion_rate():
    report = synthetic_measurement_report()
    failed = deepcopy(report["results"][0])
    failed["id"] = "fixture-2"
    failed["transport_errors"] = [{"code": "model_timeout", "recovered": False}]
    failed["turns"][0]["terminal"] = {"type": "error", "error_code": "model_timeout", "response": ""}
    failed["structure"]["completed"] = False
    failed["model_call_outcomes"] = [{"model": "fixture-subject", "status": "failed", "error_code": "model_timeout", "received_chunks": 0}]
    report["results"].append(failed)
    report["expected_cases"] = 2
    preserved = deepcopy(report)
    assert runner.report_ready(report) is True
    groups = runner.summarize(report["results"])
    assert groups["facts"]["completed_rate"] == 0.5 and groups["facts"]["scores"]["total"] == 0
    assert groups["facts"]["model_failure_rate"] == 0.5
    assert report == preserved


@pytest.mark.parametrize("failure", ["no_success", "account_401", "account_403", "connection", "unknown_transport",
                                     "missing_score", "invalid_score", "missing_tape", "invalid_measurement",
                                     "measurement_error", "incomplete_capture", "duplicate_id", "no_terminal", "missing_model_outcome"])
def test_incomplete_or_unusable_measurements_do_not_become_ready(failure):
    report = synthetic_measurement_report()
    row = report["results"][0]
    if failure == "no_success":
        row["model_call_outcomes"][0].update(status="cancelled", received_chunks=0)
    elif failure in {"account_401", "account_403", "connection", "unknown_transport"}:
        code = {"account_401": "model_http_401", "account_403": "model_http_403",
                "connection": "model_connection_error", "unknown_transport": "unknown_transport_failure"}[failure]
        row["transport_errors"] = [{"code": code, "recovered": False}]
    elif failure == "missing_score":
        row["score"] = None
    elif failure == "invalid_score":
        row["score"]["answered"] = True
    elif failure == "missing_tape":
        row["tape"]["misses"] = 1
    elif failure == "invalid_measurement":
        report["measurement_valid"] = False
    elif failure == "measurement_error":
        row["measurement_errors"] = [{"code": "fixture_parser_error"}]
    elif failure == "incomplete_capture":
        row["capture_complete"] = False
    elif failure == "duplicate_id":
        report["results"].append(deepcopy(row))
        report["expected_cases"] = 2
    elif failure == "no_terminal":
        row["turns"][0]["terminal_count"] = 0
        row["turns"][0]["terminal"] = {"type": "error", "error_code": "terminal_missing"}
    else:
        row["model_call_outcomes"] = []
    assert runner.report_ready(report) is False


def test_complete_capture_of_duplicate_terminals_is_measurable_protocol_failure():
    report = synthetic_measurement_report()
    row = report["results"][0]
    row["turns"][0]["terminal_count"] = 2
    row["structure"].update(single_terminal_per_turn=False, completed=False)
    assert runner.report_ready(report) is True
    groups = runner.summarize(report["results"])
    assert groups["facts"]["single_terminal_rate"] == 0 and groups["facts"]["completed_rate"] == 0


def test_caller_budget_cancellation_is_measurable_when_another_call_completed():
    report = synthetic_measurement_report()
    row = report["results"][0]
    row["model_call_outcomes"].append({"model": "fixture-subject", "status": "cancelled", "received_chunks": 0})
    row["turns"][0].update(model_calls=2, terminal={"type": "cancelled", "response": ""})
    row["structure"]["completed"] = False
    assert runner.report_ready(report) is True
    assert runner.summarize(report["results"])["facts"]["model_failure_rate"] == 0.5


def test_recovered_connection_is_preserved_but_not_account_refusal():
    report = synthetic_measurement_report()
    row = report["results"][0]
    row["transport_errors"] = [{"code": "model_connection_error", "recovered": True}]
    assert runner.report_ready(report) is True
    row["transport_errors"] = [{"code": "model_http_403", "recovered": True}]
    assert runner.report_ready(report) is False


def test_ready_baseline_is_not_a_claim_that_product_acceptance_passed():
    report = synthetic_measurement_report()
    report["product_acceptance"] = {"passed": False, "queries_passed": 0, "queries_total": 48}
    assert runner.report_ready(report) is True
    assert report["product_acceptance"]["passed"] is False

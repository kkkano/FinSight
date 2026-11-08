"""隔离调度协议测试；模拟 Docker，不在测试进程执行用户代码。"""
from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from backend.analysis_worker.app import create_app, run_connected
from backend.analysis_worker import dispatcher as dispatcher_module
from backend.analysis_worker.dispatcher import Dispatcher, DockerCLI, Settings, available_memory_mb as read_meminfo
from backend.analysis_worker.protocol import (
    AnalysisError, JobRequest, MAX_LOG_BYTES, MAX_REQUEST_BYTES, MAX_RESULT_BYTES,
)


TOKEN = "test-only-worker-token-0000000000000000"
IMAGE_ID = "sha256:" + "a" * 64


@pytest.fixture(autouse=True)
def memory_capacity(monkeypatch):
    monkeypatch.setattr(dispatcher_module, "available_memory_mb", lambda: 2048)


class FakeDocker:
    def __init__(self):
        self.calls = []
        self.info = {"OSType": "linux", "MemoryLimit": True, "SwapLimit": True, "PidsLimit": True,
                     "CpuCfsQuota": True, "CpuCfsPeriod": True,
                     "MemTotal": 2 * 1024 ** 3, "SecurityOptions": ["name=seccomp,profile=builtin"]}
        self.output = json.dumps({"status": "ok", "result": {"mean": 2}, "logs": "完成"}).encode()
        self.state = {"ExitCode": 0, "OOMKilled": False, "Running": False}
        self.block_job = False
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cleanup_failed = False
        self.fail_create = False
        self.recovery_containers = []
        self.recovery_volumes = []

    async def command(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if args[0] == "info":
            return 0, json.dumps(self.info).encode(), b""
        if args[:2] == ["image", "inspect"]:
            return 0, json.dumps({"Os": "linux", "Id": IMAGE_ID, "Config": {
                "User": "65532:65532", "Entrypoint": ["python", "-I", "/opt/analysis/runner.py"]}}).encode(), b""
        if "ls" in args:
            if any(arg.startswith("label=") for arg in args):
                names = self.recovery_containers if args[0] == "container" else self.recovery_volumes
                return 0, "\n".join(names).encode(), b""
            return 0, b"still-running" if self.cleanup_failed else b"", b""
        if args[:2] == ["container", "create"] and self.fail_create:
            return 125, b"", b"daemon-private-detail"
        if args[:2] == ["container", "start"] and args[-1].endswith("-run"):
            self.started.set()
            if self.block_job:
                await self.release.wait()
            return 0, self.output, b""
        if args[:2] == ["container", "inspect"]:
            state = self.state if args[-1].endswith("-run") else {"ExitCode": 0, "Running": False}
            return 0, json.dumps(state).encode(), b""
        return 0, b"", b""


def settings(**kwargs):
    return replace(Settings(enabled=True, token=TOKEN), **kwargs)


def job(**kwargs):
    return replace(JobRequest(code="result = {'mean': 2}", datasets={"dataset_fixture": {"rows": [1, 2, 3]}}), **kwargs)


def worker(cli=None, **kwargs):
    return Dispatcher(settings(**kwargs), cli or FakeDocker())


@pytest.mark.asyncio
async def test_job_mounts_only_its_input_and_sets_all_isolation_limits():
    cli = FakeDocker()
    dispatcher = worker(cli)
    await dispatcher.initialize()
    result = await dispatcher.run(job(code="result = pd.DataFrame(datasets['dataset_fixture']).shape"))
    assert result["status"] == "ok"
    assert result["code_hash"] and result["input_hash"] and result["duration_ms"] >= 0
    creates = [args for args, _ in cli.calls if args[:2] == ["container", "create"]]
    stage, runner = creates
    for args in creates:
        for key, expected in {"--network": "none", "--cap-drop": "ALL", "--security-opt": "no-new-privileges:true",
                              "--memory": "512m", "--memory-swap": "512m", "--cpus": "1.0",
                              "--pids-limit": "64", "--log-driver": "none", "--ipc": "private",
                              "--cgroupns": "private"}.items():
            assert args[args.index(key) + 1] == expected
        assert "--read-only" in args
        assert "--env" not in args and "--env-file" not in args and "--privileged" not in args
        assert "docker.sock" not in " ".join(args) and TOKEN not in " ".join(args)
        assert "noexec,nosuid,nodev" in args[args.index("--tmpfs") + 1]
    assert runner[runner.index("--user") + 1] == "65532:65532"
    assert runner[-1] == IMAGE_ID
    assert runner[runner.index("--mount") + 1].endswith(",readonly")
    assert ",readonly" not in stage[stage.index("--mount") + 1]
    assert stage[-1] == "stage"
    staged = [opts["input_bytes"] for _, opts in cli.calls if "input_bytes" in opts]
    assert len(staged) == 1 and json.loads(staged[0])["datasets"] == job().datasets
    assert all("result =" not in " ".join(args) for args, _ in cli.calls)
    assert any(args[:3] == ["container", "rm", "--force"] for args, _ in cli.calls)
    assert any(args[:2] == ["volume", "rm"] for args, _ in cli.calls)


@pytest.mark.asyncio
async def test_task_inputs_use_different_volumes_and_containers():
    cli = FakeDocker()
    dispatcher = worker(cli)
    await dispatcher.initialize()
    await dispatcher.run(job())
    await dispatcher.run(job())
    volumes = [args[-1] for args, _ in cli.calls if args[:2] == ["volume", "create"]]
    assert len(volumes) == len(set(volumes)) == 2
    names = [args[args.index("--name") + 1] for args, _ in cli.calls if args[:2] == ["container", "create"]]
    assert len(names) == len(set(names)) == 4


@pytest.mark.asyncio
async def test_available_memory_is_checked_for_every_job_before_any_docker_mutation(monkeypatch):
    cli = FakeDocker()
    dispatcher = worker(cli)
    await dispatcher.initialize()
    before = len(cli.calls)
    monkeypatch.setattr(dispatcher_module, "available_memory_mb", lambda: 263)
    result = await dispatcher.run(job())
    assert result == {"status": "error", "error": "analysis_capacity_insufficient",
                      "available_memory_mb": 263, "required_memory_mb": 768}
    assert len(cli.calls) == before and not dispatcher.active
    monkeypatch.setattr(dispatcher_module, "available_memory_mb", lambda: 768)
    assert (await dispatcher.run(job()))["status"] == "ok"
    monkeypatch.setattr(dispatcher_module, "available_memory_mb", lambda: 767)
    before = len(cli.calls)
    assert (await dispatcher.run(job()))["error"] == "analysis_capacity_insufficient"
    assert len(cli.calls) == before


@pytest.mark.asyncio
async def test_missing_memavailable_fails_closed_without_docker_calls(monkeypatch):
    dispatcher = worker()
    await dispatcher.initialize()
    before = len(dispatcher.cli.calls)

    def unavailable():
        raise AnalysisError("analysis_capacity_unavailable")

    monkeypatch.setattr(dispatcher_module, "available_memory_mb", unavailable)
    assert (await dispatcher.run(job()))["error"] == "analysis_capacity_unavailable"
    assert len(dispatcher.cli.calls) == before


def test_memory_environment_configuration_is_bounded(monkeypatch):
    monkeypatch.setenv("FINSIGHT_ANALYSIS_ENABLED", "1")
    monkeypatch.setenv("FINSIGHT_ANALYSIS_WORKER_TOKEN", TOKEN)
    monkeypatch.setenv("FINSIGHT_ANALYSIS_JOB_MEMORY_MB", "256")
    monkeypatch.setenv("FINSIGHT_ANALYSIS_MEMORY_RESERVE_MB", "384")
    assert Settings.from_env().configured()
    assert Settings.from_env().memory_mb + Settings.from_env().reserve_memory_mb == 640
    monkeypatch.setenv("FINSIGHT_ANALYSIS_MEMORY_RESERVE_MB", "0")
    assert not Settings.from_env().configured()
    monkeypatch.setenv("FINSIGHT_ANALYSIS_MEMORY_RESERVE_MB", "invalid")
    assert not Settings.from_env().configured()


@pytest.mark.parametrize("raw,expected", [("MemAvailable: 270336 kB\nSwapFree: 9999999 kB\n", 264),
                                         ("MemAvailable: 786431 kB\n", 767)])
def test_meminfo_uses_available_physical_memory_only(tmp_path, monkeypatch, raw, expected):
    source = tmp_path / "meminfo"
    source.write_text(raw, encoding="ascii")
    monkeypatch.setattr(dispatcher_module, "Path", lambda _: source)
    assert read_meminfo() == expected


@pytest.mark.parametrize("raw", ["MemFree: 9999999 kB\n", "MemAvailable: invalid kB\n", ""])
def test_meminfo_does_not_invent_a_fallback(tmp_path, monkeypatch, raw):
    source = tmp_path / "meminfo"
    source.write_text(raw, encoding="ascii")
    monkeypatch.setattr(dispatcher_module, "Path", lambda _: source)
    with pytest.raises(AnalysisError, match="analysis_capacity_unavailable"):
        read_meminfo()


@pytest.mark.asyncio
@pytest.mark.parametrize("change,error", [
    ({"OSType": "windows"}, "analysis_isolation_unavailable"),
    ({"SecurityOptions": []}, "analysis_isolation_unavailable"),
    ({"MemoryLimit": False}, "analysis_isolation_unavailable"),
    ({"SwapLimit": False}, "analysis_isolation_unavailable"),
    ({"PidsLimit": False}, "analysis_isolation_unavailable"),
    ({"CpuCfsQuota": False}, "analysis_isolation_unavailable"),
    ({"CpuCfsPeriod": False}, "analysis_isolation_unavailable"),
    ({"MemTotal": 256 * 1024 ** 2}, "analysis_capacity_insufficient"),
])
async def test_unavailable_isolation_never_dispatches(change, error):
    cli = FakeDocker()
    cli.info.update(change)
    dispatcher = worker(cli)
    await dispatcher.initialize()
    assert not dispatcher.ready
    assert (await dispatcher.run(job()))["error"] == error
    assert not any("create" in args for args, _ in cli.calls)


@pytest.mark.asyncio
async def test_startup_recovers_only_owned_previous_resources():
    cli = FakeDocker()
    prefix = "finsight-analysis-" + "1" * 32
    cli.recovery_containers = [prefix + "-run"]
    cli.recovery_volumes = [prefix + "-input"]
    dispatcher = worker(cli)
    await dispatcher.initialize()
    assert dispatcher.ready
    assert ["container", "rm", "--force", prefix + "-run"] in [args for args, _ in cli.calls]
    assert ["volume", "rm", prefix + "-input"] in [args for args, _ in cli.calls]


@pytest.mark.asyncio
@pytest.mark.parametrize("config", [{"User": "0"}, {"Volumes": {"/data": {}}}, {"Entrypoint": ["sh"]}])
async def test_job_image_cannot_replace_runner_or_add_shared_volumes(config):
    cli = FakeDocker()
    previous = cli.command

    async def altered(args, **kwargs):
        code, stdout, stderr = await previous(args, **kwargs)
        if args[:2] == ["image", "inspect"]:
            value = json.loads(stdout)
            value["Config"].update(config)
            stdout = json.dumps(value).encode()
        return code, stdout, stderr

    cli.command = altered
    dispatcher = worker(cli)
    await dispatcher.initialize()
    assert not dispatcher.ready and dispatcher.error == "analysis_image_invalid"


@pytest.mark.asyncio
async def test_missing_docker_does_not_fallback_to_local_execution(monkeypatch):
    spawn = AsyncMock(side_effect=FileNotFoundError("no-docker"))
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    dispatcher = Dispatcher(settings())
    await dispatcher.initialize()
    assert not dispatcher.ready and dispatcher.error == "analysis_docker_unavailable"
    assert (await dispatcher.run(job()))["error"] == "analysis_docker_unavailable"
    assert spawn.call_count == 1 and spawn.call_args.args[0] == "docker"


@pytest.mark.asyncio
async def test_cancel_during_create_waits_for_rpc_then_cleans_result():
    cli = FakeDocker()
    original = cli.command
    creating, release = asyncio.Event(), asyncio.Event()

    async def delayed(args, **kwargs):
        if args[:2] == ["volume", "create"]:
            creating.set()
            await release.wait()
        return await original(args, **kwargs)

    cli.command = delayed
    dispatcher = worker(cli)
    await dispatcher.initialize()
    task = asyncio.create_task(dispatcher.run(job()))
    await creating.wait()
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert any(args[:2] == ["volume", "rm"] for args, _ in cli.calls)
    assert not dispatcher.active


@pytest.mark.asyncio
@pytest.mark.parametrize("mode,error", [("timeout", "analysis_timeout"), ("oom", "analysis_memory_limit"),
                                         ("create", "analysis_docker_failed"), ("invalid", "analysis_protocol_invalid"),
                                         ("exit", "analysis_code_failed"), ("output", "analysis_output_limit")])
async def test_failures_have_stable_codes_and_always_cleanup(mode, error):
    cli = FakeDocker()
    cli.block_job = mode == "timeout"
    cli.fail_create = mode == "create"
    if mode == "oom":
        cli.state = {"ExitCode": 137, "OOMKilled": True}
    elif mode == "exit":
        cli.state = {"ExitCode": 1, "OOMKilled": False}
    elif mode == "invalid":
        cli.output = b"user stdout is not a protocol envelope"
    elif mode == "output":
        cli.output = json.dumps({"status": "ok", "result": "x" * (MAX_RESULT_BYTES + 1)}).encode()
    dispatcher = worker(cli, timeout_seconds=0.03 if mode == "timeout" else 15)
    await dispatcher.initialize()
    result = await dispatcher.run(job())
    assert {key: result[key] for key in ("status", "error")} == {"status": "error", "error": error}
    assert result["allocated_memory_mb"] == 512
    assert not dispatcher.active
    assert any(args[:3] == ["container", "rm", "--force"] for args, _ in cli.calls)
    assert any(args[:2] == ["volume", "rm"] for args, _ in cli.calls)
    assert "daemon-private-detail" not in str(result)


@pytest.mark.asyncio
async def test_cancellation_removes_container_tree_and_volume_before_propagating():
    cli = FakeDocker()
    cli.block_job = True
    dispatcher = worker(cli)
    await dispatcher.initialize()
    task = asyncio.create_task(dispatcher.run(job()))
    await cli.started.wait()
    assert (await dispatcher.run(job()))["error"] == "analysis_worker_busy"
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert not dispatcher.active
    assert any(args[:3] == ["container", "rm", "--force"] for args, _ in cli.calls)
    assert any(args[:2] == ["volume", "rm"] for args, _ in cli.calls)


@pytest.mark.asyncio
async def test_cleanup_failure_disables_service_and_does_not_claim_success():
    cli = FakeDocker()
    cli.cleanup_failed = True
    dispatcher = worker(cli)
    await dispatcher.initialize()
    result = await dispatcher.run(job())
    assert result == {"status": "error", "error": "analysis_cleanup_failed"}
    assert not dispatcher.ready
    previous = len(cli.calls)
    assert (await dispatcher.run(job()))["error"] == "analysis_cleanup_failed"
    assert len(cli.calls) == previous


@pytest.mark.asyncio
async def test_http_disconnect_waits_for_cancellation_cleanup():
    cli = FakeDocker()
    cli.block_job = True
    dispatcher = worker(cli)
    await dispatcher.initialize()
    request = type("Request", (), {"is_disconnected": AsyncMock(return_value=True)})()
    result = await run_connected(request, dispatcher, job())
    assert result["error"] == "analysis_cancelled"
    assert not dispatcher.active
    assert any(args[:2] == ["volume", "rm"] for args, _ in cli.calls)


@pytest.mark.parametrize("changes", [{"path": "/etc/passwd"}, {"code": "a" * 16001}, {"datasets": {}},
                                    {"timeout_seconds": 61}, {"timeout_seconds": True}, {"timeout_seconds": 0}])
def test_request_validation(changes):
    payload = {"code": "result = 1", "datasets": {"dataset_a": [1]}, **changes}
    with pytest.raises(AnalysisError):
        JobRequest.from_bytes(json.dumps(payload).encode())


def test_non_finite_json_is_not_accepted():
    with pytest.raises(AnalysisError, match="analysis_request_invalid"):
        JobRequest.from_bytes(b'{"code":"result=1","datasets":{"x":NaN}}')


@pytest.mark.parametrize("settings_value", [Settings(), settings(token="short"), settings(enabled=False)])
def test_unconfigured_http_service_fails_closed(settings_value):
    cli = FakeDocker()
    with TestClient(create_app(settings_value, Dispatcher(settings_value, cli))) as client:
        assert client.get("/health").status_code == 503
        assert client.post("/jobs", json={}).status_code == 503
    assert cli.calls == []


def test_http_authorization_size_validation_and_success():
    dispatcher = worker()
    with TestClient(create_app(dispatcher.settings, dispatcher)) as client:
        assert client.get("/health").json()["ready"]
        payload = {"code": "result = 2", "datasets": {"dataset_x": [1, 2, 3]}}
        assert client.post("/jobs", json=payload).status_code == 401
        headers = {"Authorization": "Bearer " + TOKEN}
        assert client.post("/jobs", json={**payload, "path": "/host"}, headers=headers).status_code == 422
        response = client.post("/jobs", content=b" " * (MAX_REQUEST_BYTES + 1),
                               headers={**headers, "Content-Type": "application/json"})
        assert response.status_code == 413
        response = client.post("/jobs", json=payload, headers=headers)
        assert response.status_code == 200 and response.json()["result"] == {"mean": 2}
        assert response.json()["logs"] == "完成"


@pytest.mark.asyncio
@pytest.mark.parametrize("stream_name", ["stdout", "stderr"])
async def test_cli_output_limits_use_exec_and_kill_cli(monkeypatch, stream_name):
    class Process:
        def __init__(self):
            self.returncode = None
            self.stdin = None
            self.stdout = asyncio.StreamReader()
            self.stderr = asyncio.StreamReader()
            self.ended = asyncio.Event()

        async def wait(self):
            await self.ended.wait()
            return self.returncode

        def kill(self):
            self.returncode = -9
            self.ended.set()

    process = Process()
    getattr(process, stream_name).feed_data(b"x" * (MAX_LOG_BYTES + 1))
    process.stdout.feed_eof()
    process.stderr.feed_eof()
    spawn = AsyncMock(return_value=process)
    monkeypatch.setattr(asyncio, "create_subprocess_exec", spawn)
    with pytest.raises(AnalysisError, match="analysis_output_limit"):
        await DockerCLI().command(["container", "start", "--attach", "job"], stdout_limit=MAX_LOG_BYTES)
    assert spawn.call_args.args[0] == "docker"
    assert "shell" not in spawn.call_args.kwargs
    assert process.returncode == -9

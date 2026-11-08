"""Docker CLI 作业调度；所有用户代码均留在独立容器内。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .protocol import (
    AnalysisError, JobRequest, MAX_LOG_BYTES, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES,
    MAX_RESULT_BYTES, MAX_SECONDS, strict_json,
)

LABEL = "finsight.analysis.worker"
RESOURCE_NAME = re.compile(r"^finsight-analysis-[a-f0-9]{32}-(stage|run|input)$")
RUNNER_ERRORS = {
    "analysis_result_missing", "analysis_output_limit", "analysis_code_or_result_invalid",
    "analysis_code_failed",
    "analysis_memory_limit",
}


def available_memory_mb() -> int:
    """读取计算宿主当前可用物理内存，不将 swap 计入新作业额度。"""
    try:
        raw = Path("/proc/meminfo").read_text(encoding="ascii")
    except (OSError, UnicodeError):
        raise AnalysisError("analysis_capacity_unavailable") from None
    match = re.search(r"^MemAvailable:\s+(\d+)\s+kB\s*$", raw, re.MULTILINE)
    if not match:
        raise AnalysisError("analysis_capacity_unavailable")
    return int(match.group(1)) // 1024


@dataclass(frozen=True)
class Settings:
    enabled: bool = False
    token: str = field(default="", repr=False)
    image: str = "finsight-compute-job:local"
    worker_id: str = "default"
    timeout_seconds: float = 15.0
    memory_mb: int = 512
    reserve_memory_mb: int = 256
    adaptive_memory: bool = False
    min_memory_mb: int = 128
    cpus: float = 1.0
    pids: int = 64

    @classmethod
    def from_env(cls) -> "Settings":
        try:
            memory_mb = int(os.getenv("FINSIGHT_ANALYSIS_JOB_MEMORY_MB", "512"))
            reserve_memory_mb = int(os.getenv("FINSIGHT_ANALYSIS_MEMORY_RESERVE_MB", "256"))
            min_memory_mb = int(os.getenv("FINSIGHT_ANALYSIS_MIN_JOB_MEMORY_MB", "128"))
        except ValueError:
            return cls()
        return cls(enabled=os.getenv("FINSIGHT_ANALYSIS_ENABLED") == "1",
                   token=os.getenv("FINSIGHT_ANALYSIS_WORKER_TOKEN", ""),
                   image=os.getenv("FINSIGHT_ANALYSIS_JOB_IMAGE", "finsight-compute-job:local"),
                   worker_id=os.getenv("FINSIGHT_ANALYSIS_WORKER_ID", "default"),
                   memory_mb=memory_mb, reserve_memory_mb=reserve_memory_mb, min_memory_mb=min_memory_mb,
                   adaptive_memory=os.getenv("FINSIGHT_ANALYSIS_ADAPTIVE_MEMORY", "false").lower() in {"true", "1"})

    def configured(self) -> bool:
        return (self.enabled and len(self.token) >= 32 and bool(self.image)
                and bool(re.fullmatch(r"[a-zA-Z0-9_-]{1,64}", self.worker_id))
                and 0 < self.timeout_seconds <= MAX_SECONDS
                and 128 <= self.memory_mb <= 2048 and 128 <= self.reserve_memory_mb <= 65536
                and 128 <= self.min_memory_mb <= self.memory_mb
                and 0 < self.cpus <= 2 and 16 <= self.pids <= 128)


class DockerCLI:
    async def command(self, args: list[str], *, input_bytes: bytes | None = None,
                      timeout: float = 10, stdout_limit: int = MAX_RESPONSE_BYTES) -> tuple[int, bytes, bytes]:
        """不用 shell；同时有界读取两条管道，防止日志淹没调度器。"""
        try:
            process = await asyncio.create_subprocess_exec(
                "docker", *args, stdin=asyncio.subprocess.PIPE if input_bytes is not None else asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                limit=65536,
            )
        except OSError:
            raise AnalysisError("analysis_docker_unavailable") from None

        async def read_limited(stream, limit):
            chunks, total = [], 0
            while chunk := await stream.read(65536):
                total += len(chunk)
                if total > limit:
                    raise AnalysisError("analysis_output_limit")
                chunks.append(chunk)
            return b"".join(chunks)

        async def write_input():
            if process.stdin is not None:
                try:
                    process.stdin.write(input_bytes)
                    await process.stdin.drain()
                except (BrokenPipeError, ConnectionResetError):
                    pass
                finally:
                    process.stdin.close()

        tasks = [asyncio.create_task(read_limited(process.stdout, stdout_limit)),
                 asyncio.create_task(read_limited(process.stderr, MAX_LOG_BYTES)),
                 asyncio.create_task(write_input()), asyncio.create_task(process.wait())]
        try:
            stdout, stderr, _, code = await asyncio.wait_for(asyncio.gather(*tasks), timeout=timeout)
            return code, stdout, stderr
        finally:
            # 杀掉 CLI 不能替代杀容器；Dispatcher 的 finally 另外强制删除整个作业。
            if process.returncode is None:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await process.wait()


class Dispatcher:
    def __init__(self, settings: Settings, cli: DockerCLI | None = None):
        self.settings = settings
        self.cli = cli or DockerCLI()
        self.ready = False
        self.error = "analysis_worker_unconfigured"
        self.image_id = ""
        self.active = False

    async def checked(self, args: list[str], **kwargs) -> bytes:
        code, stdout, _ = await self.cli.command(args, **kwargs)
        if code:
            raise AnalysisError("analysis_docker_failed")
        return stdout

    async def initialize(self) -> None:
        if not self.settings.configured():
            return
        try:
            info = strict_json(await self.checked(["info", "--format", "{{json .}}"] ))
            security = info.get("SecurityOptions", [])
            if (info.get("OSType") != "linux" or not info.get("MemoryLimit")
                    or not info.get("SwapLimit") or not info.get("PidsLimit")
                    or not info.get("CpuCfsQuota") or not info.get("CpuCfsPeriod")
                    or not any("name=seccomp" in item and "profile=builtin" in item for item in security)):
                raise AnalysisError("analysis_isolation_unavailable")
            required = (self.settings.min_memory_mb if self.settings.adaptive_memory else self.settings.memory_mb) + self.settings.reserve_memory_mb
            if info.get("MemTotal", 0) < required * 1024 * 1024:
                raise AnalysisError("analysis_capacity_insufficient")
            image = strict_json(await self.checked(["image", "inspect", "--format", "{{json .}}", self.settings.image]))
            config = image.get("Config", {})
            if (image.get("Os") != "linux" or config.get("User") != "65532:65532"
                    or config.get("Volumes")
                    or config.get("Entrypoint") != ["python", "-I", "/opt/analysis/runner.py"]
                    or not re.fullmatch(r"sha256:[a-f0-9]{64}", image.get("Id", ""))):
                raise AnalysisError("analysis_image_invalid")
            self.image_id = image["Id"]
            await self.recover()
            self.ready, self.error = True, ""
        except (AnalysisError, TimeoutError, ValueError, TypeError, AttributeError) as exc:
            self.error = exc.code if isinstance(exc, AnalysisError) else "analysis_docker_unavailable"

    async def recover(self) -> None:
        """单调度实例启动时回收自己上次中断留下的容器/卷。"""
        label = f"{LABEL}={self.settings.worker_id}"
        for kind, args in (("container", ["container", "ls", "--all", "--filter", "label=" + label, "--format", "{{.Names}}"]),
                           ("volume", ["volume", "ls", "--filter", "label=" + label, "--format", "{{.Name}}"] )):
            names = (await self.checked(args)).decode("utf-8").splitlines()
            for name in names:
                if not RESOURCE_NAME.fullmatch(name):
                    raise AnalysisError("analysis_recovery_failed")
                await self.checked([kind, "rm", *( ["--force"] if kind == "container" else []), name])

    def job_memory_mb(self, available: int) -> int | None:
        if not self.settings.adaptive_memory:
            return self.settings.memory_mb if available >= self.settings.memory_mb + self.settings.reserve_memory_mb else None
        budget = min(self.settings.memory_mb, (available - self.settings.reserve_memory_mb) // 64 * 64)
        return budget if budget >= self.settings.min_memory_mb else None

    def container_args(self, name: str, volume: str, *, stage: bool, memory_mb: int | None = None) -> list[str]:
        memory = str(memory_mb or self.settings.memory_mb) + "m"
        return ["container", "create", "--name", name, "--label", f"{LABEL}={self.settings.worker_id}",
                "--network", "none", "--read-only", "--cap-drop", "ALL",
                # 初始化进程只把 stdin 写到新卷；只有它以 root 创建可读输入文件。
                "--security-opt", "no-new-privileges:true", "--user", "0:0" if stage else "65532:65532",
                "--cgroupns", "private", "--ipc", "private", "--pids-limit", str(self.settings.pids),
                "--memory", memory, "--memory-swap", memory, "--cpus", str(self.settings.cpus), "--oom-score-adj", "500",
                "--ulimit", "core=0:0", "--ulimit", "nofile=64:64", "--ulimit", "fsize=8388608:8388608",
                "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=67108864,mode=1777", "--shm-size", "16m",
                "--workdir", "/tmp", "--hostname", "analysis", "--log-driver", "none",
                "--mount", f"type=volume,source={volume},target=/input,volume-nocopy" + ("" if stage else ",readonly"),
                *(["--interactive"] if stage else []), self.image_id, *(["stage"] if stage else [])]

    async def create_resource(self, args: list[str]) -> None:
        # 创建 RPC 完成后再响应取消，避免 CLI 刚断开、daemon 随后创建出漏清理作业。
        task = asyncio.create_task(self.checked(args))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            await asyncio.gather(task, return_exceptions=True)
            raise

    async def cleanup(self, stage: str, job: str, volume: str) -> bool:
        try:
            # 即使 create 未成功也尝试按不可猜测名称清理，再检查是否确实不存在。
            await self.cli.command(["container", "rm", "--force", stage, job])
            existing = await self.checked(["container", "ls", "--all", "--filter",
                                           f"name=^/{stage[:-6]}-(stage|run)$", "--format", "{{.Names}}"])
            if existing.strip():
                return False
            await self.cli.command(["volume", "rm", volume])
            remaining = await self.checked(["volume", "ls", "--filter", "name=^" + volume + "$", "--format", "{{.Name}}"])
            return not remaining.strip()
        except (AnalysisError, TimeoutError):
            return False

    async def run(self, request: JobRequest) -> dict:
        if not self.ready:
            return {"status": "error", "error": self.error}
        if self.active:
            return {"status": "error", "error": "analysis_worker_busy"}
        # 每次作业都重新取宿主实测值；不足时连输入卷/初始化容器也不创建。
        # 调度器与 daemon 必须同宿主，容器内 /proc/meminfo 反映宿主物理内存。
        try:
            available = available_memory_mb()
        except AnalysisError as exc:
            return {"status": "error", "error": exc.code}
        memory_mb = self.job_memory_mb(available)
        required = (self.settings.min_memory_mb if self.settings.adaptive_memory else self.settings.memory_mb) + self.settings.reserve_memory_mb
        if memory_mb is None:
            return {"status": "error", "error": "analysis_capacity_insufficient",
                    "available_memory_mb": available, "required_memory_mb": required}
        self.active = True
        identifier = "finsight-analysis-" + uuid.uuid4().hex
        stage, job, volume = (identifier + suffix for suffix in ("-stage", "-run", "-input"))
        started = time.monotonic()
        result = {"status": "error", "error": "analysis_code_failed"}
        try:
            async with asyncio.timeout(min(request.timeout_seconds, self.settings.timeout_seconds)):
                raw = request.encode()
                if len(raw) > MAX_REQUEST_BYTES:
                    raise AnalysisError("analysis_request_too_large")
                await self.create_resource(["volume", "create", "--label", f"{LABEL}={self.settings.worker_id}",
                                            "--driver", "local", volume])
                await self.create_resource(self.container_args(stage, volume, stage=True, memory_mb=memory_mb))
                await self.checked(["container", "start", "--attach", "--interactive", stage], input_bytes=raw)
                stage_state = strict_json(await self.checked(["container", "inspect", "--format", "{{json .State}}", stage]))
                if stage_state.get("ExitCode") != 0:
                    raise AnalysisError("analysis_input_failed")
                await self.create_resource(self.container_args(job, volume, stage=False, memory_mb=memory_mb))
                _, stdout, _ = await self.cli.command(["container", "start", "--attach", job], timeout=MAX_SECONDS)
                state = strict_json(await self.checked(["container", "inspect", "--format", "{{json .State}}", job]))
                if state.get("OOMKilled"):
                    raise AnalysisError("analysis_memory_limit")
                if state.get("ExitCode") != 0 or state.get("Running"):
                    raise AnalysisError("analysis_code_failed")
                result = self.parse_result(stdout)
                result.update({"job_id": identifier, "code_hash": hashlib.sha256(request.code.encode()).hexdigest(),
                               "input_hash": hashlib.sha256(raw).hexdigest(),
                               "duration_ms": round((time.monotonic() - started) * 1000)})
        except TimeoutError:
            result = {"status": "error", "error": "analysis_timeout"}
        except AnalysisError as exc:
            result = {"status": "error", "error": exc.code}
        except (ValueError, TypeError, UnicodeError, RecursionError):
            result = {"status": "error", "error": "analysis_protocol_invalid"}
        finally:
            cleanup_task = asyncio.create_task(self.cleanup(stage, job, volume))
            try:
                cleaned = await asyncio.shield(cleanup_task)
            except asyncio.CancelledError:
                cleaned = await cleanup_task
                raise
            finally:
                self.active = False
                if not cleanup_task.cancelled() and cleanup_task.done() and not cleanup_task.result():
                    self.ready, self.error = False, "analysis_cleanup_failed"
        if not cleaned:
            return {"status": "error", "error": "analysis_cleanup_failed"}
        return {**result, "allocated_memory_mb": memory_mb, "memory_reserve_mb": self.settings.reserve_memory_mb}

    @staticmethod
    def parse_result(stdout: bytes) -> dict:
        if len(stdout) > MAX_RESPONSE_BYTES:
            raise AnalysisError("analysis_output_limit")
        value = strict_json(stdout)
        if not isinstance(value, dict):
            raise AnalysisError("analysis_protocol_invalid")
        if value.get("status") == "error" and value.get("error") in RUNNER_ERRORS:
            from .protocol import safe_code_error
            detail = safe_code_error(value.get("code_error"))
            logs = value.get("logs", "")
            if not isinstance(logs, str) or len(logs.encode()) > MAX_LOG_BYTES:
                raise AnalysisError("analysis_protocol_invalid")
            return {"status": "error", "error": value["error"], "logs": logs,
                    "logs_truncated": bool(value.get("logs_truncated")), **({"code_error": detail} if detail else {})}
        if value.get("status") != "ok" or "result" not in value:
            raise AnalysisError("analysis_protocol_invalid")
        if len(json.dumps(value["result"], ensure_ascii=False, allow_nan=False).encode()) > MAX_RESULT_BYTES:
            raise AnalysisError("analysis_output_limit")
        logs = value.get("logs", "")
        if not isinstance(logs, str) or len(logs.encode()) > MAX_LOG_BYTES:
            raise AnalysisError("analysis_output_limit")
        return {"status": "ok", "result": value["result"], "logs": logs,
                "logs_truncated": bool(value.get("logs_truncated"))}

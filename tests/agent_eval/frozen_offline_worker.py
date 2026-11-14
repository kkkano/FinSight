"""在独立进程内执行冻结来源，网络阻断覆盖内部线程且不污染研究模型。"""
from __future__ import annotations

import atexit
import hashlib
import json
import os
from pathlib import Path
from queue import Empty, Queue
import subprocess
import sys
from threading import Lock, Thread
import uuid

ROOT = Path(__file__).resolve().parents[2]


class OfflineWorker:
    def __init__(self, corpus_root: Path, *, timeout: float = 45):
        self.corpus_root = Path(corpus_root).resolve()
        self.timeout = timeout
        self.lock = Lock()
        self.process = None
        self.log = None
        self.responses = Queue()
        atexit.register(self.close)

    def _start(self):
        self.responses = Queue()
        log_root = ROOT / "tmp/agent-eval-offline" / str(os.getpid())
        log_root.mkdir(parents=True, exist_ok=True)
        self.log = (log_root / (uuid.uuid4().hex + ".log")).open("w", encoding="utf-8")
        # 离线解析进程只需系统路径；不向它传递供应商密钥或用户凭据。
        environment = {key: value for key, value in os.environ.items()
                       if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LOCALAPPDATA"}}
        environment.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        if os.getenv("FINSIGHT_EVAL_CORPUS_MOUNT_MANIFEST"):
            environment["FINSIGHT_EVAL_CORPUS_MOUNT_MANIFEST"] = os.environ["FINSIGHT_EVAL_CORPUS_MOUNT_MANIFEST"]
        self.process = subprocess.Popen([sys.executable, "-B", "-X", "utf8", str(Path(__file__).resolve()),
                                        "--serve", str(self.corpus_root)], cwd=ROOT, env=environment,
                                       stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.log,
                                       text=True, encoding="utf-8", bufsize=1)
        process, responses = self.process, self.responses

        def collect():
            for line in process.stdout:
                responses.put(line)
            responses.put(None)

        Thread(target=collect, daemon=True).start()

    def close(self):
        process = self.process
        self.process = None
        if process is not None:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=10)
            for stream in (process.stdin, process.stdout):
                if stream is not None:
                    stream.close()
        if self.log is not None:
            self.log.close()
            self.log = None

    def retrieve(self, name: str, arguments: dict):
        with self.lock:
            if self.process is None or self.process.poll() is not None:
                self.close()
                self._start()
            request = {"tool": name, "arguments": arguments, "request_id": uuid.uuid4().hex}
            try:
                self.process.stdin.write(json.dumps(request, ensure_ascii=False) + "\n")
                self.process.stdin.flush()
                line = self.responses.get(timeout=self.timeout)
                if line is None:
                    raise RuntimeError("frozen_offline_worker_exited")
                response = json.loads(line)
                if response.get("request_id") != request["request_id"]:
                    raise ValueError("frozen_offline_response_identity_mismatch")
                if "error" in response:
                    raise RuntimeError(response["error"])
                raw, proof = response["result"]
                proof["execution_isolation"] = {"kind": "dedicated_offline_process",
                    "socket_guard_scope": "whole_offline_process_including_internal_threads",
                    "credentials_forwarded": False,
                    "worker_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
                return raw, proof
            except (Empty, BrokenPipeError):
                self.close()
                raise RuntimeError("frozen_offline_worker_timeout_or_pipe_closed") from None


def serve(corpus_root: Path):
    wire = sys.stdout
    # 生产函数的日志不能混入机器协议；完整诊断保留在本机独立日志。
    sys.stdout = sys.stderr
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "tests"))
    from agent_eval.offline_network_isolation import install_network_filter
    network_guard = install_network_filter()
    from agent_eval.frozen_corpus_provider import FrozenCorpus
    from agent_eval.run import financial_tool_specs
    corpus = FrozenCorpus(corpus_root)
    specs = financial_tool_specs("baseline")
    for line in sys.stdin:
        request = json.loads(line)
        response = {"request_id": request["request_id"]}
        try:
            name = request["tool"]
            if name == "__environment_info__":
                from agent_eval.environment_preflight import inspect_environment
                response["result"] = inspect_environment(), corpus.marker({"kind": "readonly_environment_preflight"})
            elif name == "__network_guard_probe__":
                from agent_eval.offline_network_isolation import probe_network_filter
                response["result"] = probe_network_filter(request["arguments"]["local_probe_url"]), corpus.marker({"kind": "kernel_network_guard_probe"})
            else:
                callback = specs[name].invoke
                response["result"] = corpus.retrieve(name, request["arguments"], callback)
            response["result"][1]["kernel_network_guard"] = network_guard
        except Exception as exc:
            response["error"] = "frozen_offline_execution_" + type(exc).__name__
        print(json.dumps(response, ensure_ascii=False), file=wire, flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "--serve":
        raise SystemExit("expected --serve CORPUS_ROOT")
    serve(Path(sys.argv[2]))

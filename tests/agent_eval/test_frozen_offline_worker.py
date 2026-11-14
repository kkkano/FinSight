"""独立离线执行不能污染父进程事件循环，也不能携带运行时凭据。"""
import asyncio
import json
import os
from pathlib import Path
import socket
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import patch

import pytest

from .frozen_corpus_provider import build_corpus
from .frozen_offline_worker import OfflineWorker
from .tapes import ToolTape


def fixture(tmp_path):
    source = tmp_path / "source"
    ToolTape(source, "record").invoke("get_stock_price", {"ticker": "ALPHA"},
                                      lambda _args: "ALPHA: 42, captured fixture only")
    build_corpus(source, tmp_path / "corpus")
    return tmp_path / "corpus"


def test_offline_process_reuses_complete_exact_snapshot_and_never_forwards_credentials(tmp_path):
    worker = OfflineWorker(fixture(tmp_path))
    try:
        with patch.dict(os.environ, {"FINSIGHT_AGENT_API_KEY": "test-secret-do-not-forward"}):
            value, proof = worker.retrieve("get_stock_price", {"ticker": "ALPHA"})
        assert value == "ALPHA: 42, captured fixture only"
        assert proof["kind"] == "exact_original_snapshot"
        assert proof["execution_isolation"]["credentials_forwarded"] is False
        first_pid = worker.process.pid
        second, _ = worker.retrieve("search", {"query": "nonexistent fixture corpus document"})
        assert second["status"] == "empty" and worker.process.pid == first_pid
    finally:
        worker.close()


def test_offline_network_guard_does_not_break_parallel_parent_asyncio_socket_wakeup(tmp_path):
    worker = OfflineWorker(fixture(tmp_path))

    async def run():
        task = asyncio.create_task(asyncio.to_thread(worker.retrieve, "get_stock_historical_data",
                                                   {"ticker": "ALPHA", "period": "1y", "interval": "1d"}))
        left, right = socket.socketpair()
        try:
            for _ in range(25):
                await asyncio.to_thread(left.sendall, b"wakeup")
                assert right.recv(6) == b"wakeup"
            return await task
        finally:
            left.close()
            right.close()

    try:
        raw, proof = asyncio.run(run())
        assert raw["error_code"] == "frozen_corpus_gap"
        assert proof["kind"] == "structured_data_gap" and proof["network_access"] is False
    finally:
        worker.close()


def test_offline_worker_logs_use_explicit_external_artifact_root(tmp_path, monkeypatch):
    artifact_root = tmp_path / "external-artifacts"
    monkeypatch.setenv("FINSIGHT_EVAL_ARTIFACT_ROOT", str(artifact_root))
    worker = OfflineWorker(fixture(tmp_path))
    try:
        raw, _proof = worker.retrieve("get_stock_price", {"ticker": "ALPHA"})
        assert raw == "ALPHA: 42, captured fixture only"
        assert Path(worker.log.name).is_relative_to(artifact_root)
    finally:
        worker.close()


@pytest.mark.skipif(sys.platform != "linux", reason="内核 seccomp 合同只在 Linux 验证；Windows 不宣称原生网络隔离")
def test_linux_worker_denies_native_libc_libcurl_and_threads_but_preserves_parent_http_and_unix(tmp_path):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"parent-network-positive-control")

        def log_message(self, *_args):
            pass

    from urllib.request import urlopen
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    serving = Thread(target=server.serve_forever, daemon=True)
    serving.start()
    url = f"http://127.0.0.1:{server.server_port}/health"
    worker = OfflineWorker(fixture(tmp_path))
    try:
        assert urlopen(url, timeout=5).status == 200
        observed, proof = worker.retrieve("__network_guard_probe__", {"local_probe_url": url})
        assert observed["passed"]
        assert observed["libcurl_return"] == 7 and observed["libcurl_ffi_errno"] == 1
        assert proof["kernel_network_guard"]["installed"]
        assert proof["kernel_network_guard"]["kernel_status"]["NoNewPrivs"] == "1"
        assert urlopen(url, timeout=5).status == 200
    finally:
        worker.close()
        server.shutdown()
        server.server_close()
        serving.join(timeout=5)

"""独立离线执行不能污染父进程事件循环，也不能携带运行时凭据。"""
import asyncio
import json
import os
from pathlib import Path
import socket
from unittest.mock import patch

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

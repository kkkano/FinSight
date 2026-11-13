"""在隔离进程中执行归档单测；默认禁止任何网络连接。"""
from __future__ import annotations

import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tests"))

from agent_eval.reference.loader import activate, verify_manifest


def main() -> int:
    os.environ.update(FINSIGHT_RUNTIME_PROFILE="test", FINSIGHT_LLM_REQUIRED="false",
                      LANGGRAPH_CHECKPOINTER_BACKEND="memory", LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK="true",
                      LANGGRAPH_EXECUTE_LIVE_TOOLS="false", LANGGRAPH_SYNTHESIZE_MODE="stub",
                      MONITOR_REALTIME_ENABLED="false", PREDICTION_ENABLED="false",
                      PREDICTION_GENERATION_ENABLED="false", RAG_EMBEDDING="hash", RAG_RERANKER="none")
    original_connect = socket.socket.connect
    def forbidden_connect(*args, **kwargs):
        # Windows 的 asyncio socketpair 使用本机连接创建自唤醒管道。
        frame = sys._getframe(1)
        while frame is not None:
            if frame.f_code is getattr(socket.socketpair, "__code__", None):
                return original_connect(*args, **kwargs)
            frame = frame.f_back
        raise AssertionError("reference_suite_network_forbidden")
    socket.socket.connect = forbidden_connect
    socket.create_connection = forbidden_connect
    activate(include_tests=True)
    import pytest
    args = sys.argv[1:]
    if not any(not value.startswith("-") for value in args):
        args = [*(str(ROOT / path) for path in verify_manifest()["reference_test_selection"]), *args]
    return pytest.main(["-c", str(ROOT / "pytest.ini"), "--confcutdir", str(ROOT), "--import-mode=importlib", *args])


if __name__ == "__main__":
    raise SystemExit(main())

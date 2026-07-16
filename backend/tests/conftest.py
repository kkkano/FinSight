# -*- coding: utf-8 -*-
import os
import tempfile
from pathlib import Path

import pytest

from backend.config.settings import clear_settings_caches

# Windows sandbox may deny pytest's default AppData temp base. Keep pytest
# temp files inside the repo-local ignored tmp/ directory for deterministic CI.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_PYTEST_TMP = _REPO_ROOT / "tmp" / "pytest"
_PYTEST_TMP.mkdir(parents=True, exist_ok=True)
for _name in ("TMP", "TEMP", "TMPDIR"):
    os.environ.setdefault(_name, str(_PYTEST_TMP))
tempfile.tempdir = str(_PYTEST_TMP)

# Keep test runtime deterministic and avoid async sqlite destructor noise in
# short-lived TestClient lifecycles unless a test explicitly overrides backend.
#
# These are HARD isolation guarantees: force-override even when the outer shell
# already exports them. Using setdefault here was a silent footgun — an external
# env (e.g. a dev shell with LANGGRAPH_CHECKPOINTER_BACKEND=postgres or
# MONITOR_REALTIME_ENABLED=true) would make the suite connect to real services.
os.environ["LANGGRAPH_CHECKPOINTER_BACKEND"] = "memory"
os.environ["LANGGRAPH_CHECKPOINTER_ALLOW_MEMORY_FALLBACK"] = "true"

# 测试默认不启动页面 lease 调度器；实时链路由定向测试显式调用。
os.environ["MONITOR_REALTIME_ENABLED"] = "false"


@pytest.fixture(autouse=True)
def _force_langgraph_deterministic_defaults(monkeypatch):
    """
    Tests must be deterministic and must NOT call external LLMs/tools by default.

    Individual tests can override these env vars when explicitly testing LLM/tool modes.
    """

    monkeypatch.setenv("LANGGRAPH_SYNTHESIZE_MODE", "stub")
    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "false")
    monkeypatch.setenv("ENABLE_LANGSMITH", "false")
    clear_settings_caches()
    yield
    clear_settings_caches()

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
# Health probes must model the deterministic CI profile: external LLM,
# Postgres and live provider credentials are optional for unit tests.
os.environ["FINSIGHT_RUNTIME_PROFILE"] = "test"
os.environ["FINSIGHT_LLM_REQUIRED"] = "false"
os.environ["ALLOW_ANONYMOUS_GENERATION"] = "true"


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


@pytest.fixture(autouse=True)
def _isolate_request_semantic_model(monkeypatch):
    """请求模型使用明确输入 fixture；未知测试不能悄悄调用真实付费服务。"""
    from importlib import import_module
    from backend.tests.semantic_request_fixtures import fixture_for_query

    module = import_module("backend.graph.nodes.route_request")

    async def fixture_extraction(state, seed):
        return fixture_for_query(str(state.get("query") or ""), state=state, seed=seed), {
            "status": "confirmed", "source": "explicit_test_fixture", "actual_model": "fixture-model",
        }

    monkeypatch.setattr(module, "extract_semantic_requirements", fixture_extraction)

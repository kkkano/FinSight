# -*- coding: utf-8 -*-
"""WP3 模块拆分后的导入与生命周期回归。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI

REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_in_fresh_interpreter(source: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-c", source],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def test_base_agent_import_does_not_eagerly_load_graph_runtime() -> None:
    result = _run_in_fresh_interpreter(
        "from backend.agents.base_agent import AgentOutput, BaseFinancialAgent"
    )

    assert result.returncode == 0, result.stderr


def test_security_limiters_load_dotenv_before_reading_environment() -> None:
    result = _run_in_fresh_interpreter(
        """
import os
import sys
import types

for key in (
    "RATE_LIMIT_ENABLED",
    "RATE_LIMIT_PER_MINUTE",
    "RATE_LIMIT_WINDOW_SECONDS",
    "CONCURRENCY_LIMIT_ENABLED",
    "GENERATION_MAX_CONCURRENT",
    "GENERATION_MAX_CONCURRENT_PER_CLIENT",
):
    os.environ.pop(key, None)

dotenv = types.ModuleType("dotenv")

def load_dotenv(*args, **kwargs):
    os.environ["RATE_LIMIT_ENABLED"] = "false"
    os.environ["RATE_LIMIT_PER_MINUTE"] = "7"
    os.environ["RATE_LIMIT_WINDOW_SECONDS"] = "13"
    os.environ["CONCURRENCY_LIMIT_ENABLED"] = "false"
    os.environ["GENERATION_MAX_CONCURRENT"] = "17"
    os.environ["GENERATION_MAX_CONCURRENT_PER_CLIENT"] = "3"
    return True

dotenv.load_dotenv = load_dotenv
dotenv.dotenv_values = lambda *args, **kwargs: {}
sys.modules["dotenv"] = dotenv

from backend.api import security_gate

assert security_gate._rate_limiter.enabled is False
assert security_gate._rate_limiter.limit == 7
assert security_gate._rate_limiter.window_seconds == 13
assert security_gate._concurrency_limiter.enabled is False
assert security_gate._concurrency_limiter.max_global == 17
assert security_gate._concurrency_limiter.max_per_client == 3
"""
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_lifespan_runs_startup_and_shutdown_hooks(monkeypatch: pytest.MonkeyPatch) -> None:
    import backend.api.lifespan as lifespan_module

    dependency_names = (
        "install_rag_observability_hooks",
        "get_rag_observability_store",
        "aget_graph_runner",
        "flush_langfuse",
        "shutdown_langfuse",
        "reset_graph_runner",
    )
    missing = [name for name in dependency_names if not hasattr(lifespan_module, name)]
    assert not missing, f"lifespan 缺少运行时依赖: {missing}"

    calls: list[str] = []

    class _Store:
        def ensure_schema(self) -> bool:
            calls.append("rag_schema")
            return True

    async def _aget_graph_runner() -> object:
        calls.append("graph_start")
        return object()

    async def _areset_checkpointer_caches() -> None:
        calls.append("checkpointer_stop")

    monkeypatch.setattr(lifespan_module, "_init_default_user_config", lambda: calls.append("config"))
    monkeypatch.setattr(
        lifespan_module,
        "install_rag_observability_hooks",
        lambda: calls.append("rag_hooks"),
    )
    monkeypatch.setattr(lifespan_module, "get_rag_observability_store", lambda: _Store())
    monkeypatch.setattr(lifespan_module, "aget_graph_runner", _aget_graph_runner)
    monkeypatch.setattr(lifespan_module, "flush_langfuse", lambda: calls.append("langfuse_flush"))
    monkeypatch.setattr(lifespan_module, "shutdown_langfuse", lambda: calls.append("langfuse_stop"))
    monkeypatch.setattr(lifespan_module, "reset_graph_runner", lambda: calls.append("graph_stop"))

    from backend.graph import checkpointer
    from backend.services import startup_check

    monkeypatch.setattr(checkpointer, "areset_checkpointer_caches", _areset_checkpointer_caches)
    monkeypatch.setattr(startup_check, "run_startup_checks", lambda: calls.append("startup_check"))

    for key in (
        "PRICE_ALERT_SCHEDULER_ENABLED",
        "NEWS_ALERT_SCHEDULER_ENABLED",
        "RISK_ALERT_SCHEDULER_ENABLED",
        "HEALTH_PROBE_ENABLED",
        "MONITOR_SCAN_ENABLED",
        "MONITOR_REALTIME_ENABLED",
        "PREDICTION_OUTCOME_SCHEDULER_ENABLED",
        "RAG_OBSERVABILITY_RETENTION_ENABLED",
    ):
        monkeypatch.setenv(key, "false")

    lifespan_module._schedulers.clear()
    async with lifespan_module.lifespan(FastAPI()):
        calls.append("yield")

    assert calls == [
        "config",
        "startup_check",
        "rag_hooks",
        "rag_schema",
        "graph_start",
        "yield",
        "langfuse_flush",
        "langfuse_stop",
        "checkpointer_stop",
        "graph_stop",
    ]


@pytest.mark.asyncio
async def test_real_graph_deep_report_path_reaches_render(monkeypatch: pytest.MonkeyPatch) -> None:
    """不替换节点，验证 deep-report 真实图路径可完整执行。"""
    for key, value in {
        "LANGGRAPH_PLANNER_MODE": "stub",
        "LANGGRAPH_SYNTHESIZE_MODE": "stub",
        "LANGGRAPH_EXECUTE_LIVE_TOOLS": "false",
        "FINSIGHT_INTENT_FRAME": "on",
        "FINSIGHT_DAG_EXECUTOR": "on",
        "FINSIGHT_AGENT_BRIEF": "on",
        "FINSIGHT_EVIDENCE_BUS": "on",
        "RAG_V2_BACKEND": "memory",
    }.items():
        monkeypatch.setenv(key, value)

    from backend.graph.runner import GraphRunner

    result = await GraphRunner.create().ainvoke(
        thread_id="wp3-real-deep-report",
        query=(
            "请做 INTC 深度投资报告（deep report, filing document longform），"
            "重点引用 10-K/10-Q、业绩电话会与权威媒体来源，并给出明确结论与风险清单"
        ),
        ui_context={"market": "US"},
        output_mode="chat",
        confirmation_mode="skip",
    )

    nodes = [span.get("node") for span in (result.get("trace") or {}).get("spans") or []]
    artifacts = result.get("artifacts") or {}

    assert result.get("output_mode") == "investment_report"
    assert (result.get("reply_contract") or {}).get("lane") == "report_generation"
    assert len((result.get("plan_ir") or {}).get("steps") or []) >= 6
    assert {"policy_gate", "planner", "execute_plan", "synthesize", "render"}.issubset(nodes)
    assert len(str(artifacts.get("draft_markdown") or "")) >= 200

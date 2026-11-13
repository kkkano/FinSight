"""唯一研究运行时不构建旧图，其他业务的调度与关闭清理仍保留。"""
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from fastapi import FastAPI
import pytest


def test_research_entry_import_does_not_load_graph_runner_or_execution_service():
    workspace = Path(__file__).resolve().parents[2]
    result = subprocess.run([sys.executable, "-B", "-c",
        "import sys; import backend.api.lifespan; import backend.api.execution_router; "
        "assert 'backend.graph.runner' not in sys.modules; "
        "assert 'backend.services.execution_service' not in sys.modules"],
        cwd=workspace, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
@pytest.mark.parametrize("retired_value", ["legacy", "agent2"])
async def test_startup_ignores_retired_selector_and_cleans_loaded_checkpointer(retired_value, monkeypatch):
    from backend.api import lifespan as module
    from backend.api import app_factory
    from backend.services import prediction_runner, startup_check
    from backend.config import settings
    monkeypatch.setenv("FINSIGHT_RESEARCH_RUNTIME", retired_value)
    monkeypatch.setattr(settings, "validate_startup_settings", lambda: {})
    monkeypatch.setattr(module, "validate_runtime_auth_configuration", lambda: None)
    monkeypatch.setattr(module, "assert_core_schema_current", lambda: SimpleNamespace(configured=False))
    monkeypatch.setattr(startup_check, "run_startup_checks", lambda: None)
    monkeypatch.setattr(app_factory, "_is_production_runtime", lambda: False)
    monkeypatch.setattr(prediction_runner, "enabled", lambda: False)
    monkeypatch.setattr(module, "flush_langfuse", lambda: None)
    monkeypatch.setattr(module, "shutdown_langfuse", lambda: None)
    calls = []

    async def unexpected_runner():
        raise AssertionError("研究启动不能构建旧图")

    async def cleanup():
        calls.append("checkpoint_cleanup")

    import backend.graph
    monkeypatch.setitem(backend.graph.__dict__, "aget_graph_runner", unexpected_runner)
    monkeypatch.setitem(sys.modules, "backend.common.checkpoint_store",
                        SimpleNamespace(areset_checkpointer_caches=cleanup))

    async with module.lifespan(FastAPI()):
        assert calls == []
    assert calls == ["checkpoint_cleanup"]


@pytest.mark.asyncio
async def test_research_startup_keeps_prediction_recovery_and_scheduler(monkeypatch):
    from backend.api import lifespan as module
    from backend.api import app_factory
    from backend.config import settings
    from backend.services import prediction_runner, prediction_store, scheduler_runner, startup_check

    monkeypatch.setattr(settings, "validate_startup_settings", lambda: {})
    monkeypatch.setattr(module, "validate_runtime_auth_configuration", lambda: None)
    monkeypatch.setattr(module, "assert_core_schema_current", lambda: SimpleNamespace(configured=False))
    monkeypatch.setattr(startup_check, "run_startup_checks", lambda: None)
    monkeypatch.setattr(app_factory, "_is_production_runtime", lambda: False)
    monkeypatch.setattr(prediction_runner, "enabled", lambda: True)
    monkeypatch.setattr(module, "flush_langfuse", lambda: None)
    monkeypatch.setattr(module, "shutdown_langfuse", lambda: None)
    calls = []
    monkeypatch.setattr(prediction_store, "get_prediction_store", lambda: SimpleNamespace(
        recover_interrupted=lambda: calls.append("recover")))

    def start_scheduler(callback, **kwargs):
        assert callback is prediction_runner.run_prediction_cycle
        assert kwargs["job_id"] == "us20_prediction_ledger"
        assert kwargs["interval_minutes"] == 5.0
        calls.append("start")
        return SimpleNamespace(shutdown=lambda **kwargs: calls.append(("shutdown", kwargs["wait"])))

    monkeypatch.setattr(scheduler_runner, "start_interval_scheduler", start_scheduler)
    async with module.lifespan(FastAPI()):
        assert calls == ["recover", "start"]
    assert calls == ["recover", "start", ("shutdown", True)]

"""核心服务、Prediction worker 与必要调度器的生命周期。"""
from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.security_gate import _env_bool, validate_runtime_auth_configuration
from backend.graph import aget_graph_runner, reset_graph_runner
from backend.services.database import assert_core_schema_current
from backend.services.langfuse_tracer import flush_langfuse, shutdown_langfuse


logger = logging.getLogger(__name__)
_schedulers: list[object] = []


@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_runtime_auth_configuration()
    schema_status = assert_core_schema_current()
    if schema_status.configured:
        logger.info("[Database] Alembic revision current=%s", ",".join(schema_status.current))
    else:
        logger.info("[Database] development 模式未配置核心 PostgreSQL，跳过 revision 检查")

    from backend.services.startup_check import run_startup_checks

    run_startup_checks()

    prediction_service = None
    if schema_status.configured and _env_bool("PREDICTION_GENERATION_ENABLED", True):
        from backend.services.prediction_service import get_prediction_service

        prediction_service = get_prediction_service()
        await prediction_service.start()
        logger.info("[Prediction] generation worker and recovery scan started")

    if schema_status.configured:
        from backend.services.scheduler_runner import start_interval_scheduler

        if _env_bool("MONITOR_REALTIME_ENABLED", True):
            from backend.services.monitor_engine import run_realtime_monitor_cycle

            scheduler = start_interval_scheduler(
                run_realtime_monitor_cycle,
                interval_minutes=1.0,
                enabled=True,
                job_id="monitor_realtime_tick",
                job_label="page-lease realtime monitor tick",
            )
            if scheduler:
                _schedulers.append(scheduler)

        if _env_bool("PREDICTION_OUTCOME_SCHEDULER_ENABLED", True):
            from backend.services.prediction_outcomes import run_prediction_outcome_cycle

            scheduler = start_interval_scheduler(
                run_prediction_outcome_cycle,
                interval_minutes=float(os.getenv("PREDICTION_OUTCOME_INTERVAL_MINUTES", "1440")),
                enabled=True,
                job_id="prediction_outcome_daily",
                job_label="deterministic prediction outcome evaluation",
            )
            if scheduler:
                _schedulers.append(scheduler)

    try:
        await aget_graph_runner()
        logger.info("[GraphRunner] initialized in lifespan")
    except Exception as exc:
        logger.exception("[GraphRunner] initialization failed in lifespan: %s", exc)

    try:
        yield
    finally:
        if prediction_service is not None:
            try:
                await prediction_service.stop()
            except Exception as exc:
                logger.warning("[Prediction] shutdown error: %s", exc)

        for scheduler in _schedulers:
            try:
                scheduler.shutdown(wait=True)  # type: ignore[attr-defined]
            except Exception as exc:
                logger.warning("[Scheduler] shutdown error: %s", exc)
        _schedulers.clear()

        try:
            flush_langfuse()
            shutdown_langfuse()
        except Exception:
            logger.debug("[LangFuse] flush/shutdown error", exc_info=True)

        try:
            from backend.graph.checkpointer import areset_checkpointer_caches

            await areset_checkpointer_caches()
            reset_graph_runner()
        except Exception as exc:
            logger.warning("[GraphRunner] shutdown cleanup error: %s", exc)


__all__ = ["lifespan"]

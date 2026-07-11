# -*- coding: utf-8 -*-
"""FastAPI lifespan（WP3 Task6 机械搬运自 backend/api/main.py，零行为变更）。

调度器生命周期（_schedulers）、默认用户配置初始化、RAG 观测台/GraphRunner 预热。
"""
from __future__ import annotations

import asyncio
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.security_gate import _env_bool, logger
from backend.graph import aget_graph_runner, reset_graph_runner
from backend.rag import get_rag_observability_store, install_rag_observability_hooks
from backend.services.langfuse_tracer import flush_langfuse, shutdown_langfuse

logger = logging.getLogger(__name__)

_schedulers = []

def _init_default_user_config() -> None:
    """Write default LLM config on first boot if user_config.json does not exist.

    This gives new deployments a working out-of-the-box experience:
    users see a pre-filled (but overridable) endpoint in the Settings UI.
    The file is stored in FINSIGHT_CONFIG_DIR (/app/data in Docker) so it
    persists across container restarts via the named volume.
    """
    import json as _json
    from backend.llm_config import DEFAULT_OPENAI_COMPATIBLE_MODEL, USER_CONFIG_PATH

    if os.path.exists(USER_CONFIG_PATH):
        return

    _DEFAULT_API_BASE = os.getenv("OPENAI_COMPATIBLE_API_BASE", "https://token-plan-cn.xiaomimimo.com/v1")
    _DEFAULT_API_KEY  = os.getenv("OPENAI_COMPATIBLE_API_KEY", "")
    _DEFAULT_MODEL    = os.getenv("OPENAI_COMPATIBLE_MODEL", DEFAULT_OPENAI_COMPATIBLE_MODEL)

    default_cfg = {
        "llm_provider": "openai_compatible",
        "llm_model":    _DEFAULT_MODEL,
        "llm_api_base": _DEFAULT_API_BASE,
        "llm_api_key":  _DEFAULT_API_KEY,
        "llm_endpoints": [
            {
                "name":        "primary",
                "provider":    "openai_compatible",
                "api_base":    _DEFAULT_API_BASE,
                "api_key":     _DEFAULT_API_KEY,
                "model":       _DEFAULT_MODEL,
                "weight":      1,
                "enabled":     True,
                "cooldown_sec": 30,
            }
        ],
    }
    try:
        os.makedirs(os.path.dirname(USER_CONFIG_PATH), exist_ok=True)
        with open(USER_CONFIG_PATH, "w", encoding="utf-8") as _f:
            _json.dump(default_cfg, _f, indent=2, ensure_ascii=False)
        logger.info("[Config] wrote default user config to %s", USER_CONFIG_PATH)
    except Exception as _exc:
        logger.warning("[Config] failed to write default user config: %s", _exc)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan handler to start/stop price_change scheduler."""
    # Ensure a working default LLM config exists on first boot.
    _init_default_user_config()

    # P1-1/P1-3: 启动配置自检（数据源 key 缺失告警 + LLM endpoint 可用性）
    try:
        from backend.services.startup_check import run_startup_checks

        run_startup_checks()
    except Exception as exc:
        logger.exception("[StartupCheck] failed: %s", exc)

    from backend.services.alert_scheduler import run_price_change_cycle
    from backend.services.scheduler_runner import start_interval_scheduler, start_price_change_scheduler

    enabled = _env_bool("PRICE_ALERT_SCHEDULER_ENABLED", False)
    if enabled:
        interval = float(os.getenv("PRICE_ALERT_INTERVAL_MINUTES", "15"))
        sched = start_price_change_scheduler(
            run_price_change_cycle,
            interval_minutes=interval,
            enabled=True,
        )
        if sched:
            _schedulers.append(sched)
    else:
        logger.info("[Scheduler] PRICE_ALERT_SCHEDULER_ENABLED is false; skip start.")

    # News scheduler
    from backend.services.alert_scheduler import run_news_alert_cycle
    news_enabled = _env_bool("NEWS_ALERT_SCHEDULER_ENABLED", False)
    if news_enabled:
        news_interval = float(os.getenv("NEWS_ALERT_INTERVAL_MINUTES", "30"))
        sched = start_price_change_scheduler(
            run_news_alert_cycle,
            interval_minutes=news_interval,
            enabled=True,
        )
        if sched:
            _schedulers.append(sched)
    else:
        logger.info("[Scheduler] NEWS_ALERT_SCHEDULER_ENABLED is false; skip start.")

    # Risk scheduler
    from backend.services.alert_scheduler import run_risk_alert_cycle
    risk_enabled = _env_bool("RISK_ALERT_SCHEDULER_ENABLED", False)
    if risk_enabled:
        risk_interval = float(os.getenv("RISK_ALERT_INTERVAL_MINUTES", "60"))
        sched = start_price_change_scheduler(
            run_risk_alert_cycle,
            interval_minutes=risk_interval,
            enabled=True,
        )
        if sched:
            _schedulers.append(sched)
    else:
        logger.info("[Scheduler] RISK_ALERT_SCHEDULER_ENABLED is false; skip start.")

    # Health probe scheduler (optional)
    from backend.services.health_probe import run_health_probe_cycle
    health_enabled = _env_bool("HEALTH_PROBE_ENABLED", False)
    if health_enabled:
        health_interval = float(os.getenv("HEALTH_PROBE_INTERVAL_MINUTES", "30"))
        sched = start_price_change_scheduler(
            run_health_probe_cycle,
            interval_minutes=health_interval,
            enabled=True,
        )
        if sched:
            _schedulers.append(sched)
    else:
        logger.info("[Scheduler] HEALTH_PROBE_ENABLED is false; skip start.")

    # Workbench: 交易时段感知 L1 盯盘调度（零 LLM 成本）
    # 调度心跳固定 5 分钟，实际扫描频率由 dispatcher 按时段间隔节流
    # （盘前 10 / 盘中 15 / 盘后 30 / 闭市 60 分钟）。
    monitor_enabled = _env_bool("MONITOR_SCAN_ENABLED", True)
    if monitor_enabled:
        from backend.services.monitor_engine import run_monitor_dispatch_cycle

        heartbeat_interval = float(os.getenv("MONITOR_DISPATCH_HEARTBEAT_MINUTES", "5"))
        sched = start_interval_scheduler(
            run_monitor_dispatch_cycle,
            interval_minutes=heartbeat_interval,
            enabled=True,
            job_id="monitor_l1_dispatch",
            job_label="workbench L1 session-aware monitor dispatch",
        )
        if sched:
            _schedulers.append(sched)
    else:
        logger.info("[Scheduler] MONITOR_SCAN_ENABLED is false; skip start.")

    try:
        install_rag_observability_hooks()
        rag_observability_status = get_rag_observability_store().ensure_schema() if hasattr(get_rag_observability_store(), 'ensure_schema') else False
        logger.info("[RAGObservability] initialized=%s", rag_observability_status)
    except Exception as exc:
        logger.exception("[RAGObservability] initialization failed in lifespan: %s", exc)

    rag_retention_enabled = _env_bool("RAG_OBSERVABILITY_RETENTION_ENABLED", True)
    if rag_retention_enabled:
        rag_retention_interval = float(os.getenv("RAG_OBSERVABILITY_RETENTION_INTERVAL_MINUTES", "360"))

        def _run_rag_observability_retention_cycle() -> None:
            try:
                deleted = get_rag_observability_store().cleanup_retention()
                logger.info("[RAGObservability] retention cleanup deleted=%s", deleted)
            except Exception as exc:
                logger.exception("[RAGObservability] retention cleanup failed: %s", exc)

        sched = start_interval_scheduler(
            _run_rag_observability_retention_cycle,
            interval_minutes=rag_retention_interval,
            enabled=True,
            job_id="rag_observability_retention",
            job_label="rag observability retention",
        )
        if sched:
            _schedulers.append(sched)
    else:
        logger.info("[RAGObservability] RAG_OBSERVABILITY_RETENTION_ENABLED is false; skip retention scheduler.")

    try:
        await aget_graph_runner()
        logger.info("[GraphRunner] initialized in lifespan")
    except Exception as exc:
        logger.exception("[GraphRunner] initialization failed in lifespan: %s", exc)

    try:
        yield
    finally:
        try:
            flush_langfuse()
            shutdown_langfuse()
        except Exception:
            logger.debug("[LangFuse] flush/shutdown error on shutdown (ignored)")
        try:
            for sched in _schedulers:
                sched.shutdown(wait=True)
            if _schedulers:
                logger.info("[Scheduler] all schedulers stopped.")
            _schedulers.clear()
        except Exception as e:
            logger.info(f"[Scheduler] shutdown error: {e}")
        try:
            from backend.graph.checkpointer import areset_checkpointer_caches

            await areset_checkpointer_caches()
            reset_graph_runner()
            logger.info("[GraphRunner] checkpointer/runner caches cleared on shutdown")
        except Exception as e:
            logger.info(f"[GraphRunner] shutdown cleanup error: {e}")

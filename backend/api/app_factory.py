# -*- coding: utf-8 -*-
"""FinSight FastAPI 应用装配。

公共产品面注册核心业务、模型设置与固定公开预测账本 Router。
"""
from __future__ import annotations

import logging
import math
import os
import threading
import time

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.conversation_router import ConversationRouterDeps, create_conversation_router
from backend.api.client_recovery import router as client_recovery_router
from backend.api.execution_router import ExecutionRouterDeps, create_execution_router
from backend.api.lifespan import lifespan
from backend.api.market_router import MarketRouterDeps, create_market_router
from backend.api.monitor_router import monitor_router
from backend.api.model_router import router as model_router
from backend.api.prediction_router import router as track_record_router
from backend.services.model_selection import require_model_access
from backend.agent_runtime.model_options import ResearchModelSelectionMiddleware as ModelSelectionMiddleware
from backend.api.predictions_router import PredictionsRouterDeps, create_predictions_router
from backend.api.report_router import ReportRouterDeps, create_report_router
from backend.api.security_gate import (
    _env_bool,
    _is_internal_api_key_authorized,
    _parse_csv_env,
    security_gate,
)
from backend.api.session_context import (
    _clear_session_context,
    _get_session_context,
    _list_session_contexts,
    _resolve_thread_id,
    _schedule_report_index,
    _update_session_context,
)
from backend.api.system_router import SystemRouterDeps, create_system_router
from backend.api.user_router import create_user_router
from backend.api.watchlist_router import WatchlistRouterDeps, create_watchlist_router
from backend.metrics import METRICS_ENABLED, metrics_payload
from backend.services.conversation_store import get_conversation_store
from backend.dashboard.schemas import DashboardResponse
from backend.dashboard.snapshot import get_dashboard
from backend.services.llm_usage_store import check_user_quota
from backend.services.market_data_gateway import get_market_data_gateway
from backend.services.prediction_outcomes import run_prediction_outcome_cycle
from backend.services.prediction_service import get_prediction_service
from backend.services.report_index import get_report_index_store
from backend.services.startup_check import get_startup_result
from backend.services.system_health import authentication_health, database_health, market_data_health
from backend.services.watchlist_store import get_watchlist_store


load_dotenv()
logger = logging.getLogger(__name__)
_rag_probe_lock = threading.Lock()
_rag_probe_fingerprint: tuple[str, ...] | None = None
_rag_probe_result: dict[str, object] | None = None
_rag_probe_failed_at: float | None = None


def _is_production_runtime() -> bool:
    values = (
        str(os.getenv("FINSIGHT_RUNTIME_PROFILE") or "").strip().lower(),
        str(os.getenv("APP_MODE") or "").strip().lower(),
    )
    return any(value in {"prod", "production"} for value in values)


def _rag_probe_key() -> tuple[str, ...]:
    return (
        str(os.getenv("FINSIGHT_RUNTIME_PROFILE") or "").strip().lower(),
        str(os.getenv("APP_MODE") or "").strip().lower(),
        str(os.getenv("RAG_V2_BACKEND") or "auto").strip().lower(),
        str(os.getenv("RAG_EMBEDDING") or "lexical").strip().lower(),
        str(os.getenv("RAG_V2_VECTOR_DIM") or "").strip(),
        str(os.getenv("RAG_RERANKER") or "none").strip().lower(),
        str(os.getenv("RAG_WORKER_URL") or ""),
        str(os.getenv("RAG_EMBEDDING_API_URL") or ""),
        str(os.getenv("RAG_EMBEDDING_MODEL") or ""),
        str(os.getenv("RAG_EMBEDDING_MODEL_VERSION") or ""),
        str(os.getenv("RAG_EMBEDDING_DIM") or ""),
        "configured" if os.getenv("RAG_EMBEDDING_API_KEY") else "missing",
    )


def _run_embedding_smoke(service: object) -> tuple[bool, str | None]:
    """Encode one short string using the exact embedder selected by RAG."""
    embedder = getattr(service, "_embedder", None)
    encode_single = getattr(embedder, "encode_single", None)
    if not callable(encode_single):
        return False, "rag_embedding_probe_unavailable"
    try:
        dense, _sparse = encode_single("FinSight readiness probe")
        vector = list(dense or [])
        expected_dim = int(getattr(service, "vector_dim", 0) or 0)
        if not vector or (expected_dim and len(vector) != expected_dim):
            return False, "rag_embedding_probe_invalid_dimension"
        if not all(math.isfinite(float(item)) for item in vector):
            return False, "rag_embedding_probe_non_finite"
        actual_model = str(getattr(embedder, "model_name", "unknown") or "unknown").lower()
        if _is_production_runtime() and actual_model != "bge-m3":
            return False, "rag_embedding_degraded"
        return True, None
    except Exception:
        logger.exception("RAG embedding readiness probe failed")
        return False, "rag_embedding_probe_failed"


def _rag_health_uncached() -> dict[str, object]:
    """Return a cheap, secret-free RAG readiness snapshot.

    Construction is intentionally lazy and failures are converted into a
    stable error code so a probe never exposes DSNs or model stack traces.
    Production readiness is fail-closed; test/stub profiles can report a
    degraded in-memory service without making the API unusable.
    """
    # Local/test readiness must not instantiate a Postgres RAG service or load
    # multi-gigabyte embedding weights just to answer a probe. Production is
    # warmed explicitly during lifespan and is the only profile that requires
    # a real encode check.
    if not _is_production_runtime():
        return {
            "status": "disabled",
            "reason": "rag_probe_skipped_non_production",
            "backend_requested": str(os.getenv("RAG_V2_BACKEND", "auto") or "auto").strip().lower(),
        }
    try:
        from backend.rag.hybrid_service import get_rag_service
        from backend.rag.reranker import get_reranker_service

        service = get_rag_service()
        provider = str(os.getenv("RAG_EMBEDDING") or "lexical").strip().lower()
        if provider in {"lexical", "remote_api"}:
            # 健康读取不能为观测额外调用托管模型；沿真实检索的最后成功身份报告。
            health = service._embedder.worker_health()
            semantic_ready = bool(health.get("inference_verified") and health.get("status") == "ok")
            identity = str(health.get("embedding_identity") or "") or None
            index = service.index_status(identity)
            lexical_ready = service.backend_name == "postgres"
            reranker_disabled = str(os.getenv("RAG_RERANKER") or "none").strip().lower() == "none"
            reranker_status = "disabled" if reranker_disabled else get_reranker_service().health()["status"]
            return {
                "status": ("ok" if provider == "lexical" or semantic_ready else "degraded") if lexical_ready else "error",
                "backend": service.backend_name, "backend_requested": os.getenv("RAG_V2_BACKEND", "postgres"),
                "embedding": service.embedding_model, "semantic_ready": semantic_ready,
                "lexical_ready": lexical_ready, "index": index,
                "reranker": reranker_status,
                "full_ready": bool(semantic_ready and index["pending"] == 0 and reranker_status in {"ok", "disabled"}),
                "reason": ("lexical_mode" if provider == "lexical" else
                           (None if semantic_ready else "semantic_retrieval_unverified_using_lexical")),
                **({} if lexical_ready else {"error_code": "rag_backend_not_persistent"}),
            }
        if str(os.getenv("RAG_WORKER_URL") or "").strip():
            health = service._embedder.worker_health()
            semantic_ready = bool(health.get("inference_verified") and health.get("status") == "ok")
            lexical_ready = service.backend_name == "postgres"
            identity = f"bge-m3:{health.get('model_version')}:1024" if semantic_ready else None
            index = service.index_status(identity)
            full_ready = semantic_ready and health.get("reranker") in {"ok", "disabled"} and index["pending"] == 0
            return {"status": "ok" if semantic_ready else ("degraded" if lexical_ready else "error"),
                    "backend": service.backend_name, "backend_requested": os.getenv("RAG_V2_BACKEND", "postgres"),
                    "embedding": service.embedding_model, "semantic_ready": semantic_ready,
                    "lexical_ready": lexical_ready, "reranker": health.get("reranker", "disabled"),
                    "index": index, "full_ready": full_ready,
                    "reason": None if semantic_ready else "semantic_retrieval_unavailable_using_lexical"}
        backend_actual = str(getattr(service, "backend_name", "unknown") or "unknown").lower()
        embedding = str(getattr(service, "embedding_model", "unknown") or "unknown").lower()
        fallback_reason = str(getattr(service, "fallback_reason", "") or "").strip()
        requested = str(os.getenv("RAG_V2_BACKEND", "auto") or "auto").strip().lower()
        reranker = get_reranker_service()
        reranker_enabled = bool(reranker.is_enabled)
        production = _is_production_runtime()

        if production:
            probe_ok, probe_error = _run_embedding_smoke(service)
            if not probe_ok:
                return {
                    "status": "error",
                    "error_code": probe_error or "rag_embedding_probe_failed",
                    "backend_requested": requested,
                    "backend": backend_actual,
                    "embedding": embedding,
                    "reranker": "ok" if reranker_enabled else "degraded",
                }
            if requested == "postgres" and backend_actual != "postgres":
                return {
                    "status": "error",
                    "error_code": "rag_backend_unavailable",
                    "backend_requested": requested,
                    "backend": backend_actual,
                    "embedding": embedding,
                    "reranker": "ok" if reranker_enabled else "degraded",
                }
            if backend_actual != "postgres":
                return {
                    "status": "error",
                    "error_code": "rag_backend_not_persistent",
                    "backend_requested": requested,
                    "backend": backend_actual,
                    "embedding": embedding,
                    "reranker": "ok" if reranker_enabled else "degraded",
                }
            if fallback_reason:
                return {
                    "status": "error",
                    "error_code": "rag_fallback_active",
                    "backend_requested": requested,
                    "backend": backend_actual,
                    "embedding": embedding,
                    "reranker": "ok" if reranker_enabled else "degraded",
                }
            if embedding != "bge-m3":
                return {
                    "status": "error",
                    "error_code": "rag_embedding_degraded",
                    "backend_requested": requested,
                    "backend": backend_actual,
                    "embedding": embedding,
                    "reranker": "ok" if reranker_enabled else "degraded",
                }

        return {
            "status": "ok" if not fallback_reason else "degraded",
            "backend_requested": requested,
            "backend": backend_actual,
            "embedding": embedding,
            "reranker": "ok" if reranker_enabled else "degraded",
            "reason": fallback_reason or None,
        }
    except Exception:
        return {"status": "error", "error_code": "rag_health_failed"}


def warm_rag_readiness_probe(*, force: bool = False) -> dict[str, object]:
    """Run/read the RAG readiness probe for the current config.

    Healthy results are reusable for the process lifetime (until the config
    fingerprint changes). A failure is cached briefly to avoid repeatedly
    constructing a broken model on every readiness request, then retried so a
    transient database/model outage can recover without restarting the app.
    The lock deliberately covers the probe call: concurrent requests share one
    in-flight attempt rather than loading the embedding model multiple times.
    """
    global _rag_probe_fingerprint, _rag_probe_result, _rag_probe_failed_at
    fingerprint = _rag_probe_key()
    with _rag_probe_lock:
        now = time.monotonic()
        if not force and _rag_probe_result is not None and _rag_probe_fingerprint == fingerprint:
            status = str(_rag_probe_result.get("status") or "").strip().lower()
            if status in {"ok", "disabled"} and (status == "disabled" or _rag_probe_failed_at is not None
                                                  and now - _rag_probe_failed_at < 15):
                return dict(_rag_probe_result)
            failure_ttl = _rag_probe_failure_ttl_seconds()
            if status not in {"ok", "disabled"} and _rag_probe_failed_at is not None and now - _rag_probe_failed_at < failure_ttl:
                return dict(_rag_probe_result)
        result = _rag_health_uncached()
        _rag_probe_fingerprint = fingerprint
        _rag_probe_result = dict(result)
        _rag_probe_failed_at = now
        return dict(result)


def _rag_probe_failure_ttl_seconds() -> float:
    raw = str(os.getenv("RAG_PROBE_FAILURE_TTL_SECONDS") or "45").strip()
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 45.0
    return max(1.0, min(300.0, value))


def reset_rag_readiness_probe_for_testing() -> None:
    global _rag_probe_fingerprint, _rag_probe_result, _rag_probe_failed_at
    with _rag_probe_lock:
        _rag_probe_fingerprint = None
        _rag_probe_result = None
        _rag_probe_failed_at = None


def _rag_health() -> dict[str, object]:
    return warm_rag_readiness_probe()


def _cors_allow_origins() -> list[str]:
    origins = _parse_csv_env(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
    )
    return origins or ["http://localhost:5173", "http://127.0.0.1:5173"]


def _cors_allow_origin_regex() -> str | None:
    configured = str(os.getenv("CORS_ALLOW_ORIGIN_REGEX") or "").strip()
    return configured or r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"


def _cors_allow_credentials() -> bool:
    allow_credentials = _env_bool("CORS_ALLOW_CREDENTIALS", False)
    if allow_credentials and "*" in _cors_allow_origins():
        logger.warning("CORS wildcard origin cannot be combined with credentials; credentials disabled")
        return False
    return allow_credentials


def create_app() -> FastAPI:
    from backend.api.skill_router import create_skill_router
    from backend.api.auth_provider_router import router as auth_provider_router
    app = FastAPI(
        title="FinSight API",
        description="可信行情、AI Prediction 与证据化研究 API",
        version="2.0.0",
        lifespan=lifespan,
    )
    app.state.require_model_access = require_model_access
    app.add_middleware(ModelSelectionMiddleware, authenticate=require_model_access)
    app.middleware("http")(security_gate)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_allow_origins(),
        allow_origin_regex=_cors_allow_origin_regex(),
        allow_credentials=_cors_allow_credentials(),
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Run-Id"],
    )

    system_router = create_system_router(
        SystemRouterDeps(
            metrics_enabled=METRICS_ENABLED,
            metrics_payload=metrics_payload,
            get_startup_result=get_startup_result,
            get_authentication_health=authentication_health,
            get_database_health=database_health,
            get_market_data_health=market_data_health,
            get_rag_health=_rag_health,
        )
    )
    user_router = create_user_router()
    watchlist_router = create_watchlist_router(WatchlistRouterDeps(get_store=get_watchlist_store))
    conversation_router = create_conversation_router(
        ConversationRouterDeps(
            resolve_thread_id=_resolve_thread_id,
            get_session_context=_get_session_context,
            list_session_contexts=_list_session_contexts,
            clear_session_context=_clear_session_context,
            list_conversation_records=lambda user_id: get_conversation_store().list(user_id=user_id),
            get_conversation_record=lambda session_id, user_id: get_conversation_store().get(
                session_id, user_id=user_id
            ),
            upsert_conversation_record=lambda session_id, payload, user_id: get_conversation_store().upsert(
                session_id, payload, user_id=user_id
            ),
            delete_conversation_record=lambda session_id, user_id: get_conversation_store().delete(
                session_id, user_id=user_id
            ),
        )
    )
    market_router = create_market_router(
        MarketRouterDeps(
            get_market_data_gateway=get_market_data_gateway,
            logger=logger,
        )
    )
    market_router.add_api_route(
        "/api/dashboard",
        get_dashboard,
        methods=["GET"],
        response_model=DashboardResponse,
        tags=["Market"],
    )
    execution_router = create_execution_router(
        ExecutionRouterDeps(
            resolve_thread_id=_resolve_thread_id,
            schedule_report_index=_schedule_report_index,
            update_session_context=_update_session_context,
        )
    )
    predictions_router = create_predictions_router(
        PredictionsRouterDeps(
            get_service=get_prediction_service,
            check_user_quota=check_user_quota,
            run_outcome_cycle=run_prediction_outcome_cycle,
            is_internal_authorized=_is_internal_api_key_authorized,
        )
    )
    report_router = create_report_router(
        ReportRouterDeps(
            resolve_thread_id=_resolve_thread_id,
            get_report_index_store=get_report_index_store,
        )
    )

    for router in (
        model_router,
        system_router,
        client_recovery_router,
        user_router,
        watchlist_router,
        conversation_router,
        market_router,
        execution_router,
        predictions_router,
        track_record_router,
        monitor_router,
        report_router,
    ):
        app.include_router(router)
    app.include_router(create_skill_router())
    app.include_router(auth_provider_router)
    return app


__all__ = ["create_app"]

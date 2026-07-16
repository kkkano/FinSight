# -*- coding: utf-8 -*-
"""FinSight FastAPI 应用装配。

公共产品面只注册九个 Router：system、user、watchlist、conversation、market、
execution、predictions、monitor 与 report。
"""
from __future__ import annotations

import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.conversation_router import ConversationRouterDeps, create_conversation_router
from backend.api.execution_router import ExecutionRouterDeps, create_execution_router
from backend.api.lifespan import lifespan
from backend.api.market_router import MarketRouterDeps, create_market_router
from backend.api.monitor_router import monitor_router
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
    _contract_info,
    _get_session_context,
    _is_raw_trace_event,
    _list_session_contexts,
    _redact_sensitive_payload,
    _resolve_thread_id,
    _schedule_report_index,
    _update_session_context,
)
from backend.api.system_router import SystemRouterDeps, create_system_router
from backend.api.user_router import create_user_router
from backend.api.watchlist_router import WatchlistRouterDeps, create_watchlist_router
from backend.contracts import SSE_EVENT_SCHEMA_VERSION
from backend.graph import aget_graph_runner, get_graph_checkpointer_info, graph_runner_ready
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
    app = FastAPI(
        title="FinSight API",
        description="可信行情、AI Prediction 与证据化研究 API",
        version="2.0.0",
        lifespan=lifespan,
    )
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
            graph_runner_ready=graph_runner_ready,
            get_graph_checkpointer_info=get_graph_checkpointer_info,
            get_startup_result=get_startup_result,
            get_authentication_health=authentication_health,
            get_database_health=database_health,
            get_market_data_health=market_data_health,
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
            get_graph_runner=aget_graph_runner,
            resolve_thread_id=_resolve_thread_id,
            schedule_report_index=_schedule_report_index,
            update_session_context=_update_session_context,
            redact_sensitive_payload=_redact_sensitive_payload,
            is_raw_trace_event=_is_raw_trace_event,
            contract_info=_contract_info,
            sse_event_schema_version=SSE_EVENT_SCHEMA_VERSION,
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
        system_router,
        user_router,
        watchlist_router,
        conversation_router,
        market_router,
        execution_router,
        predictions_router,
        monitor_router,
        report_router,
    ):
        app.include_router(router)
    return app


__all__ = ["create_app"]

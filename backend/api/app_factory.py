# -*- coding: utf-8 -*-
"""FastAPI 装配工厂（WP3 Task6 机械搬运自 backend/api/main.py，零行为变更）。

create_app()：FastAPI 实例 + security_gate 注册 + CORS + 24 路由构造与列表驱动挂载。
"""
import logging
import json
import asyncio
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import re
import sys
import time
from collections import deque
from threading import Lock
from typing import Any, Dict, List, Optional
from urllib import error as urllib_error
from urllib import request as urllib_request
from uuid import uuid4
from fastapi.responses import JSONResponse
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from backend.api.schemas import (
    ChatRequest,
)
from backend.api.chat_router import ChatRouterDeps, create_chat_router
from backend.api.config_router import ConfigRouterDeps, create_config_router
from backend.api.conversation_router import ConversationRouterDeps, create_conversation_router
from backend.api.dashboard_router import dashboard_router
from backend.api.execution_router import ExecutionRouterDeps, create_execution_router
from backend.api.market_router import MarketRouterDeps, create_market_router
from backend.api.monitor_router import monitor_router
from backend.api.portfolio_router import portfolio_router
from backend.api.attribution_router import attribution_router
from backend.api.rebalance_router import RebalanceRouterDeps, create_rebalance_router
from backend.api.report_router import ReportRouterDeps, create_report_router
from backend.api.research_router import ResearchRouterDeps, create_research_router
from backend.api.subscription_router import create_subscription_router
from backend.api.alerts_router import create_alerts_router
from backend.api.screener_router import screener_router
from backend.api.cn_market_router import cn_market_router
from backend.api.backtest_router import backtest_router
from backend.api.system_router import SystemRouterDeps, create_system_router
from backend.api.morning_brief_router import MorningBriefRouterDeps, create_morning_brief_router
from backend.api.task_router import TaskRouterDeps, create_task_router
from backend.api.tools_router import create_tools_router
from backend.api.skills_router import create_skills_router
from backend.api.agents_router import AgentsRouterDeps, create_agents_router
from backend.api.user_router import UserRouterDeps, create_user_router
from backend.api.watchlist_router import WatchlistRouterDeps, create_watchlist_router
from backend.services.watchlist_store import get_watchlist_store
from backend.services.agent_prediction_store import get_agent_prediction_store
from backend.services.agent_run_archive import get_agent_run_archive
from backend.services.prediction_outcomes import get_prediction_outcome_store
from backend.contracts import CHAT_RESPONSE_SCHEMA_VERSION, SSE_EVENT_SCHEMA_VERSION, contract_manifest
from backend.metrics import METRICS_ENABLED, metrics_payload
from backend.conversation.context import ContextManager
from backend.graph import aget_graph_runner, get_graph_checkpointer_info, graph_runner_ready, reset_graph_runner
from backend.orchestration.tools_bridge import get_global_orchestrator
from backend.graph.nodes.planner import get_planner_ab_metrics
from backend.rag import get_rag_observability_store, install_rag_observability_hooks
from backend.services.langfuse_tracer import flush_langfuse, shutdown_langfuse
from backend.services.portfolio_store import get_positions as get_portfolio_positions
from backend.services.report_index import get_report_index_store
from backend.services.conversation_store import get_conversation_store
from backend.services.cost_audit import get_cost_audit_store

logger = logging.getLogger(__name__)

from backend.api.session_context import (  # WP3-T6 拆分回接
    _build_ui_context,
    _clear_session_context,
    _contract_info,
    _get_orchestrator_safe,
    _get_session_context,
    _is_raw_trace_event,
    _list_session_contexts,
    _redact_sensitive_payload,
    _resolve_query_reference,
    _resolve_thread_id,
    _resolve_trace_raw_enabled,
    _schedule_report_index,
    _update_session_context,
)

from backend.api.lifespan import _init_default_user_config, _schedulers, lifespan  # WP3-T6 拆分回接
from backend.api.security_gate import (  # WP3-T6 拆分回接
    SimpleRateLimiter,
    _AUTH_IDENTITY_CACHE_SENTINEL,
    _auth_identity_cache,
    _auth_identity_cache_ttl_seconds,
    _auth_identity_lock,
    _concurrency_limiter,
    _env_bool,
    _env_int,
    _extract_api_key,
    _extract_bearer_token,
    _fetch_supabase_user_identity,
    _is_allowlisted_path,
    _is_internal_api_key_authorized,
    _is_rag_observability_dev_auth_enabled,
    _is_supabase_auth_configured,
    _parse_api_keys,
    _parse_csv_env,
    _rate_limiter,
    _require_rag_mutation_access,
    _require_rag_read_access,
    _resolve_client_ip,
    _resolve_rag_observability_dev_auth_config,
    _resolve_rag_observability_dev_user_identity,
    _resolve_request_user_identity,
    _resolve_supabase_auth_config,
    _trust_proxy_headers,
    security_gate,
)

# Ensure project root is on sys.path for backend imports.
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Windows + psycopg async 需要 Selector Event LoopPolicy，否则本地 PostgreSQL checkpointer 启动会报错。
if sys.platform.startswith('win') and hasattr(asyncio, 'WindowsSelectorEventLoopPolicy'):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# Load env once for scheduler/SMTP configs, etc.
load_dotenv()

# Logging (avoid duplicate handlers in reload)
if not logging.getLogger().handlers:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

# 鐏忔繆鐦€电厧鍙嗛弽绋跨妇瀹搞儱鍙?
try:
    from backend.tools import (
        get_stock_price,
        get_company_news,
        get_stock_historical_data,
        get_financial_statements,
        get_financial_statements_summary,
        get_company_info,
    )
    logger.info("[Init] Core tools imported successfully.")
except ImportError as e:
    # 婵″倹鐏?backend.tools 鐎电厧鍙嗘径杈Е閿涘苯鍨亸婵婄槸娴犲孩鐗撮惄顔肩秿 tools 鐎电厧鍙嗛敍鍫濆悑鐎硅妫紒鎾寸€敍?
    try:
        from tools import (
            get_stock_price,
            get_company_news,
            get_stock_historical_data,
            get_financial_statements,
            get_financial_statements_summary,
            get_company_info,
        )
        logger.info("[Init] Core tools imported from root successfully.")
    except ImportError as e2:
        logger.info(f"[Init] Error importing tools: {e2}")

# Import chart detector.
try:
    from backend.api.chart_detector import ChartTypeDetector
    logger.info("[Init] Chart detector imported successfully.")
except ImportError as e:
    logger.info(f"[Init] Error importing chart detector: {e}")
    ChartTypeDetector = None

# 鐎电厧鍙?MemoryService
try:
    from backend.services.memory import MemoryService, UserProfile
    memory_service = MemoryService()
    logger.info("[Init] MemoryService initialized successfully.")
except Exception as e:
    logger.info(f"[Init] Error initializing MemoryService: {e}")
    memory_service = None




def _cors_allow_origins() -> list[str]:
    origins = _parse_csv_env(
        "CORS_ALLOW_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
    )
    return origins or [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:5174",
        "http://127.0.0.1:5174",
    ]

def _cors_allow_origin_regex() -> str | None:
    configured = str(os.getenv("CORS_ALLOW_ORIGIN_REGEX") or "").strip()
    if configured:
        return configured
    return r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$"

def _cors_allow_credentials() -> bool:
    allow_credentials = _env_bool("CORS_ALLOW_CREDENTIALS", False)
    origins = _cors_allow_origins()
    if allow_credentials and "*" in origins:
        logger.warning("CORS_ALLOW_CREDENTIALS=true with wildcard origin is invalid. Force disabling credentials.")
        return False
    return allow_credentials


def create_app() -> FastAPI:
    """装配顺序 = 原 main.py 逐行：FastAPI(lifespan) -> security_gate -> CORS -> 路由构造 -> 挂载。"""
    app = FastAPI(
        title="FinSight API",
        description="FinSight 閸氬海顏張宥呭",
        version="1.0.0",
        lifespan=lifespan,
    )







    app.middleware("http")(security_gate)  # WP3-T6：gate 本体已迁 security_gate.py


    # CORS —— 必须注册在 security_gate 之后（add_middleware 是 prepend，后注册 = 最外层）。
    # 这样 security_gate 直接返回的 429/401/503 响应也会被 CORS 包裹；
    # 否则浏览器把这些响应报成 CORS 错误，掩盖真实的限流提示（线上事故 2026-06-03）。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_allow_origins(),
        allow_origin_regex=_cors_allow_origin_regex(),
        allow_credentials=_cors_allow_credentials(),
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Run-Id"],
    )

    # === API routers ===

    chat_router = create_chat_router(
        ChatRouterDeps(
            get_graph_runner=lambda: aget_graph_runner(),
            resolve_thread_id=_resolve_thread_id,
            build_ui_context=_build_ui_context,
            resolve_query_reference=_resolve_query_reference,
            schedule_report_index=_schedule_report_index,
            update_session_context=_update_session_context,
            contract_info=_contract_info,
            resolve_trace_raw_enabled=_resolve_trace_raw_enabled,
            is_raw_trace_event=_is_raw_trace_event,
            redact_sensitive_payload=_redact_sensitive_payload,
            get_session_context=_get_session_context,
            chat_response_schema_version=CHAT_RESPONSE_SCHEMA_VERSION,
            sse_event_schema_version=SSE_EVENT_SCHEMA_VERSION,
        )
    )

    conversation_router = create_conversation_router(
        ConversationRouterDeps(
            resolve_thread_id=_resolve_thread_id,
            get_session_context=_get_session_context,
            list_session_contexts=_list_session_contexts,
            clear_session_context=_clear_session_context,
            list_conversation_records=lambda user_id: get_conversation_store().list(user_id=user_id),
            get_conversation_record=lambda session_id, user_id: get_conversation_store().get(session_id, user_id=user_id),
            upsert_conversation_record=lambda session_id, payload, user_id: get_conversation_store().upsert(session_id, payload, user_id=user_id),
            patch_conversation_record=lambda session_id, payload, user_id: get_conversation_store().patch(session_id, payload, user_id=user_id),
            delete_conversation_record=lambda session_id, user_id: get_conversation_store().delete(session_id, user_id=user_id),
        )
    )

    system_router = create_system_router(
        SystemRouterDeps(
            metrics_enabled=METRICS_ENABLED,
            metrics_payload=metrics_payload,
            graph_runner_ready=graph_runner_ready,
            get_graph_checkpointer_info=get_graph_checkpointer_info,
            get_orchestrator_safe=_get_orchestrator_safe,
            get_planner_ab_metrics=get_planner_ab_metrics,
            get_rag_observability_store=lambda: get_rag_observability_store(),
            get_cost_audit_store=lambda: get_cost_audit_store(),
            require_rag_read_access=lambda request: _require_rag_read_access(request),
            require_rag_mutation_access=lambda request: _require_rag_mutation_access(request),
            memory_service=memory_service,
            logger=logger,
        )
    )

    user_router = create_user_router(
        UserRouterDeps(
            memory_service=memory_service,
            user_profile_cls=UserProfile,
        )
    )
    watchlist_router = create_watchlist_router(
        WatchlistRouterDeps(get_store=get_watchlist_store)
    )

    market_router = create_market_router(
        MarketRouterDeps(
            get_orchestrator_safe=_get_orchestrator_safe,
            get_stock_price=globals().get("get_stock_price") or (lambda _ticker: {"error": "price tool unavailable"}),
            get_company_news=globals().get("get_company_news") or (lambda _ticker: {"error": "news tool unavailable"}),
            get_financial_statements=globals().get("get_financial_statements") or (lambda _ticker: {"error": "financials tool unavailable"}),
            get_financial_statements_summary=globals().get("get_financial_statements_summary") or (lambda _ticker: {"error": "financials summary tool unavailable"}),
            get_stock_historical_data=globals().get("get_stock_historical_data") or (lambda _ticker, **_kwargs: {"error": "history tool unavailable"}),
            detect_chart_type=(ChartTypeDetector.detect_chart_type if ChartTypeDetector else None),
            logger=logger,
        )
    )

    subscription_router = create_subscription_router()
    alerts_router = create_alerts_router()

    config_router = create_config_router(
        ConfigRouterDeps(
            project_root=project_root,
            logger=logger,
        )
    )

    def _safe_fetch_price_snapshot(ticker: str):
        """价差接口用的实时价获取器：导入或拉取失败时诚实降级为 None，不影响主流程。"""
        try:
            from backend.services.alert_scheduler import fetch_price_snapshot
            return fetch_price_snapshot(ticker)
        except Exception:
            return None


    report_router = create_report_router(
        ReportRouterDeps(
            resolve_thread_id=_resolve_thread_id,
            get_report_index_store=lambda: get_report_index_store(),
            fetch_price_snapshot=_safe_fetch_price_snapshot,
        )
    )

    research_router = create_research_router(
        ResearchRouterDeps(
            resolve_thread_id=_resolve_thread_id,
            get_report_index_store=lambda: get_report_index_store(),
        )
    )

    task_router = create_task_router(
        TaskRouterDeps(
            resolve_thread_id=_resolve_thread_id,
            get_report_index_store=lambda: get_report_index_store(),
            get_portfolio_positions=lambda session_id, user_id: get_portfolio_positions(
                session_id, user_id=user_id
            ),
            get_stock_price=globals().get("get_stock_price") or (lambda _ticker: None),
        )
    )
    tools_router = create_tools_router()
    skills_router = create_skills_router()
    agents_router = create_agents_router(AgentsRouterDeps(
        memory_service=memory_service,
        get_prediction_store=get_agent_prediction_store,
        get_outcome_store=get_prediction_outcome_store,
        get_run_archive=get_agent_run_archive,
    ))

    morning_brief_router = create_morning_brief_router(
        MorningBriefRouterDeps(
            resolve_thread_id=_resolve_thread_id,
            get_portfolio_positions=lambda session_id, user_id: get_portfolio_positions(
                session_id, user_id=user_id
            ),
            get_stock_price=globals().get("get_stock_price") or (lambda _ticker: None),
            get_company_news=globals().get("get_company_news") or (lambda _ticker, _limit=5: []),
            get_watchlist=lambda user_id: get_watchlist_store().list_items(user_id=user_id),
            get_graph_runner=lambda: aget_graph_runner(),
        )
    )

    execution_router = create_execution_router(
        ExecutionRouterDeps(
            get_graph_runner=lambda: aget_graph_runner(),
            resolve_thread_id=_resolve_thread_id,
            schedule_report_index=_schedule_report_index,
            update_session_context=_update_session_context,
            redact_sensitive_payload=_redact_sensitive_payload,
            is_raw_trace_event=_is_raw_trace_event,
            contract_info=_contract_info,
            sse_event_schema_version=SSE_EVENT_SCHEMA_VERSION,
        )
    )

    # --- Phase 3: Portfolio & Rebalance routers ---
    from backend.services.rebalance_engine import RebalanceEngine as _RebalanceEngine
    from backend.services.rebalance_llm_enhancer import AgentBackedEnhancer as _AgentBackedEnhancer

    _rebalance_llm_enhancer = _AgentBackedEnhancer(
        get_company_news=globals().get("get_company_news"),
        get_company_info=globals().get("get_company_info"),
        create_llm_fn=None,
    )

    _rebalance_engine = _RebalanceEngine(llm_enhancer=_rebalance_llm_enhancer)

    rebalance_router = create_rebalance_router(
        RebalanceRouterDeps(
            rebalance_engine=_rebalance_engine,
            get_stock_price=globals().get("get_stock_price"),
            get_company_info=globals().get("get_company_info"),
        )
    )

    app.include_router(system_router)
    app.include_router(user_router)
    app.include_router(watchlist_router)
    app.include_router(conversation_router)
    app.include_router(chat_router)
    app.include_router(market_router)
    app.include_router(subscription_router)
    app.include_router(alerts_router)
    app.include_router(screener_router)
    app.include_router(cn_market_router)
    app.include_router(backtest_router)
    app.include_router(config_router)
    app.include_router(report_router)
    app.include_router(research_router)
    app.include_router(task_router)
    app.include_router(tools_router)
    app.include_router(skills_router)
    app.include_router(agents_router)
    app.include_router(execution_router)
    app.include_router(dashboard_router)
    app.include_router(portfolio_router)
    app.include_router(attribution_router)
    app.include_router(monitor_router)
    app.include_router(rebalance_router)
    app.include_router(morning_brief_router)

    return app

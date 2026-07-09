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
from backend.api.agent_router import AgentRouterDeps, create_agent_router
from backend.api.config_router import ConfigRouterDeps, create_config_router
from backend.api.conversation_router import ConversationRouterDeps, create_conversation_router
from backend.api.dashboard_router import dashboard_router
from backend.api.execution_router import ExecutionRouterDeps, create_execution_router
from backend.api.market_router import MarketRouterDeps, create_market_router
from backend.api.monitor_router import monitor_router
from backend.api.portfolio_router import portfolio_router
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
from backend.api.agents_router import create_agents_router
from backend.api.user_router import UserRouterDeps, create_user_router
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

























































































# P1-6: 昂贵生成端点的并发限制（全局 + 单客户端）
from backend.api.concurrency import ConcurrencyLimiter, is_generation_path





# 閸氼垰濮╅崗銉ュ經
if __name__ == "__main__":
    uvicorn.run("backend.api.main:app", host="0.0.0.0", port=8000, reload=True)


# ---- WP3-T6：装配已迁 app_factory；helper 已迁 session_context/security_gate/lifespan ----
from backend.api.app_factory import create_app  # noqa: E402

app = create_app()

from backend.api.session_context import (  # noqa: F401,E402 —— 测试/旧调用方兼容再导出
    _ESSENTIAL_SSE_TYPES,
    _SENSITIVE_KEY_FRAGMENTS,
    _SESSION_PART_PATTERN,
    _build_trace_digest,
    _build_ui_context,
    _cleanup_session_contexts,
    _clear_session_context,
    _clear_thread_rag_artifacts,
    _contract_info,
    _get_orchestrator_safe,
    _get_session_context,
    _index_report_async,
    _is_raw_trace_event,
    _list_session_contexts,
    _mask_secret,
    _normalize_session_key,
    _redact_sensitive_payload,
    _reference_context_last_access,
    _reference_contexts,
    _reference_lock,
    _resolve_query_reference,
    _resolve_thread_id,
    _resolve_trace_raw_enabled,
    _schedule_report_index,
    _summarize_session_context,
    _update_session_context,
)

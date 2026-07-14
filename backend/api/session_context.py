# -*- coding: utf-8 -*-
"""会话上下文/trace/UI 组装 helper（WP3 Task6 机械搬运自 backend/api/main.py，零行为变更）。"""
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




_reference_contexts: Dict[str, ContextManager] = {}

_reference_context_last_access: Dict[str, float] = {}

_reference_lock = Lock()

_SESSION_PART_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

_SENSITIVE_KEY_FRAGMENTS = (
    "api_key",
    "apikey",
    "authorization",
    "auth",
    "token",
    "cookie",
    "password",
    "secret",
)

_ESSENTIAL_SSE_TYPES = {
    "token",
    "done",
    "error",
    "degraded",
    # Execution visibility essentials (kept even when trace_raw is OFF)
    "plan_ready",
    "pipeline_stage",
    "step_start",
    "step_done",
    "step_error",
    "agent_start",
    "agent_done",
    "agent_error",
    "trace",
    "decision_note",
}

def _mask_secret(value: str) -> str:
    raw = str(value or "")
    if len(raw) <= 8:
        return "***"
    return f"{raw[:3]}***{raw[-3:]}"

def _redact_sensitive_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, inner in value.items():
            key_text = str(key).lower()
            if any(fragment in key_text for fragment in _SENSITIVE_KEY_FRAGMENTS):
                # token 计数等数值型指标不是凭据（如 total_tokens/prompt_tokens），不脱敏。
                # 注意 bool 是 int 的子类，需单独判断后一并放行（计数场景不会出现 bool，但保持类型透明）。
                if isinstance(inner, bool) or isinstance(inner, (int, float)):
                    redacted[key] = inner
                    continue
                # 容器类型递归处理（如 tokens_by_model = {"gpt-4": 123}），不整体抹掉，
                # 这样嵌套结构里若真有字符串凭据仍会在递归中被脱敏。
                if isinstance(inner, (dict, list)):
                    redacted[key] = _redact_sensitive_payload(inner)
                    continue
                # 纯数字字符串也是计数不是凭据（如 "12345"），保留原值。
                if isinstance(inner, str) and inner.strip().isdigit():
                    redacted[key] = inner
                    continue
                # 其余情况（真正的字符串凭据，如 "sk-xxx"/"Bearer xxx"）仍然脱敏。
                redacted[key] = _mask_secret(str(inner)) if inner is not None else "***"
                continue
            redacted[key] = _redact_sensitive_payload(inner)
        return redacted
    if isinstance(value, list):
        return [_redact_sensitive_payload(item) for item in value]
    if isinstance(value, str):
        # Best-effort key/token masking in free text.
        masked = re.sub(r"(?i)(sk-[a-z0-9_-]{8,})", lambda m: _mask_secret(m.group(1)), value)
        masked = re.sub(
            r"(?i)(authorization\s*[:=]\s*bearer\s+)([a-z0-9._-]{8,})",
            lambda m: f"{m.group(1)}{_mask_secret(m.group(2))}",
            masked,
        )
        return masked
    return value

def _normalize_session_key(session_id: Optional[str]) -> str:
    raw = (session_id or "").strip()
    if not raw:
        return f"public:anonymous:{uuid4()}"

    parts = raw.split(":")
    if len(parts) == 1:
        parts = ["public", "anonymous", parts[0]]
    elif len(parts) == 2:
        parts = ["public", parts[0], parts[1]]
    elif len(parts) != 3:
        raise ValueError("session_id format invalid, expected tenant:user:thread")

    normalized: list[str] = []
    for idx, part in enumerate(parts):
        text = (part or "").strip()
        if not text:
            raise ValueError("session_id contains empty segment")
        if not _SESSION_PART_PATTERN.fullmatch(text):
            raise ValueError(f"session_id segment[{idx}] contains illegal chars")
        normalized.append(text)
    return ":".join(normalized)

def _resolve_trace_raw_enabled(request: ChatRequest) -> bool:
    default_enabled = _env_bool("TRACE_RAW_ENABLED", True)
    override = None
    if getattr(request, "options", None):
        override = request.options.trace_raw_override
    if override == "on":
        return True
    if override == "off":
        return False
    return default_enabled

def _build_trace_digest(state: dict[str, Any] | None) -> dict[str, Any]:
    payload = state if isinstance(state, dict) else {}
    trace = payload.get("trace") if isinstance(payload.get("trace"), dict) else {}
    spans = trace.get("spans") if isinstance(trace.get("spans"), list) else []
    first_nodes: list[str] = []
    for span in spans[:10]:
        if not isinstance(span, dict):
            continue
        node = span.get("node")
        if isinstance(node, str) and node:
            first_nodes.append(node)
    return {
        "output_mode": payload.get("output_mode"),
        "subject": payload.get("subject"),
        "span_count": len(spans),
        "first_nodes": first_nodes,
    }

def _index_report_async(*, session_id: str, report: dict[str, Any], state: dict[str, Any] | None) -> None:
    try:
        store = get_report_index_store()
        store.upsert_report(
            session_id=session_id,
            report=report,
            trace_digest=_build_trace_digest(state),
        )
    except Exception:
        logger.exception("report index async upsert failed")

def _schedule_report_index(*, session_id: str, report: dict[str, Any], state: dict[str, Any] | None) -> None:
    if not (isinstance(report, dict) and report.get("report_id")):
        return
    try:
        import asyncio as _asyncio

        _asyncio.get_running_loop().run_in_executor(
            None,
            lambda: _index_report_async(session_id=session_id, report=report, state=state),
        )
    except Exception:
        logger.exception("schedule async report indexing failed")

def _is_raw_trace_event(payload: dict[str, Any]) -> bool:
    event_type = str(payload.get("type") or "").strip().lower()
    if not event_type:
        return True
    return event_type not in _ESSENTIAL_SSE_TYPES

def _resolve_thread_id(session_id: Optional[str]) -> str:
    return _normalize_session_key(session_id)

def _cleanup_session_contexts(now_ts: Optional[float] = None) -> None:
    now = now_ts if now_ts is not None else time.time()
    ttl_minutes = max(1, _env_int("SESSION_CONTEXT_TTL_MINUTES", 240))
    ttl_seconds = ttl_minutes * 60
    max_threads = max(16, _env_int("SESSION_CONTEXT_MAX_THREADS", 1000))

    expired = [
        sid
        for sid, last_access in list(_reference_context_last_access.items())
        if now - float(last_access) >= ttl_seconds
    ]
    for sid in expired:
        _reference_contexts.pop(sid, None)
        _reference_context_last_access.pop(sid, None)

    current_size = len(_reference_contexts)
    if current_size <= max_threads:
        return

    overflow = current_size - max_threads
    oldest_first = sorted(
        _reference_context_last_access.items(),
        key=lambda item: item[1],
    )
    for sid, _ in oldest_first[:overflow]:
        _reference_contexts.pop(sid, None)
        _reference_context_last_access.pop(sid, None)

def _get_session_context(session_id: str) -> ContextManager:
    with _reference_lock:
        now = time.time()
        _cleanup_session_contexts(now)
        manager = _reference_contexts.get(session_id)
        if manager is None:
            manager = ContextManager(max_turns=20)
            _reference_contexts[session_id] = manager
        _reference_context_last_access[session_id] = now
        return manager

def _summarize_session_context(session_id: str, manager: ContextManager) -> dict[str, Any]:
    try:
        state = manager.get_state()
    except Exception:
        state = {}
    if not isinstance(state, dict):
        state = {}
    return {
        "session_id": session_id,
        "turns": int(state.get("turns") or 0),
        "current_focus": state.get("current_focus"),
        "current_focus_name": state.get("current_focus_name"),
        "current_focus_market": state.get("current_focus_market"),
        "pending_clarification": bool(state.get("pending_clarification")),
        "cached_data_keys": state.get("cached_data_keys") if isinstance(state.get("cached_data_keys"), list) else [],
        "last_access": _reference_context_last_access.get(session_id),
    }

def _list_session_contexts() -> list[dict[str, Any]]:
    with _reference_lock:
        _cleanup_session_contexts(time.time())
        items = [
            _summarize_session_context(session_id, manager)
            for session_id, manager in _reference_contexts.items()
        ]
    return sorted(items, key=lambda item: float(item.get("last_access") or 0), reverse=True)

def _clear_thread_rag_artifacts(thread_id: str) -> dict[str, int]:
    deleted_collections = 0
    soft_deleted_runs = 0
    try:
        from backend.rag import get_rag_service
        from backend.rag.layering import build_thread_memory_collection, build_thread_working_set_collection

        collections = [
            build_thread_working_set_collection(thread_id),
            build_thread_memory_collection(thread_id=thread_id),
        ]
        service = get_rag_service()
        delete_collections = getattr(service, "delete_collections", None)
        if callable(delete_collections):
            deleted_collections = int(delete_collections(collections=collections) or 0)

        store = get_rag_observability_store()
        soft_delete_runs_for_collections = getattr(store, "soft_delete_runs_for_collections", None)
        if callable(soft_delete_runs_for_collections):
            soft_deleted_runs = int(
                soft_delete_runs_for_collections(
                    collections=collections,
                    deleted_by="conversation_api",
                    reason="conversation_deleted",
                )
                or 0
            )
            return {"rag_collections": deleted_collections, "rag_runs": soft_deleted_runs}

        list_runs = getattr(store, "list_runs", None)
        soft_delete_run = getattr(store, "soft_delete_run", None)
        if callable(list_runs) and callable(soft_delete_run):
            cursor = None
            seen_cursors: set[str] = set()
            while True:
                runs = list_runs(limit=200, cursor=cursor, include_deleted=False)
                for item in runs.get("items") or []:
                    if not isinstance(item, dict):
                        continue
                    if str(item.get("collection") or "").strip() not in collections:
                        continue
                    run_id = str(item.get("id") or "").strip()
                    if not run_id:
                        continue
                    soft_delete_run(run_id, deleted_by="conversation_api", reason="conversation_deleted")
                    soft_deleted_runs += 1
                next_cursor = str(runs.get("next_cursor") or "").strip()
                if not next_cursor or next_cursor in seen_cursors:
                    break
                seen_cursors.add(next_cursor)
                cursor = next_cursor
    except Exception:
        logger.exception("failed to clear RAG artifacts for session")
    return {"rag_collections": deleted_collections, "rag_runs": soft_deleted_runs}

def _clear_session_context(thread_id: str) -> dict[str, Any]:
    normalized = str(thread_id or "").strip()
    result: dict[str, Any] = {
        "context": False,
        "reports": 0,
        "citations": 0,
        "rag_collections": 0,
        "rag_runs": 0,
    }
    if not normalized:
        return result

    with _reference_lock:
        manager = _reference_contexts.pop(normalized, None)
        _reference_context_last_access.pop(normalized, None)
    if manager is not None:
        try:
            manager.clear()
        except Exception:
            logger.debug("session context clear failed after pop", exc_info=True)
        result["context"] = True

    try:
        delete_session = getattr(get_report_index_store(), "delete_session", None)
        if callable(delete_session):
            deleted = delete_session(session_id=normalized)
            if isinstance(deleted, dict):
                result["reports"] = int(deleted.get("reports") or 0)
                result["citations"] = int(deleted.get("citations") or 0)
    except Exception:
        logger.exception("failed to delete report index session")

    result.update(_clear_thread_rag_artifacts(normalized))
    return result

def _resolve_query_reference(query: str, thread_id: str) -> str:
    try:
        return _get_session_context(thread_id).resolve_reference(query)
    except Exception:
        return query

def _update_session_context(
    *,
    thread_id: str,
    original_query: str,
    response_markdown: str,
    subject: Optional[Dict[str, Any]] = None,
    skip_context: bool = False,
) -> None:
    if not thread_id:
        return
    # 閹稿洣鎶ら崹瀣惙娴ｆ粣绱欐俊?alert_set閿涘绗夋惔鏃€钖勯弻鎾愁嚠鐠囨繀绗傛稉瀣瀮
    if skip_context:
        return
    try:
        tickers: list[str] = []
        if isinstance(subject, dict):
            candidates = [str(t).strip().upper() for t in (subject.get("tickers") or []) if str(t).strip()]
            query_upper = str(original_query or "").upper()
            explicit = [
                ticker
                for ticker in candidates
                if re.search(rf"(?<![A-Z0-9]){re.escape(ticker)}(?![A-Z0-9])", query_upper)
            ]
            # 显式 ticker 全保留；公司名解析等隐式场景只接受主 ticker，阻止 ATM/CNN/RSI 扩散。
            tickers = explicit or candidates[:1]
        metadata: Dict[str, Any] = {}
        if tickers:
            metadata["tickers"] = tickers
        _get_session_context(thread_id).add_turn(
            query=original_query,
            intent="chat",
            response=response_markdown or "",
            metadata=metadata,
        )
    except Exception:
        logger.exception("failed to update session context")

def _build_ui_context(request: ChatRequest) -> Dict[str, Any]:
    ui_context: Dict[str, Any] = {}
    if not request.context:
        return ui_context
    if request.context.active_symbol:
        ui_context["active_symbol"] = request.context.active_symbol
    if request.context.view:
        ui_context["view"] = request.context.view
    if request.context.source_view:
        ui_context["source_view"] = request.context.source_view
    if request.context.source_tab:
        ui_context["source_tab"] = request.context.source_tab

    selections: List[Dict[str, Any]] = []
    if request.context.selection:
        selections.append(request.context.selection.model_dump())
    if getattr(request.context, "selections", None):
        selections.extend([s.model_dump() for s in (request.context.selections or []) if s])
    if selections:
        ui_context["selections"] = selections
    if request.context.user_email:
        ui_context["user_email"] = request.context.user_email

    raw_context = request.context.model_dump(exclude_none=True)
    for key in ("portfolio", "positions", "holdings"):
        value = raw_context.get(key)
        if value:
            ui_context[key] = value
    return ui_context

def _contract_info() -> Dict[str, str]:
    return contract_manifest()

def _get_orchestrator_safe():
    try:
        return get_global_orchestrator()
    except Exception:
        logger.exception("failed to initialize orchestrator")
        return None

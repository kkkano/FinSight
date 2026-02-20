import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import re
import sys
import time
from collections import deque
from threading import Lock
from typing import Any, Dict, List, Optional
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
from backend.api.dashboard_router import dashboard_router
from backend.api.execution_router import ExecutionRouterDeps, create_execution_router
from backend.api.market_router import MarketRouterDeps, create_market_router
from backend.api.portfolio_router import portfolio_router
from backend.api.rebalance_router import RebalanceRouterDeps, create_rebalance_router
from backend.api.report_router import ReportRouterDeps, create_report_router
from backend.api.subscription_router import create_subscription_router
from backend.api.alerts_router import create_alerts_router
from backend.api.system_router import SystemRouterDeps, create_system_router
from backend.api.task_router import TaskRouterDeps, create_task_router
from backend.api.tools_router import create_tools_router
from backend.api.user_router import UserRouterDeps, create_user_router
from backend.contracts import CHAT_RESPONSE_SCHEMA_VERSION, SSE_EVENT_SCHEMA_VERSION, contract_manifest
from backend.metrics import METRICS_ENABLED, metrics_payload
from backend.conversation.context import ContextManager
from backend.graph import aget_graph_runner, get_graph_checkpointer_info, graph_runner_ready
from backend.orchestration.tools_bridge import get_global_orchestrator
from backend.graph.nodes.planner import get_planner_ab_metrics
from backend.services.langfuse_tracer import flush_langfuse, shutdown_langfuse
from backend.services.portfolio_store import get_positions as get_portfolio_positions
from backend.services.report_index import get_report_index_store

logger = logging.getLogger(__name__)

# Ensure project root is on sys.path for backend imports.
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Load env once for scheduler/SMTP configs, etc.
load_dotenv()

# Logging (avoid duplicate handlers in reload)
if not logging.getLogger().handlers:
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

# 灏濊瘯瀵煎叆鏍稿績宸ュ叿
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
    # 如果 backend.tools 导入失败，则尝试从根目录 tools 导入（兼容旧结构）
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
        logger.info(f"❌ Error importing tools: {e2}")

# Import chart detector.
try:
    from backend.api.chart_detector import ChartTypeDetector
    logger.info("[Init] Chart detector imported successfully.")
except ImportError as e:
    logger.info(f"[Init] Error importing chart detector: {e}")
    ChartTypeDetector = None

# 瀵煎叆 MemoryService
try:
    from backend.services.memory import MemoryService, UserProfile
    memory_service = MemoryService()
    logger.info("[Init] MemoryService initialized successfully.")
except Exception as e:
    logger.info(f"[Init] Error initializing MemoryService: {e}")
    memory_service = None


_schedulers = []
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
    # Execution visibility essentials (kept even when trace_raw is OFF)
    "plan_ready",
    "pipeline_stage",
    "step_start",
    "step_done",
    "step_error",
    "agent_start",
    "agent_done",
    "agent_error",
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
    default_enabled = _env_bool("TRACE_RAW_ENABLED", "true")
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
) -> None:
    if not thread_id:
        return
    try:
        tickers = []
        if isinstance(subject, dict):
            tickers = [str(t).strip().upper() for t in (subject.get("tickers") or []) if str(t).strip()]
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

    selections: List[Dict[str, Any]] = []
    if request.context.selection:
        selections.append(request.context.selection.model_dump())
    if getattr(request.context, "selections", None):
        selections.extend([s.model_dump() for s in (request.context.selections or []) if s])
    if selections:
        ui_context["selections"] = selections
    return ui_context


def _contract_info() -> Dict[str, str]:
    return contract_manifest()


def _get_orchestrator_safe():
    try:
        return get_global_orchestrator()
    except Exception:
        logger.exception("failed to initialize orchestrator")
        return None

def _env_bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).lower() in ("true", "1", "yes", "on")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except Exception:
        return default


def _parse_csv_env(key: str, default: str) -> list[str]:
    raw = os.getenv(key, default)
    values = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    return values


def _cors_allow_origins() -> list[str]:
    origins = _parse_csv_env("CORS_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
    return origins or ["http://localhost:5173", "http://127.0.0.1:5173"]


def _cors_allow_credentials() -> bool:
    allow_credentials = _env_bool("CORS_ALLOW_CREDENTIALS", "false")
    origins = _cors_allow_origins()
    if allow_credentials and "*" in origins:
        logger.warning("CORS_ALLOW_CREDENTIALS=true with wildcard origin is invalid. Force disabling credentials.")
        return False
    return allow_credentials


def _parse_api_keys() -> set[str]:
    raw = os.getenv("API_AUTH_KEYS") or os.getenv("API_AUTH_KEY") or ""
    return {item.strip() for item in raw.split(",") if item.strip()}


def _extract_api_key(request: Request) -> Optional[str]:
    header_key = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    if header_key:
        return header_key.strip()
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None


def _is_allowlisted_path(path: str) -> bool:
    defaults = "/health,/docs,/openapi.json,/redoc"
    configured = _parse_csv_env("API_PUBLIC_PATHS", defaults)
    exact_paths: set[str] = set()
    prefix_paths: list[str] = []

    for entry in configured:
        normalized = entry if entry.startswith("/") else f"/{entry}"
        if normalized.endswith("/*"):
            base = normalized[:-2]
            if base:
                prefix_paths.append(base)
        elif normalized in ("/docs", "/redoc"):
            exact_paths.add(normalized)
            prefix_paths.append(normalized)
        else:
            exact_paths.add(normalized)

    if path in exact_paths:
        return True
    return any(path.startswith(prefix + "/") or path == prefix for prefix in prefix_paths)


class SimpleRateLimiter:
    def __init__(self, limit_per_window: int, window_seconds: int, enabled: bool = True):
        self.enabled = enabled
        self.limit = max(1, int(limit_per_window))
        self.window_seconds = max(1, int(window_seconds))
        self._buckets: Dict[str, deque[float]] = {}
        self._last_cleanup = time.time()

    def _cleanup(self, now: float) -> None:
        if now - self._last_cleanup < self.window_seconds:
            return
        self._last_cleanup = now
        stale_keys = [
            key for key, bucket in self._buckets.items()
            if not bucket or (now - bucket[-1] >= self.window_seconds)
        ]
        for key in stale_keys:
            self._buckets.pop(key, None)

    @classmethod
    def from_env(cls) -> "SimpleRateLimiter":
        enabled = _env_bool("RATE_LIMIT_ENABLED", "false")
        limit = int(os.getenv("RATE_LIMIT_PER_MINUTE", "120"))
        window_seconds = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
        return cls(limit_per_window=limit, window_seconds=window_seconds, enabled=enabled)

    def allow(self, key: str) -> tuple[bool, Optional[int]]:
        now = time.time()
        self._cleanup(now)
        bucket = self._buckets.setdefault(key, deque())
        while bucket and now - bucket[0] >= self.window_seconds:
            bucket.popleft()
        if len(bucket) >= self.limit:
            retry_after = int(self.window_seconds - (now - bucket[0])) if bucket else self.window_seconds
            return False, max(1, retry_after)
        bucket.append(now)
        return True, None


_rate_limiter = SimpleRateLimiter.from_env()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan handler to start/stop price_change scheduler."""
    from backend.services.alert_scheduler import run_price_change_cycle
    from backend.services.scheduler_runner import start_price_change_scheduler

    enabled = _env_bool("PRICE_ALERT_SCHEDULER_ENABLED", "false")
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
    news_enabled = _env_bool("NEWS_ALERT_SCHEDULER_ENABLED", "false")
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
    risk_enabled = _env_bool("RISK_ALERT_SCHEDULER_ENABLED", "false")
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
    health_enabled = _env_bool("HEALTH_PROBE_ENABLED", "false")
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
                sched.shutdown(wait=False)
            if _schedulers:
                logger.info("[Scheduler] all schedulers stopped.")
        except Exception as e:
            logger.info(f"[Scheduler] shutdown error: {e}")

app = FastAPI(
    title="FinSight API",
    description="FinSight 鍚庣鏈嶅姟",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 閰嶇疆
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_allow_origins(),
    allow_credentials=_cors_allow_credentials(),
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def security_gate(request: Request, call_next):
    if _is_allowlisted_path(request.url.path):
        return await call_next(request)

    api_key = None
    if _env_bool("API_AUTH_ENABLED", "false"):
        keys = _parse_api_keys()
        if not keys:
            return JSONResponse(status_code=503, content={"detail": "API auth enabled but no keys configured"})
        api_key = _extract_api_key(request)
        if not api_key or api_key not in keys:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    if _rate_limiter.enabled:
        client_id = api_key or (request.client.host if request.client else "anonymous")
        allowed, retry_after = _rate_limiter.allow(client_id)
        if not allowed:
            headers = {"Retry-After": str(retry_after)}
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"}, headers=headers)

    return await call_next(request)

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

system_router = create_system_router(
    SystemRouterDeps(
        metrics_enabled=METRICS_ENABLED,
        metrics_payload=metrics_payload,
        graph_runner_ready=graph_runner_ready,
        get_graph_checkpointer_info=get_graph_checkpointer_info,
        get_orchestrator_safe=_get_orchestrator_safe,
        get_planner_ab_metrics=get_planner_ab_metrics,
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

agent_router = create_agent_router(
    AgentRouterDeps(
        memory_service=memory_service,
    )
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

report_router = create_report_router(
    ReportRouterDeps(
        resolve_thread_id=_resolve_thread_id,
        get_report_index_store=lambda: get_report_index_store(),
    )
)

task_router = create_task_router(
    TaskRouterDeps(
        resolve_thread_id=_resolve_thread_id,
        get_report_index_store=lambda: get_report_index_store(),
        get_portfolio_positions=get_portfolio_positions,
        get_stock_price=globals().get("get_stock_price") or (lambda _ticker: None),
    )
)
tools_router = create_tools_router()

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

_rebalance_engine = _RebalanceEngine()

rebalance_router = create_rebalance_router(
    RebalanceRouterDeps(
        rebalance_engine=_rebalance_engine,
        get_stock_price=globals().get("get_stock_price"),
        get_company_info=globals().get("get_company_info"),
    )
)

app.include_router(system_router)
app.include_router(user_router)
app.include_router(agent_router)
app.include_router(chat_router)
app.include_router(market_router)
app.include_router(subscription_router)
app.include_router(alerts_router)
app.include_router(config_router)
app.include_router(report_router)
app.include_router(task_router)
app.include_router(tools_router)
app.include_router(execution_router)
app.include_router(dashboard_router)
app.include_router(portfolio_router)
app.include_router(rebalance_router)
# 启动入口
if __name__ == "__main__":
    uvicorn.run("backend.api.main:app", host="0.0.0.0", port=8000, reload=True)

import logging
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import os
import sys
import traceback
import time
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from fastapi.responses import StreamingResponse, JSONResponse, Response
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from backend.api.streaming import stream_report_sse, stream_supervisor_sse
from backend.api.schemas import (
    ChatRequest, SubscriptionRequest, UnsubscribeRequest, ToggleSubscriptionRequest,
    ChatResponse, SupervisorResponse, HealthResponse, RootResponse,
    DiagnosticsResponse, UserProfileResponse, SubscriptionResponse,
    SubscriptionListResponse, StockDataResponse, KlineResponse,
    ConfigResponse, ChartDetectResponse, ChartDataResponse,
)
from backend.metrics import METRICS_ENABLED, metrics_payload

logger = logging.getLogger(__name__)

# 将项目根目录添加到 sys.path
# 这样可以确保 backend modules 等模块能被找到
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

# 尝试导入核心工具
try:
    from backend.tools import get_stock_price, get_company_news, get_stock_historical_data, get_financial_statements, get_financial_statements_summary
    logger.info("[Init] Core tools imported successfully.")
except ImportError as e:
    # 如果 backend.tools 失败，尝试从根目录 tools 导入（兼容旧结构）
    try:
        from tools import get_stock_price, get_company_news, get_stock_historical_data, get_financial_statements, get_financial_statements_summary
        logger.info("[Init] Core tools imported from root successfully.")
    except ImportError as e2:
        logger.info(f"❌ Error importing tools: {e2}")

# 导入图表检测器
try:
    from backend.api.chart_detector import ChartTypeDetector
    logger.info("[Init] Chart detector imported successfully.")
except ImportError as e:
    logger.info(f"❌ Error importing chart detector: {e}")
    ChartTypeDetector = None

# 导入 Agent
from backend.conversation.agent import create_agent
from backend.llm_config import create_llm  # 导入 create_llm 以支持热加载

# 导入 MemoryService
try:
    from backend.services.memory import MemoryService, UserProfile
    memory_service = MemoryService()
    logger.info("[Init] MemoryService initialized successfully.")
except Exception as e:
    logger.info(f"[Init] Error initializing MemoryService: {e}")
    memory_service = None

# 初始化 Agent
try:
    # 尝试初始化，如果失败则打印详细堆栈
    agent = create_agent(
        use_llm=True,
        use_orchestrator=True
    )
    logger.info("[Init] ConversationAgent initialized successfully.")
except Exception as e:
    logger.info(f"[Init] Error initializing ConversationAgent: {e}")
    traceback.print_exc()
    agent = None

_schedulers = []

def _env_bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).lower() in ("true", "1", "yes", "on")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except Exception:
        return default


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
    allow_prefixes = ("/", "/docs", "/openapi.json", "/redoc", "/health")
    return path in allow_prefixes or path.startswith(("/docs", "/redoc"))


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
        yield
    finally:
        try:
            for sched in _schedulers:
                sched.shutdown(wait=False)
            if _schedulers:
                logger.info("[Scheduler] all schedulers stopped.")
        except Exception as e:
            logger.info(f"[Scheduler] shutdown error: {e}")

# 初始化 FastAPI
app = FastAPI(
    title="FinSight API",
    description="FinSight 后端服务",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS 配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
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

# === API 端点 ===

@app.get("/api/user/profile")
async def get_user_profile(user_id: str = "default_user"):
    """获取用户画像"""
    if not memory_service:
        return {"error": "MemoryService not initialized"}

    try:
        profile = memory_service.get_user_profile(user_id)
        return {"success": True, "profile": profile.to_dict()}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/user/profile")
async def update_user_profile(request: dict):
    """更新用户画像"""
    if not memory_service:
        return {"error": "MemoryService not initialized"}

    try:
        user_id = request.get("user_id", "default_user")
        profile_data = request.get("profile", {})

        # 确保 user_id 一致
        profile_data["user_id"] = user_id

        profile = UserProfile.from_dict(profile_data)
        success = memory_service.update_user_profile(profile)

        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/user/watchlist/add")
async def add_watchlist(request: dict):
    """添加关注"""
    if not memory_service:
        return {"error": "MemoryService not initialized"}

    try:
        user_id = request.get("user_id", "default_user")
        ticker = request.get("ticker")

        if not ticker:
            return {"success": False, "error": "Ticker is required"}

        success = memory_service.add_to_watchlist(user_id, ticker)
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/user/watchlist/remove")
async def remove_watchlist(request: dict):
    """取消关注"""
    if not memory_service:
        return {"error": "MemoryService not initialized"}

    try:
        user_id = request.get("user_id", "default_user")
        ticker = request.get("ticker")

        if not ticker:
            return {"success": False, "error": "Ticker is required"}

        success = memory_service.remove_from_watchlist(user_id, ticker)
        return {"success": success}
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.get("/", response_model=RootResponse)
def read_root():
    """
    根路径健康检查，附带简要说明。
    """
    return {
        "status": "healthy",
        "message": "FinSight API is running",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/health")
def health_check():
    """
    增强健康检查端点 - 包含子Agent状态和后端服务状态
    """
    # 基础状态
    status = "healthy"
    components = {}

    # 检查 Agent 状态
    if agent:
        components["agent"] = {"status": "ok", "available": True}

        # 检查 LLM
        has_llm = hasattr(agent, "llm") and agent.llm is not None
        components["llm"] = {"status": "ok" if has_llm else "unavailable"}

        # 检查 Orchestrator
        has_orchestrator = hasattr(agent, "orchestrator") and agent.orchestrator is not None
        components["orchestrator"] = {"status": "ok" if has_orchestrator else "unavailable"}

        # 检查 Orchestrator 内部组件
        if has_orchestrator:
            has_cache = hasattr(agent.orchestrator, 'cache') and agent.orchestrator.cache is not None
            has_tools = hasattr(agent.orchestrator, 'tools_module') and agent.orchestrator.tools_module is not None
            components["cache"] = {"status": "ok" if has_cache else "unavailable"}
            components["tools_module"] = {"status": "ok" if has_tools else "unavailable"}

        # 检查子 Agent（只有 llm + orchestrator + cache + tools_module 都存在才会初始化）
        if hasattr(agent, "news_agent") and agent.news_agent:
            components["news_agent"] = {"status": "ok"}
        else:
            components["news_agent"] = {"status": "unavailable", "reason": "not initialized"}

        if hasattr(agent, "price_agent") and agent.price_agent:
            components["price_agent"] = {"status": "ok"}
        else:
            components["price_agent"] = {"status": "unavailable", "reason": "not initialized"}

        # 检查 Supervisor
        if hasattr(agent, "supervisor") and agent.supervisor:
            components["supervisor"] = {"status": "ok"}
        else:
            components["supervisor"] = {"status": "unavailable"}
    else:
        status = "degraded"
        components["agent"] = {"status": "error", "available": False}

    # 检查 MemoryService
    if memory_service:
        components["memory"] = {"status": "ok"}
    else:
        components["memory"] = {"status": "unavailable"}

    return {
        "status": status,
        "components": components,
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/metrics")
def metrics_endpoint():
    """Prometheus metrics endpoint (optional)."""
    if not METRICS_ENABLED:
        raise HTTPException(status_code=404, detail="metrics disabled")
    payload, content_type = metrics_payload()
    return Response(content=payload, media_type=content_type)


@app.get("/diagnostics/orchestrator", response_model=DiagnosticsResponse)
def diagnostics_orchestrator():
    """
    返回 Orchestrator 的聚合健康信息：总请求、缓存命中、回退次数、按源统计。
    供前端健康面板使用。
    """
    if not agent or not getattr(agent, "orchestrator", None):
        raise HTTPException(status_code=500, detail="Orchestrator not initialized")
    try:
        stats = agent.orchestrator.get_stats()
        return {
            "status": "ok",
            "data": stats,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"orchestrator diagnostics failed: {exc}")

@app.post("/chat/supervisor")
async def chat_supervisor_endpoint(request: ChatRequest):
    """
    协调者模式对话接口 - Supervisor Agent 架构
    意图分类(规则+LLM) → Supervisor协调 → Worker Agents → Forum综合
    """
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")

    try:
        # 动态创建 LLM 以支持配置热加载
        try:
            current_llm = create_llm()
        except Exception as e:
            logger.error(f"Failed to create LLM: {e}")
            current_llm = agent.llm  # 回退到全局 LLM
            
        if not current_llm:
             raise HTTPException(status_code=500, detail="LLM not initialized")

        from backend.orchestration.supervisor_agent import SupervisorAgent
        from backend.conversation.router import extract_tickers, Intent

        preprocess = agent.context.preprocess_query(request.query)
        prepared_query = preprocess.get("query", request.query)
        resolved_query = agent.context.resolve_reference(prepared_query)

        intent, metadata, _handler = agent.router.route(resolved_query, agent.context)
        selected_ticker = preprocess.get("selected_ticker")
        if selected_ticker and selected_ticker not in metadata.get("tickers", []):
            metadata.setdefault("tickers", []).insert(0, selected_ticker)
        if preprocess.get("selection_reason"):
            metadata["selection_reason"] = preprocess.get("selection_reason")
        if preprocess.get("market_hint"):
            metadata["market_hint"] = preprocess.get("market_hint")

        if intent == Intent.CLARIFY:
            question = metadata.get("schema_question") or "Please provide more details."
            return {
                "success": True,
                "response": question,
                "schema_question": question,
                "intent": "clarify",
                "classification": {"method": "schema_router", "confidence": 0.95},
                "session_id": request.session_id or "new_session",
                "needs_clarification": True,
                "missing_fields": metadata.get("schema_missing", []),
                "schema_tool_name": metadata.get("schema_tool_name"),
                "source": metadata.get("source", "schema_router"),
            }

        tickers = metadata.get("tickers", [])
        if not tickers:
            tickers_result = extract_tickers(resolved_query)
            tickers = tickers_result.get("tickers", []) if isinstance(tickers_result, dict) else tickers_result


        

        # 获取 tools_module, cache, circuit_breaker (从 orchestrator 获取)
        tools_module = None
        cache = None
        circuit_breaker = None
        orchestrator = getattr(agent, "orchestrator", None)
        if orchestrator:
            tools_module = getattr(orchestrator, 'tools_module', None)
            cache = getattr(orchestrator, 'cache', None)
            circuit_breaker = getattr(orchestrator, 'circuit_breaker', None)
        if not tools_module:
            import backend.tools as tools_module

        # 创建 Supervisor Agent
        # 创建 Supervisor Agent
        supervisor = SupervisorAgent(
            llm=current_llm,
            tools_module=tools_module,
            cache=cache,
            circuit_breaker=circuit_breaker
        )

        # 执行
        result = await supervisor.process(request.query, tickers)

        return {
            "success": result.success,
            "response": result.response,
            "intent": result.intent.value if result.intent else None,
            "classification": {
                "method": result.classification.method if result.classification else None,
                "confidence": result.classification.confidence if result.classification else None,
            } if result.classification else None,
            "session_id": request.session_id or "new_session",
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


# 主入口流式端点
@app.post("/chat/supervisor/stream")
async def chat_supervisor_stream_endpoint(request: ChatRequest):
    """
    协调者模式流式接口 - 实时报告意图分类和执行进度
    支持多轮对话上下文
    """
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
        
    # 动态创建 LLM 以支持配置热加载
    try:
        current_llm = create_llm()
    except Exception as e:
        logger.error(f"Failed to create LLM: {e}")
        current_llm = agent.llm  # 回退到全局 LLM
        
    if not current_llm:
         raise HTTPException(status_code=500, detail="LLM not initialized")

    import json as _json

    from backend.orchestration.supervisor_agent import SupervisorAgent
    from backend.conversation.router import extract_tickers, Intent

    preprocess = agent.context.preprocess_query(request.query)
    prepared_query = preprocess.get("query", request.query)
    resolved_query = agent.context.resolve_reference(prepared_query)

    

    intent, metadata, _handler = agent.router.route(resolved_query, agent.context)
    selected_ticker = preprocess.get("selected_ticker")
    if selected_ticker and selected_ticker not in metadata.get("tickers", []):
        metadata.setdefault("tickers", []).insert(0, selected_ticker)
    if preprocess.get("selection_reason"):
        metadata["selection_reason"] = preprocess.get("selection_reason")
    if preprocess.get("market_hint"):
        metadata["market_hint"] = preprocess.get("market_hint")

    if intent == Intent.CLARIFY:
        question = metadata.get("schema_question") or "Please provide more details."

        async def clarify_response():
            yield f"data: {_json.dumps({'type': 'token', 'content': question}, ensure_ascii=False)}\n\n"
            yield f"data: {_json.dumps({'type': 'done', 'intent': 'clarify', 'needs_clarification': True, 'schema_question': question, 'missing_fields': metadata.get('schema_missing', []), 'schema_tool_name': metadata.get('schema_tool_name'), 'source': metadata.get('source', 'schema_router')}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            clarify_response(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    tickers = metadata.get("tickers", [])
    if not tickers:
        tickers_result = extract_tickers(resolved_query)
        tickers = tickers_result.get('tickers', []) if isinstance(tickers_result, dict) else tickers_result

    agent_gate = None
    if hasattr(agent, "evaluate_agent_gate"):
        agent_gate = agent.evaluate_agent_gate(resolved_query, intent, metadata)
        # Supervisor endpoint always uses agent; override if needed
        if agent_gate.exclusion_reason == "supervisor_unavailable":
            agent_gate.exclusion_reason = None
            agent_gate.need_agent = True
            agent_gate.should_use_supervisor = True
        agent_gate.used_supervisor = True
        agent_gate.agent_path = "supervisor"
        if hasattr(agent_gate, "to_dict"):
            metadata["agent_gate"] = agent_gate.to_dict()

    # 构建对话上下文
    # 注意：对于报告生成，不依赖历史上下文，只依赖当前问题
    # 这样可以避免闲聊消息（如打招呼）污染报告内容
    conversation_context = None
    # if request.history:
    #     max_history = _env_int("CHAT_HISTORY_MAX_MESSAGES", 12)
    #     conversation_context = [
    #         {"role": msg.role, "content": msg.content}
    #         for msg in request.history[-max_history:]
    #     ]

    # 获取 tools_module, cache, circuit_breaker (从 orchestrator 获取)
    tools_module = None
    cache = None
    circuit_breaker = None
    orchestrator = getattr(agent, "orchestrator", None)
    if orchestrator:
        tools_module = getattr(orchestrator, 'tools_module', None)
        cache = getattr(orchestrator, 'cache', None)
        circuit_breaker = getattr(orchestrator, 'circuit_breaker', None)
    if not tools_module:
        import backend.tools as tools_module

    # 创建 Supervisor Agent
    # 创建 Supervisor Agent
    supervisor = SupervisorAgent(
        llm=current_llm,
        tools_module=tools_module,
        cache=cache,
        circuit_breaker=circuit_breaker
    )

    async def generate():
        async for chunk in supervisor.process_stream(
            resolved_query,
            tickers,
            conversation_context=conversation_context,
            agent_gate=metadata.get("agent_gate"),
        ):
            yield f"data: {chunk}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


# 保留旧流式端点兼容
@app.post("/api/chat/add-chart-data", response_model=ChartDataResponse)
async def add_chart_data(request: dict):
    """
    将图表数据摘要加入聊天上下文
    前端在生成图表后调用此接口
    """
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    
    try:
        ticker = request.get('ticker')
        summary = request.get('summary', '')
        
        if not ticker or not summary:
            return {"success": False, "error": "Missing ticker or summary"}
        
        # 将图表数据摘要作为系统消息加入上下文
        # 这样后续对话时AI可以看到这些数据
        chart_message = f"[图表数据] {summary}"
        agent.context.add_turn(
            query=f"查看 {ticker} 的图表数据",
            intent="chat",
            response=chart_message,
            metadata={"ticker": ticker, "chart_data": True}
        )
        
        return {"success": True, "message": "Chart data added to context"}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": str(e)}

@app.get("/api/stock/price/{ticker}")
def get_price(ticker: str):
    """获取股票价格（带缓存，TTL=60秒）"""
    try:
        # 尝试从缓存获取
        orchestrator = getattr(agent, "orchestrator", None)
        if agent and orchestrator:
            cache_key = f"price:{ticker}"
            cached_data = orchestrator.cache.get(cache_key)
            if cached_data is not None:
                logger.info(f"[API] 从缓存获取价格: {ticker}")
                return {"ticker": ticker, "data": cached_data, "cached": True}

        # 缓存未命中，调用工具获取
        price_info = get_stock_price(ticker)

        # 存入缓存（TTL=60秒）
        orchestrator = getattr(agent, "orchestrator", None)
        if agent and orchestrator and price_info:
            orchestrator.cache.set(f"price:{ticker}", price_info, ttl=60)
            logger.info(f"[API] 价格已缓存: {ticker}")

        return {"ticker": ticker, "data": price_info}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/stock/news/{ticker}")
def get_news(ticker: str):
    try:
        news = get_company_news(ticker)
        return {"ticker": ticker, "data": news}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/financials/{ticker}")
def get_financials(ticker: str):
    """获取公司财务报表数据（完整数据，JSON格式）"""
    try:
        financials_data = get_financial_statements(ticker)
        return financials_data
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}

@app.get("/api/financials/{ticker}/summary")
def get_financials_summary(ticker: str):
    """获取公司财务报表摘要（文本格式，便于阅读）"""
    try:
        summary = get_financial_statements_summary(ticker)
        return {"ticker": ticker, "summary": summary}
    except Exception as e:
        return {"ticker": ticker, "error": str(e)}

@app.get("/api/stock/kline/{ticker}", response_model=KlineResponse)
def get_kline_data(ticker: str, period: str = "1y", interval: str = "1d"):
    """
    获取 K 线图数据
    使用缓存机制避免重复请求
    
    Args:
        ticker: 股票代码
        period: 时间周期 (1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max)
        interval: 数据间隔 (1d, 1wk, 1mo)
    """
    try:
        # 尝试从 Agent 的 orchestrator 缓存获取
        orchestrator = getattr(agent, "orchestrator", None)
        if agent and orchestrator:
            cache_key = f"kline:{ticker}:{period}:{interval}"
            cached_data = orchestrator.cache.get(cache_key)
            if cached_data is not None:
                logger.info(f"[API] 从缓存获取 K 线数据: {ticker} ({period}, {interval})")
                return {"ticker": ticker, "data": cached_data, "cached": True}
        
        # 如果缓存中没有，获取新数据
        kline_data = get_stock_historical_data(ticker, period=period, interval=interval)
        
        # 如果成功获取，存入缓存（缓存 1 小时）
        orchestrator = getattr(agent, "orchestrator", None)
        if "error" not in kline_data and agent and orchestrator:
            cache_key = f"kline:{ticker}:{period}:{interval}"
            orchestrator.cache.set(cache_key, kline_data, ttl=3600)  # 1小时缓存
            logger.info(f"[API] K 线数据已缓存: {ticker} ({period}, {interval})")
        
        # 确保返回格式符合前端期望：{ticker, data: {kline_data: [...] 或 error: "..."}}
        return {
            "ticker": ticker, 
            "data": kline_data,  # kline_data 已经是 {kline_data: [...]} 或 {error: "..."}
            "cached": False
        }
    except Exception as e:
        return {"ticker": ticker, "data": {"error": str(e)}, "cached": False}

@app.post("/api/subscribe")
async def subscribe_email(request: SubscriptionRequest):
    """
    订阅股票提醒

    请求体:
    {
        "email": "user@example.com",
        "ticker": "AAPL",
        "alert_types": ["price_change", "news"],  # 可选
        "price_threshold": 5.0  # 可选，价格变动阈值（百分比）
    }
    """
    try:
        from backend.services.subscription_service import get_subscription_service

        subscription_service = get_subscription_service()
        if not subscription_service.is_valid_email(request.email):
            raise HTTPException(status_code=400, detail="无效的邮箱地址")
        success = subscription_service.subscribe(
            email=request.email,
            ticker=request.ticker,
            alert_types=request.alert_types,
            price_threshold=request.price_threshold,
        )

        if success:
            return {
                "success": True,
                "message": f"已成功订阅 {request.ticker} 的提醒",
                "email": request.email,
                "ticker": request.ticker,
            }
        else:
            raise HTTPException(status_code=500, detail="订阅失败")

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/unsubscribe")
async def unsubscribe_email(request: UnsubscribeRequest):
    """
    取消订阅
    
    请求体:
    {
        "email": "user@example.com",
        "ticker": "AAPL"  # 可选，如果不提供则取消所有订阅
    }
    """
    try:
        from backend.services.subscription_service import get_subscription_service

        subscription_service = get_subscription_service()

        # email 在模型中必填，但仍做一次保护性校验，缺失时按 400 返回
        if not request.email:
            raise HTTPException(status_code=400, detail="email 是必需的")

        success = subscription_service.unsubscribe(
            email=request.email,
            ticker=request.ticker,
        )

        if success:
            return {
                "success": True,
                "message": "已成功取消订阅",
                "email": request.email,
                "ticker": request.ticker or "所有股票",
            }
        else:
            raise HTTPException(status_code=404, detail="未找到订阅记录")

    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/subscriptions", response_model=SubscriptionListResponse)
async def get_subscriptions(email: str = None):
    """
    获取订阅列表
    
    查询参数:
    - email: 用户邮箱（可选，如果不提供则返回所有订阅）
    """
    try:
        from backend.services.subscription_service import get_subscription_service
        
        subscription_service = get_subscription_service()
        subscriptions = subscription_service.get_subscriptions(email=email)
        
        return {
            "success": True,
            "subscriptions": subscriptions,
            "count": len(subscriptions)
        }
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/subscription/toggle", response_model=SubscriptionResponse)
async def toggle_subscription(request: ToggleSubscriptionRequest):
    """
    启用或禁用订阅

    请求体:
    {
        "email": "用户邮箱",
        "ticker": "股票代码",
        "enabled": true/false
    }
    """
    try:
        from backend.services.subscription_service import get_subscription_service

        subscription_service = get_subscription_service()
        success = subscription_service.toggle_subscription(
            email=request.email,
            ticker=request.ticker,
            enabled=request.enabled,
        )

        if success:
            return {
                "success": True,
                "message": f"订阅已{'启用' if request.enabled else '禁用'}",
                "email": request.email,
                "ticker": request.ticker,
            }
        else:
            raise HTTPException(status_code=404, detail="订阅未找到")
    except HTTPException:
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/config", response_model=ConfigResponse)
async def get_config():
    """
    获取用户配置（从 user_config.json 读取）
    """
    try:
        import json
        config_file = os.path.join(project_root, "user_config.json")

        if os.path.exists(config_file):
            with open(config_file, 'r', encoding='utf-8') as f:
                saved_config = json.load(f)
            return {"success": True, "config": saved_config}

        # 文件不存在时返回默认配置
        return {
            "success": True,
            "config": {
                "llm_provider": None,
                "llm_model": None,
                "llm_api_key": None,
                "llm_api_base": None,
                "layout_mode": "centered",
            }
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

@app.post("/api/config")
async def save_config(request: dict):
    """
    保存用户配置（存储到本地文件）
    """
    try:
        import json
        config_file = os.path.join(project_root, "user_config.json")
        
        # 保存配置到文件
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(request, f, indent=2, ensure_ascii=False)
        
        logger.info(f"[Config] 用户配置已保存到 {config_file}")
        
        return {"success": True, "message": "配置已保存"}
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": str(e)}

@app.post("/api/export/pdf")
async def export_pdf(request: dict):
    """
    导出对话记录和图表到 PDF
    
    请求体:
    {
        "messages": [
            {"role": "user", "content": "...", "timestamp": "..."},
            {"role": "assistant", "content": "...", "timestamp": "..."}
        ],
        "charts": [  # 可选
            {"ticker": "AAPL", "chart_type": "candlestick", "image_path": "..."}
        ],
        "title": "对话记录"  # 可选
    }
    """
    try:
        from backend.services.pdf_export import get_pdf_service
        
        pdf_service = get_pdf_service()
        if not pdf_service:
            raise HTTPException(status_code=503, detail="PDF 导出服务不可用（请安装 reportlab: pip install reportlab）")
        
        messages = request.get('messages', [])
        charts = request.get('charts', [])
        title = request.get('title', 'FinSight 对话记录')
        
        if not messages:
            raise HTTPException(status_code=400, detail="messages 不能为空")
        
        # 生成 PDF
        if charts:
            pdf_bytes = pdf_service.export_with_charts(messages, charts, title=title)
        else:
            pdf_bytes = pdf_service.export_conversation(messages, title=title)
        
        if pdf_bytes:
            from fastapi.responses import Response
            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename=finsight_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                }
            )
        else:
            raise HTTPException(status_code=500, detail="PDF 生成失败")
            
    except ImportError as e:
        raise HTTPException(status_code=503, detail=f"PDF 导出功能不可用: {str(e)}")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# 启动入口
if __name__ == "__main__":
    uvicorn.run("backend.api.main:app", host="0.0.0.0", port=8000, reload=True)

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, constr, field_validator
import uvicorn
import os
import sys
import traceback
from datetime import datetime, timezone
from typing import Any, Dict
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv
from contextlib import asynccontextmanager
from backend.api.streaming import stream_report_sse, stream_supervisor_sse
# 将项目根目录添加到 sys.path
# 这样可以确保 backend, config, langchain_agent 等模块能被找到
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Load env once for scheduler/SMTP configs, etc.
load_dotenv()

# 尝试导入核心工具
try:
    from backend.tools import get_stock_price, get_company_news, get_stock_historical_data, get_financial_statements, get_financial_statements_summary
    print("[Init] Core tools imported successfully.")
except ImportError as e:
    # 如果 backend.tools 失败，尝试从根目录 tools 导入（兼容旧结构）
    try:
        from tools import get_stock_price, get_company_news, get_stock_historical_data, get_financial_statements, get_financial_statements_summary
        print("[Init] Core tools imported from root successfully.")
    except ImportError as e2:
        print(f"❌ Error importing tools: {e2}")

# 导入图表检测器
try:
    from backend.api.chart_detector import ChartTypeDetector
    print("[Init] Chart detector imported successfully.")
except ImportError as e:
    print(f"❌ Error importing chart detector: {e}")
    ChartTypeDetector = None

# 导入 Agent
from backend.conversation.agent import create_agent as CreateReActAgent

# 导入 MemoryService
try:
    from backend.services.memory import MemoryService, UserProfile
    memory_service = MemoryService()
    print("[Init] MemoryService initialized successfully.")
except Exception as e:
    print(f"[Init] Error initializing MemoryService: {e}")
    memory_service = None

# Pydantic Models
class ChatRequest(BaseModel):
    # 至少 1 个字符，避免空查询直接进入主链路
    query: constr(min_length=1)  # type: ignore[valid-type]
    session_id: str = None

class AnalysisRequest(BaseModel):
    query: str
    user_id: str = "default_user"


class SubscriptionRequest(BaseModel):
    email: constr(min_length=3)  # type: ignore[valid-type]
    ticker: constr(min_length=1)  # type: ignore[valid-type]
    alert_types: list[str] | None = None
    price_threshold: float | None = None

    @field_validator("alert_types", mode="before")
    def default_alert_types(cls, v):
        return v or ["price_change", "news"]

    @field_validator("alert_types")
    def validate_alert_types(cls, v):
        allowed = {"price_change", "news", "report"}
        invalid = [x for x in v if x not in allowed]
        if invalid:
            raise ValueError(f"unsupported alert_types: {invalid}. allowed: {sorted(allowed)}")
        return v

    @field_validator("price_threshold")
    def validate_price_threshold(cls, v):
        if v is not None and v <= 0:
            raise ValueError("price_threshold must be positive")
        return v


class UnsubscribeRequest(BaseModel):
    email: constr(min_length=3)  # type: ignore[valid-type]
    ticker: constr(min_length=1) | None = None

# SubscribeRequest 已移除，改用 dict

# 初始化 Agent
try:
    # 尝试初始化，如果失败则打印详细堆栈
    agent = CreateReActAgent(
        use_llm=True,
        use_orchestrator=True,
        use_report_agent=True
    )
    print("[Init] ReAct Agent initialized successfully.")
except Exception as e:
    print(f"[Init] Error initializing ReAct Agent: {e}")
    traceback.print_exc()
    agent = None

_schedulers = []

def _env_bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).lower() in ("true", "1", "yes", "on")

@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan handler to start/stop price_change scheduler.
    """
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
        print("[Scheduler] PRICE_ALERT_SCHEDULER_ENABLED is false; skip start.")

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
        print("[Scheduler] NEWS_ALERT_SCHEDULER_ENABLED is false; skip start.")

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
        print("[Scheduler] HEALTH_PROBE_ENABLED is false; skip start.")

    try:
        yield
    finally:
        try:
            for sched in _schedulers:
                sched.shutdown(wait=False)
            if _schedulers:
                print("[Scheduler] all schedulers stopped.")
        except Exception as e:
            print(f"[Scheduler] shutdown error: {e}")

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

@app.get("/")
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
    轻量健康检查端点，便于监控/探活。
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }


@app.get("/diagnostics/langgraph")
def diagnostics_langgraph():
    """
    LangGraph 报告 Agent 的自检与描述。
    返回 DAG 概览、模型/提供商及自检状态，不触发外部 LLM 调用。
    """
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    try:
        info = agent.describe_report_agent() if hasattr(agent, "describe_report_agent") else {
            "available": False,
            "error": "describe_report_agent_not_supported",
        }
        return {
            "status": "ok" if info.get("available") else "degraded",
            "data": info,
            "timestamp": datetime.utcnow().isoformat() + "Z",
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"diagnostics failed: {exc}")


@app.get("/diagnostics/orchestrator")
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

@app.post("/chat")
async def chat_endpoint(request: ChatRequest):
    """
    对话接口
    支持图表数据摘要自动加入上下文
    """
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    
    try:
        # 检查是否请求思考过程
        include_thinking = request.query.startswith("[THINKING]") if hasattr(request, 'query') else False
        if include_thinking:
            query = request.query.replace("[THINKING]", "").strip()
        else:
            query = request.query
        
        # 调用 Agent 的 chat 方法（捕获思考过程）
        if hasattr(agent, "chat_async"):
            result = await agent.chat_async(query, capture_thinking=True)
        else:
            result = agent.chat(query, capture_thinking=True)
        
        # 构造符合前端预期的响应格式
        return {
            "success": result.get('success', True),
            "response": result.get('response', '无响应'),
            "intent": result.get('intent', 'chat'),
            "current_focus": result.get('current_focus'),
            "response_time_ms": result.get('response_time_ms', 0),
            "session_id": request.session_id or "new_session",
            "thinking": result.get('thinking', [])  # 思考过程
        }
    except HTTPException:
        # 已经构造好的业务错误（如 400/404），直接透传
        raise
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat/stream")
async def chat_stream_endpoint(request: ChatRequest):
    """
    流式对话接口 - 根据意图路由到不同处理器
    只有 REPORT 意图才使用 LangGraph Agent 流式输出
    CHAT 等简单意图使用快速响应
    """
    if not agent:
        raise HTTPException(status_code=500, detail="Agent not initialized")

    import json

    # 1. 先进行指代消解 + 意图路由
    from backend.conversation.router import Intent
    resolved_query = agent.context.resolve_reference(request.query)
    intent, metadata, handler = agent.router.route(resolved_query, agent.context)

    # 2. 根据意图决定处理方式
    if intent == Intent.REPORT:
        report_agent = getattr(agent, "report_agent", None)
        supervisor = getattr(agent, "supervisor", None)
        ticker = metadata["tickers"][0] if metadata.get("tickers") else None

        report_builder = None
        if ticker and getattr(agent, "report_handler", None) and hasattr(agent.report_handler, "_generate_simple_report_ir"):
            def _build_report(content: str):
                return agent.report_handler._generate_simple_report_ir(ticker, content)
            report_builder = _build_report

        if supervisor and ticker and hasattr(supervisor, "analyze_stream"):
            async def generate_report():
                async for chunk in stream_supervisor_sse(supervisor, resolved_query, ticker, report_builder):
                    yield chunk
        elif report_agent and hasattr(report_agent, "analyze_stream"):
            async def generate_report():
                async for chunk in stream_report_sse(report_agent, resolved_query, report_builder):
                    yield chunk
        else:
            # Stream fallback using the non-streaming report path.
            async def generate_report():
                try:
                    print(f"[Stream REPORT] using sync agent.chat()")
                    result = agent.chat(resolved_query, capture_thinking=True)
                    response_text = result.get('response', '')
                    report_data = result.get('report')

                    print(f"[Stream REPORT] agent.chat report present: {report_data is not None}")
                    if report_data:
                        print(f"[Stream REPORT] report keys: {list(report_data.keys())}")

                    import re
                    sentences = re.split(r'([???\n])', response_text)
                    buffer = ""
                    for i, part in enumerate(sentences):
                        buffer += part
                        if part in ['?', '?', '?', '\n'] or i == len(sentences) - 1:
                            if buffer.strip():
                                yield f"data: {json.dumps({'type': 'token', 'content': buffer}, ensure_ascii=False)}\n\n"
                                buffer = ""

                    done_data = {'type': 'done'}
                    if report_data:
                        done_data['report'] = report_data
                        print(f"[Stream REPORT] done event includes report")
                    yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"

                except Exception as e:
                    import traceback
                    traceback.print_exc()
                    yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            generate_report(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
        )

    else:
        # 其他意图：优先走真实 token 流式输出
        async def generate_chat():
            try:
                agent.stats['total_queries'] += 1
                agent.stats['intents'][intent.value] = agent.stats['intents'].get(intent.value, 0) + 1

                response_text = ""
                result: Dict[str, Any] = {}

                if intent == Intent.CHAT and hasattr(agent.chat_handler, "stream_with_llm"):
                    result_container: Dict[str, Any] = {}
                    async for token in agent.chat_handler.stream_with_llm(
                        resolved_query, metadata, agent.context, result_container
                    ):
                        if token:
                            response_text += token
                            yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"
                    result = result_container or {'success': True, 'response': response_text, 'intent': 'chat'}

                elif intent == Intent.FOLLOWUP and hasattr(agent.followup_handler, "stream_with_llm"):
                    result_container = {}
                    async for token in agent.followup_handler.stream_with_llm(
                        resolved_query, metadata, agent.context, result_container
                    ):
                        if token:
                            response_text += token
                            yield f"data: {json.dumps({'type': 'token', 'content': token}, ensure_ascii=False)}\n\n"
                    result = result_container or {'success': True, 'response': response_text, 'intent': 'followup'}

                elif handler:
                    result = handler(resolved_query, metadata)
                    response_text = result.get('response', '')
                    if response_text:
                        yield f"data: {json.dumps({'type': 'token', 'content': response_text}, ensure_ascii=False)}\n\n"
                else:
                    result = agent._default_handler(resolved_query, metadata)
                    response_text = result.get('response', '')
                    if response_text:
                        yield f"data: {json.dumps({'type': 'token', 'content': response_text}, ensure_ascii=False)}\n\n"

                if not result.get('response'):
                    result['response'] = response_text

                if intent in [Intent.CHAT, Intent.REPORT, Intent.FOLLOWUP]:
                    before = result.get('response', '')
                    result = agent._add_chart_marker(result, request.query, metadata, resolved_query)
                    after = result.get('response', '')
                    if after.startswith(before) and after != before:
                        suffix = after[len(before):]
                        if suffix.strip():
                            yield f"data: {json.dumps({'type': 'token', 'content': suffix}, ensure_ascii=False)}\n\n"

                agent.context.add_turn(
                    query=request.query,
                    intent=intent.value,
                    response=result.get('response', ''),
                    metadata=metadata
                )

                done_data = {'type': 'done'}
                if result.get('report'):
                    done_data['report'] = result['report']
                yield f"data: {json.dumps(done_data, ensure_ascii=False)}\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'type': 'error', 'message': str(e)}, ensure_ascii=False)}\n\n"

        return StreamingResponse(
            generate_chat(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"}
        )

@app.post("/api/chart/detect")
async def detect_chart_type(request: dict):
    """
    智能检测用户查询需要的图表类型
    """
    if not ChartTypeDetector:
        return {"success": False, "error": "Chart detector not available"}
    
    try:
        query = request.get('query', '')
        ticker = request.get('ticker')
        
        result = ChartTypeDetector.detect_chart_type(query, ticker)
        should_generate = ChartTypeDetector.should_generate_chart(query)
        
        return {
            "success": True,
            "should_generate": should_generate,
            "chart_type": result['chart_type'],
            "data_dimension": result['data_dimension'],
            "confidence": result['confidence'],
            "reason": result['reason']
        }
    except Exception as e:
        traceback.print_exc()
        return {"success": False, "error": str(e)}

@app.post("/api/chat/add-chart-data")
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
    try:
        price_info = get_stock_price(ticker)
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

@app.get("/api/stock/kline/{ticker}")
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
        if agent and agent.orchestrator:
            cache_key = f"kline:{ticker}:{period}:{interval}"
            cached_data = agent.orchestrator.cache.get(cache_key)
            if cached_data is not None:
                print(f"[API] 从缓存获取 K 线数据: {ticker} ({period}, {interval})")
                return {"ticker": ticker, "data": cached_data, "cached": True}
        
        # 如果缓存中没有，获取新数据
        kline_data = get_stock_historical_data(ticker, period=period, interval=interval)
        
        # 如果成功获取，存入缓存（缓存 1 小时）
        if "error" not in kline_data and agent and agent.orchestrator:
            cache_key = f"kline:{ticker}:{period}:{interval}"
            agent.orchestrator.cache.set(cache_key, kline_data, ttl=3600)  # 1小时缓存
            print(f"[API] K 线数据已缓存: {ticker} ({period}, {interval})")
        
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

@app.get("/api/subscriptions")
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

@app.get("/api/config")
async def get_config():
    """
    获取用户配置（从本地存储或默认配置）
    """
    try:
        # 这里可以从文件或数据库读取用户配置
        # 目前返回默认配置
        return {
            "success": True,
            "config": {
                "llm_provider": None,
                "llm_model": None,
                "llm_api_key": None,
                "llm_api_base": None,
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
        
        print(f"[Config] 用户配置已保存到 {config_file}")
        
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

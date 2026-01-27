"""
FinSight API - 主应用入口

基于 Clean/Hexagonal Architecture 的金融分析 API 服务。

特性：
- 智能意图识别（LLM + 规则兜底）
- 多种分析模式（Summary/Deep）
- 结构化响应
- 完整的错误处理
- 可观测性支持
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
from pathlib import Path
import time
import logging

from finsight.api.routes import analysis_router, health_router, metrics_router
from finsight.api.dependencies import get_settings, get_service_container
from finsight.api.schemas import ErrorResponse
from finsight.infrastructure.security import SecurityHeadersMiddleware


# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时初始化
    logger.info("FinSight API 正在启动...")

    # 预热服务容器
    try:
        container = get_service_container()
        logger.info("服务容器初始化完成")
    except Exception as e:
        logger.error(f"服务容器初始化失败: {e}")

    yield

    # 关闭时清理
    logger.info("FinSight API 正在关闭...")


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例"""
    settings = get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        description="""
# FinSight API

智能金融分析助手 API，提供股票分析、市场情绪、经济日历等功能。

## 功能特性

- 🔍 **智能意图识别**：自动理解用户查询意图
- 📊 **股票分析**：价格、新闻、深度分析
- 📈 **市场情绪**：CNN Fear & Greed 指数
- 📅 **经济日历**：重要经济事件提醒
- ⚖️ **资产对比**：多资产收益对比

## 响应模式

- `summary`：简要分析（300-500字），适合快速了解
- `deep`：深度报告（800+字），适合投资决策

## 快速开始

```python
import requests

response = requests.post(
    "http://localhost:8000/api/v1/analyze",
    json={"query": "分析苹果股票", "mode": "deep"}
)
print(response.json()["report"])
```
        """,
        version=settings.APP_VERSION,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        lifespan=lifespan,
    )

    # CORS 中间件
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 安全头中间件
    app.add_middleware(SecurityHeadersMiddleware)

    # 请求日志中间件
    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        start_time = time.time()

        # 生成请求 ID
        request_id = request.headers.get("X-Request-ID", str(time.time()))

        # 记录请求
        logger.info(f"[{request_id}] {request.method} {request.url.path}")

        try:
            response = await call_next(request)

            # 记录响应
            duration = (time.time() - start_time) * 1000
            logger.info(
                f"[{request_id}] 完成 {response.status_code} - {duration:.2f}ms"
            )

            # 添加响应头
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Response-Time"] = f"{duration:.2f}ms"

            return response

        except Exception as e:
            duration = (time.time() - start_time) * 1000
            logger.error(
                f"[{request_id}] 错误 - {duration:.2f}ms - {str(e)}"
            )
            raise

    # 全局异常处理
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.error(f"未处理的异常: {exc}", exc_info=True)
        return JSONResponse(
            status_code=500,
            content=ErrorResponse(
                success=False,
                error_code="internal_error",
                error_message="服务器内部错误，请稍后重试",
            ).model_dump(),
        )

    # 注册路由
    app.include_router(health_router)
    app.include_router(analysis_router)
    app.include_router(metrics_router)

    # 挂载静态文件
    web_dir = Path(__file__).parent.parent / "web"
    static_dir = web_dir / "static"
    template_file = web_dir / "templates" / "index.html"

    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
        logger.info(f"静态文件目录已挂载: {static_dir}")

    # 前端页面路由
    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def serve_frontend():
        """提供前端页面"""
        if template_file.exists():
            return HTMLResponse(content=template_file.read_text(encoding="utf-8"))
        return HTMLResponse(
            content="<h1>FinSight</h1><p>前端页面未找到，请访问 <a href='/docs'>/docs</a> 使用 API</p>"
        )

    return app


# 创建应用实例
app = create_app()


if __name__ == "__main__":
    import uvicorn
    settings = get_settings()
    uvicorn.run(
        "finsight.api.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
    )

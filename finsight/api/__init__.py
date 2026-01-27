"""
API 层 - FastAPI 路由定义

提供 RESTful API 接口，作为系统的统一入口。

包含：
- /api/v1/analyze: 智能分析入口
- /api/v1/stock: 股票相关 API
- /api/v1/market: 市场数据 API
- /health: 健康检查
- /ready, /live: Kubernetes 探针
"""

from finsight.api.main import app, create_app
from finsight.api.schemas import (
    AnalyzeRequest,
    CompareRequest,
    AnalysisResponse,
    HealthResponse,
    ErrorResponse,
)
from finsight.api.dependencies import (
    get_orchestrator,
    get_report_writer,
    get_settings,
    ServiceContainer,
)

__all__ = [
    # 应用
    "app",
    "create_app",
    # 请求模型
    "AnalyzeRequest",
    "CompareRequest",
    # 响应模型
    "AnalysisResponse",
    "HealthResponse",
    "ErrorResponse",
    # 依赖
    "get_orchestrator",
    "get_report_writer",
    "get_settings",
    "ServiceContainer",
]

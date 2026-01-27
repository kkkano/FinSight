"""
路由包初始化
"""

from finsight.api.routes.analysis import router as analysis_router
from finsight.api.routes.health import router as health_router
from finsight.api.routes.metrics import router as metrics_router

__all__ = [
    "analysis_router",
    "health_router",
    "metrics_router",
]

"""
健康检查路由 - 系统状态监控 API
"""

from fastapi import APIRouter, Depends
from datetime import datetime

from finsight.api.schemas import HealthResponse
from finsight.api.dependencies import get_time_service, get_settings, Settings


router = APIRouter(tags=["Health"])


@router.get(
    "/",
    summary="API 根节点",
    description="返回欢迎信息和 API 基本信息"
)
async def root(settings: Settings = Depends(get_settings)):
    """API 根节点"""
    return {
        "message": f"Welcome to {settings.APP_NAME}",
        "version": settings.APP_VERSION,
        "docs": "/docs",
        "redoc": "/redoc",
    }


@router.get(
    "/health",
    response_model=HealthResponse,
    summary="健康检查",
    description="检查服务及其依赖组件的健康状态"
)
async def health_check(
    time_service=Depends(get_time_service),
    settings: Settings = Depends(get_settings),
) -> HealthResponse:
    """健康检查"""
    components = {}

    # 检查时间服务
    try:
        time_service.get_current_datetime()
        components["time_service"] = "healthy"
    except Exception:
        components["time_service"] = "unhealthy"

    # 总体状态
    overall_status = "healthy" if all(
        v == "healthy" for v in components.values()
    ) else "degraded"

    return HealthResponse(
        status=overall_status,
        timestamp=datetime.now(),
        version=settings.APP_VERSION,
        components=components,
    )


@router.get(
    "/ready",
    summary="就绪检查",
    description="检查服务是否准备好接收请求（用于 Kubernetes 就绪探针）"
)
async def readiness_check():
    """就绪检查"""
    return {"ready": True}


@router.get(
    "/live",
    summary="存活检查",
    description="检查服务是否存活（用于 Kubernetes 存活探针）"
)
async def liveness_check():
    """存活检查"""
    return {"alive": True}

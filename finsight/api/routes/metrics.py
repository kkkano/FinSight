"""
监控指标路由 - 暴露系统性能和成本数据

提供：
- 系统指标（请求、延迟、错误率）
- 缓存统计
- 限流统计
- 成本统计
"""

from typing import Dict, Any
from fastapi import APIRouter, Depends

from finsight.infrastructure import (
    get_metrics_registry,
    get_cache_manager,
    get_rate_limiter_manager,
    get_cost_tracker_manager,
)

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/system", summary="获取系统指标")
async def get_system_metrics() -> Dict[str, Any]:
    """
    获取系统性能指标

    返回请求计数、延迟统计、错误率等核心指标。
    """
    registry = get_metrics_registry()
    return {
        "metrics": registry.get_all_metrics(),
    }


@router.get("/cache", summary="获取缓存统计")
async def get_cache_stats() -> Dict[str, Any]:
    """
    获取缓存命中率和使用统计

    返回各缓存的命中率、大小、驱逐次数等。
    """
    manager = get_cache_manager()
    return {
        "caches": manager.get_all_stats(),
    }


@router.get("/rate-limits", summary="获取限流统计")
async def get_rate_limit_stats() -> Dict[str, Any]:
    """
    获取限流统计

    返回各服务的限流状态、请求数、拒绝率等。
    """
    manager = get_rate_limiter_manager()
    return {
        "limiters": manager.get_all_stats(),
    }


@router.get("/costs", summary="获取成本统计")
async def get_cost_stats() -> Dict[str, Any]:
    """
    获取API调用成本统计

    返回各服务的调用次数、成本、预算使用情况等。
    """
    manager = get_cost_tracker_manager()
    return {
        "summary": manager.get_total_cost(),
    }


@router.get("/costs/report", summary="获取完整成本报告")
async def get_cost_report() -> Dict[str, Any]:
    """
    获取完整的成本使用报告

    包含所有服务的详细成本数据和配置信息。
    """
    manager = get_cost_tracker_manager()
    return manager.generate_usage_report()


@router.get("/all", summary="获取所有指标")
async def get_all_metrics() -> Dict[str, Any]:
    """
    获取所有监控指标的汇总

    一次性返回系统指标、缓存、限流、成本等全部数据。
    """
    metrics_registry = get_metrics_registry()
    cache_manager = get_cache_manager()
    rate_limit_manager = get_rate_limiter_manager()
    cost_manager = get_cost_tracker_manager()

    return {
        "system": metrics_registry.get_all_metrics(),
        "cache": cache_manager.get_all_stats(),
        "rate_limits": rate_limit_manager.get_all_stats(),
        "costs": cost_manager.get_total_cost(),
    }


@router.post("/cache/cleanup", summary="清理过期缓存")
async def cleanup_expired_cache() -> Dict[str, Any]:
    """
    清理所有缓存中的过期条目

    返回各缓存清理的条目数。
    """
    manager = get_cache_manager()
    cleaned = manager.cleanup_all_expired()
    return {
        "cleaned": cleaned,
        "message": "过期缓存已清理",
    }


@router.post("/costs/cleanup", summary="清理旧成本记录")
async def cleanup_old_cost_records(days: int = 30) -> Dict[str, Any]:
    """
    清理超过指定天数的成本记录

    Args:
        days: 保留天数（默认30天）

    Returns:
        各追踪器清理的记录数
    """
    manager = get_cost_tracker_manager()
    cleaned = manager.cleanup_all_old_records(days)
    return {
        "cleaned": cleaned,
        "message": f"已清理超过 {days} 天的记录",
    }

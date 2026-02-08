"""
Dashboard 错误码定义

定义 Dashboard 模块的错误码常量和异常工厂函数。
"""
from fastapi import HTTPException


class DashboardError:
    """
    错误码常量

    错误码命名规范：
    - 4xxx: 客户端错误
    - 5xxx: 服务端错误
    """
    SYMBOL_NOT_FOUND = 4001
    INVALID_ASSET_TYPE = 4002
    INVALID_TIME_RANGE = 4003
    WATCHLIST_FULL = 4004
    DATA_FETCH_FAILED = 5001
    CACHE_ERROR = 5002
    RATE_LIMITED = 4291
    INTERNAL_ERROR = 5000


def symbol_not_found(symbol: str) -> HTTPException:
    """
    Symbol 未找到异常

    当解析的 symbol 不存在或无法识别时抛出。
    """
    return HTTPException(
        status_code=404,
        detail={
            "code": DashboardError.SYMBOL_NOT_FOUND,
            "message": f"Symbol '{symbol}' not found",
            "details": {"symbol": symbol},
        },
    )


def invalid_asset_type(asset_type: str) -> HTTPException:
    """
    无效资产类型异常

    当传入的资产类型不在枚举范围内时抛出。
    """
    return HTTPException(
        status_code=400,
        detail={
            "code": DashboardError.INVALID_ASSET_TYPE,
            "message": f"Invalid asset type '{asset_type}'",
            "details": {"asset_type": asset_type},
        },
    )


def invalid_time_range(time_range: str) -> HTTPException:
    """
    无效时间范围异常

    当传入的时间范围不在枚举范围内时抛出。
    """
    return HTTPException(
        status_code=400,
        detail={
            "code": DashboardError.INVALID_TIME_RANGE,
            "message": f"Invalid time range '{time_range}'",
            "details": {"time_range": time_range},
        },
    )


def data_fetch_failed(reason: str) -> HTTPException:
    """
    数据获取失败异常

    当从外部 API 获取数据失败时抛出。
    """
    return HTTPException(
        status_code=502,
        detail={
            "code": DashboardError.DATA_FETCH_FAILED,
            "message": f"Failed to fetch data: {reason}",
            "details": {"reason": reason},
        },
    )


def rate_limited(retry_after: int = 60) -> HTTPException:
    """
    速率限制异常

    当请求频率超过限制时抛出。
    """
    return HTTPException(
        status_code=429,
        detail={
            "code": DashboardError.RATE_LIMITED,
            "message": "Rate limit exceeded. Please try again later.",
            "details": {"retry_after": retry_after},
        },
        headers={"Retry-After": str(retry_after)},
    )


def internal_error(message: str = "Internal server error") -> HTTPException:
    """
    内部错误异常

    当发生未预期的服务端错误时抛出。
    """
    return HTTPException(
        status_code=500,
        detail={
            "code": DashboardError.INTERNAL_ERROR,
            "message": message,
            "details": {},
        },
    )

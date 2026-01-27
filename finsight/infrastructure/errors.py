"""
错误处理 - 统一错误定义和处理

提供：
- 业务异常类层次
- 错误码定义
- 错误处理工具
- 重试机制
"""

from typing import Optional, Dict, Any, Callable, TypeVar
from functools import wraps
import time
import logging

from finsight.domain.models import ErrorCode


logger = logging.getLogger(__name__)


# ==================== 异常类层次 ====================

class FinSightError(Exception):
    """FinSight 基础异常"""

    def __init__(
        self,
        message: str,
        error_code: ErrorCode = ErrorCode.INTERNAL_ERROR,
        details: Optional[Dict[str, Any]] = None
    ):
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "error_code": self.error_code.value,
            "message": self.message,
            "details": self.details,
        }


class ValidationError(FinSightError):
    """验证错误"""

    def __init__(self, message: str, field: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.INVALID_INPUT,
            details={"field": field} if field else {}
        )


class ResourceNotFoundError(FinSightError):
    """资源未找到错误"""

    def __init__(self, resource_type: str, resource_id: str):
        super().__init__(
            message=f"{resource_type} '{resource_id}' 未找到",
            error_code=ErrorCode.TICKER_NOT_FOUND,
            details={"resource_type": resource_type, "resource_id": resource_id}
        )


class DataUnavailableError(FinSightError):
    """数据不可用错误"""

    def __init__(self, source: str, reason: Optional[str] = None):
        message = f"数据源 '{source}' 不可用"
        if reason:
            message += f": {reason}"
        super().__init__(
            message=message,
            error_code=ErrorCode.DATA_UNAVAILABLE,
            details={"source": source, "reason": reason}
        )


class RateLimitError(FinSightError):
    """频率限制错误"""

    def __init__(self, service: str, retry_after: Optional[int] = None):
        message = f"服务 '{service}' 请求频率超限"
        if retry_after:
            message += f"，请在 {retry_after} 秒后重试"
        super().__init__(
            message=message,
            error_code=ErrorCode.RATE_LIMITED,
            details={"service": service, "retry_after": retry_after}
        )


class LLMError(FinSightError):
    """LLM 服务错误"""

    def __init__(self, message: str, provider: Optional[str] = None):
        super().__init__(
            message=message,
            error_code=ErrorCode.LLM_ERROR,
            details={"provider": provider}
        )


class TimeoutError(FinSightError):
    """超时错误"""

    def __init__(self, operation: str, timeout_seconds: float):
        super().__init__(
            message=f"操作 '{operation}' 超时（{timeout_seconds}秒）",
            error_code=ErrorCode.TIMEOUT,
            details={"operation": operation, "timeout": timeout_seconds}
        )


# ==================== 重试机制 ====================

T = TypeVar('T')


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None
):
    """
    重试装饰器

    Args:
        max_attempts: 最大重试次数
        delay: 初始延迟（秒）
        backoff: 延迟增长因子
        exceptions: 需要重试的异常类型
        on_retry: 重试时的回调函数
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            current_delay = delay
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        if on_retry:
                            on_retry(e, attempt + 1)
                        else:
                            logger.warning(
                                f"{func.__name__} 第 {attempt + 1} 次尝试失败: {e}，"
                                f"{current_delay:.1f}秒后重试"
                            )
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"{func.__name__} 在 {max_attempts} 次尝试后仍然失败"
                        )

            raise last_exception

        return wrapper
    return decorator


def async_retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,),
    on_retry: Optional[Callable[[Exception, int], None]] = None
):
    """异步重试装饰器"""
    import asyncio

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(max_attempts):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_attempts - 1:
                        if on_retry:
                            on_retry(e, attempt + 1)
                        else:
                            logger.warning(
                                f"{func.__name__} 第 {attempt + 1} 次尝试失败: {e}，"
                                f"{current_delay:.1f}秒后重试"
                            )
                        await asyncio.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(
                            f"{func.__name__} 在 {max_attempts} 次尝试后仍然失败"
                        )

            raise last_exception

        return wrapper
    return decorator


# ==================== 错误处理工具 ====================

class ErrorHandler:
    """错误处理器"""

    @staticmethod
    def handle_exception(
        e: Exception,
        context: Optional[str] = None
    ) -> FinSightError:
        """
        将异常转换为 FinSightError

        Args:
            e: 原始异常
            context: 上下文信息

        Returns:
            FinSightError: 标准化的错误
        """
        # 已经是 FinSightError
        if isinstance(e, FinSightError):
            return e

        # 根据异常类型转换
        error_message = str(e)
        if context:
            error_message = f"[{context}] {error_message}"

        # 常见异常映射
        if "timeout" in str(type(e).__name__).lower():
            return TimeoutError(context or "unknown", 30)

        if "connection" in str(type(e).__name__).lower():
            return DataUnavailableError("network", str(e))

        if "rate" in error_message.lower() or "limit" in error_message.lower():
            return RateLimitError("unknown")

        # 默认转换为内部错误
        return FinSightError(
            message=error_message,
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"original_type": type(e).__name__}
        )

    @staticmethod
    def safe_execute(
        func: Callable[..., T],
        *args,
        default: Optional[T] = None,
        context: Optional[str] = None,
        **kwargs
    ) -> T:
        """
        安全执行函数

        Args:
            func: 要执行的函数
            default: 失败时的默认值
            context: 上下文信息
            *args, **kwargs: 函数参数

        Returns:
            函数返回值或默认值
        """
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error = ErrorHandler.handle_exception(e, context)
            logger.error(f"安全执行失败: {error.message}")
            return default


def error_boundary(
    default: Any = None,
    reraise: bool = False,
    context: Optional[str] = None
):
    """
    错误边界装饰器

    Args:
        default: 失败时返回的默认值
        reraise: 是否重新抛出异常
        context: 上下文信息
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                error = ErrorHandler.handle_exception(e, context or func.__name__)
                logger.error(f"错误边界捕获: {error.message}")
                if reraise:
                    raise error
                return default
        return wrapper
    return decorator

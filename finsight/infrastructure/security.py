"""
安全中间件 - 基本安全防护

提供：
- 请求验证
- 安全头设置
- 基本输入清理
"""

from typing import Callable, Optional
from fastapi import Request, Response, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
import re
import html
from functools import wraps


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """
    安全头中间件

    添加基本的安全响应头。
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        response = await call_next(request)

        # 基本安全头
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        # 缓存控制（API响应不缓存）
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate"
            response.headers["Pragma"] = "no-cache"

        return response


class InputSanitizer:
    """
    输入清理器

    提供基本的输入验证和清理功能。
    """

    # 危险字符模式
    SQL_INJECTION_PATTERN = re.compile(
        r"(\b(SELECT|INSERT|UPDATE|DELETE|DROP|UNION|ALTER|CREATE)\b)",
        re.IGNORECASE
    )

    # XSS 模式
    XSS_PATTERN = re.compile(
        r"(<script|javascript:|on\w+=)",
        re.IGNORECASE
    )

    @classmethod
    def sanitize_string(cls, value: str, max_length: int = 10000) -> str:
        """
        清理字符串输入

        Args:
            value: 输入字符串
            max_length: 最大长度

        Returns:
            清理后的字符串
        """
        if not value:
            return value

        # 截断过长输入
        value = value[:max_length]

        # HTML 转义
        value = html.escape(value)

        return value

    @classmethod
    def is_safe_query(cls, query: str) -> bool:
        """
        检查查询是否安全

        Args:
            query: 用户查询

        Returns:
            是否安全
        """
        if not query:
            return True

        # 检查 SQL 注入模式
        if cls.SQL_INJECTION_PATTERN.search(query):
            return False

        # 检查 XSS 模式
        if cls.XSS_PATTERN.search(query):
            return False

        return True

    @classmethod
    def sanitize_ticker(cls, ticker: str) -> Optional[str]:
        """
        清理股票代码

        Args:
            ticker: 股票代码

        Returns:
            清理后的代码或None（无效）
        """
        if not ticker:
            return None

        # 转大写并移除空白
        ticker = ticker.upper().strip()

        # 验证格式（字母数字，1-10字符）
        if not re.match(r'^[A-Z0-9]{1,10}$', ticker):
            return None

        return ticker


class RequestValidator:
    """
    请求验证器

    验证请求的基本合法性。
    """

    # 允许的内容类型
    ALLOWED_CONTENT_TYPES = [
        "application/json",
        "application/x-www-form-urlencoded",
    ]

    # 最大请求体大小（字节）
    MAX_CONTENT_LENGTH = 1024 * 1024  # 1MB

    @classmethod
    def validate_content_type(cls, content_type: Optional[str]) -> bool:
        """验证内容类型"""
        if not content_type:
            return True  # GET 请求可能没有

        for allowed in cls.ALLOWED_CONTENT_TYPES:
            if content_type.startswith(allowed):
                return True

        return False

    @classmethod
    def validate_content_length(cls, content_length: Optional[int]) -> bool:
        """验证内容长度"""
        if content_length is None:
            return True

        return content_length <= cls.MAX_CONTENT_LENGTH


def require_safe_input(func: Callable) -> Callable:
    """
    安全输入装饰器

    验证函数参数中的 query 是否安全。
    """
    @wraps(func)
    async def wrapper(*args, **kwargs):
        query = kwargs.get("query") or (args[0] if args else None)

        if query and isinstance(query, str):
            if not InputSanitizer.is_safe_query(query):
                raise HTTPException(
                    status_code=400,
                    detail="输入包含不安全的内容"
                )

        return await func(*args, **kwargs)

    return wrapper


# 安全配置
class SecurityConfig:
    """安全配置"""

    # 是否启用安全头
    ENABLE_SECURITY_HEADERS: bool = True

    # 是否启用输入验证
    ENABLE_INPUT_VALIDATION: bool = True

    # 请求体最大大小
    MAX_REQUEST_SIZE: int = 1024 * 1024  # 1MB

    # 允许的来源（CORS）
    ALLOWED_ORIGINS: list = ["*"]

    # API 密钥（可选，生产环境配置）
    API_KEY_HEADER: str = "X-API-Key"
    API_KEYS: list = []  # 留空表示不启用

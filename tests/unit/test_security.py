"""
安全模块单元测试

测试安全中间件、输入验证、请求验证等功能。
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock
from fastapi import Request, HTTPException
from fastapi.responses import Response

from finsight.infrastructure.security import (
    SecurityHeadersMiddleware,
    InputSanitizer,
    RequestValidator,
    SecurityConfig,
    require_safe_input,
)


# ==================== InputSanitizer 测试 ====================

class TestInputSanitizer:
    """输入清理器测试"""

    def test_sanitize_string_basic(self):
        """测试基本字符串清理"""
        # 普通文本不变
        result = InputSanitizer.sanitize_string("Hello World")
        assert result == "Hello World"

    def test_sanitize_string_html_escape(self):
        """测试 HTML 转义"""
        result = InputSanitizer.sanitize_string("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_sanitize_string_max_length(self):
        """测试最大长度限制"""
        long_string = "a" * 20000
        result = InputSanitizer.sanitize_string(long_string, max_length=100)
        assert len(result) == 100

    def test_sanitize_string_empty(self):
        """测试空字符串"""
        assert InputSanitizer.sanitize_string("") == ""
        assert InputSanitizer.sanitize_string(None) is None

    def test_is_safe_query_normal(self):
        """测试正常查询"""
        assert InputSanitizer.is_safe_query("分析苹果股票") is True
        assert InputSanitizer.is_safe_query("AAPL price analysis") is True
        assert InputSanitizer.is_safe_query("") is True
        assert InputSanitizer.is_safe_query(None) is True

    def test_is_safe_query_sql_injection(self):
        """测试 SQL 注入检测"""
        # SQL 注入模式
        assert InputSanitizer.is_safe_query("'; DROP TABLE users; --") is False
        assert InputSanitizer.is_safe_query("SELECT * FROM stocks") is False
        assert InputSanitizer.is_safe_query("INSERT INTO table") is False
        assert InputSanitizer.is_safe_query("DELETE FROM users") is False
        assert InputSanitizer.is_safe_query("UPDATE users SET") is False

    def test_is_safe_query_xss(self):
        """测试 XSS 检测"""
        # XSS 模式
        assert InputSanitizer.is_safe_query("<script>alert('xss')</script>") is False
        assert InputSanitizer.is_safe_query("javascript:alert(1)") is False
        assert InputSanitizer.is_safe_query("onclick=alert(1)") is False

    def test_sanitize_ticker_valid(self):
        """测试有效股票代码"""
        assert InputSanitizer.sanitize_ticker("AAPL") == "AAPL"
        assert InputSanitizer.sanitize_ticker("aapl") == "AAPL"
        assert InputSanitizer.sanitize_ticker("  MSFT  ") == "MSFT"
        assert InputSanitizer.sanitize_ticker("BRK.B") is None  # 不包含点号
        assert InputSanitizer.sanitize_ticker("600519") == "600519"

    def test_sanitize_ticker_invalid(self):
        """测试无效股票代码"""
        assert InputSanitizer.sanitize_ticker("") is None
        assert InputSanitizer.sanitize_ticker(None) is None
        assert InputSanitizer.sanitize_ticker("A" * 20) is None  # 太长
        assert InputSanitizer.sanitize_ticker("AAPL!@#") is None  # 特殊字符


# ==================== RequestValidator 测试 ====================

class TestRequestValidator:
    """请求验证器测试"""

    def test_validate_content_type_json(self):
        """测试 JSON 内容类型"""
        assert RequestValidator.validate_content_type("application/json") is True
        assert RequestValidator.validate_content_type("application/json; charset=utf-8") is True

    def test_validate_content_type_form(self):
        """测试表单内容类型"""
        assert RequestValidator.validate_content_type("application/x-www-form-urlencoded") is True

    def test_validate_content_type_invalid(self):
        """测试无效内容类型"""
        assert RequestValidator.validate_content_type("text/html") is False
        assert RequestValidator.validate_content_type("application/xml") is False

    def test_validate_content_type_none(self):
        """测试空内容类型（GET 请求）"""
        assert RequestValidator.validate_content_type(None) is True

    def test_validate_content_length_valid(self):
        """测试有效内容长度"""
        assert RequestValidator.validate_content_length(1024) is True
        assert RequestValidator.validate_content_length(1024 * 1024) is True  # 1MB

    def test_validate_content_length_exceeds(self):
        """测试超出限制的内容长度"""
        assert RequestValidator.validate_content_length(1024 * 1024 + 1) is False
        assert RequestValidator.validate_content_length(10 * 1024 * 1024) is False

    def test_validate_content_length_none(self):
        """测试空内容长度"""
        assert RequestValidator.validate_content_length(None) is True


# ==================== SecurityConfig 测试 ====================

class TestSecurityConfig:
    """安全配置测试"""

    def test_default_config(self):
        """测试默认配置"""
        assert SecurityConfig.ENABLE_SECURITY_HEADERS is True
        assert SecurityConfig.ENABLE_INPUT_VALIDATION is True
        assert SecurityConfig.MAX_REQUEST_SIZE == 1024 * 1024
        assert SecurityConfig.API_KEY_HEADER == "X-API-Key"
        assert SecurityConfig.API_KEYS == []


# ==================== SecurityHeadersMiddleware 测试 ====================

class TestSecurityHeadersMiddleware:
    """安全头中间件测试"""

    def test_adds_security_headers(self):
        """测试添加安全响应头"""
        middleware = SecurityHeadersMiddleware(app=MagicMock())

        # 创建模拟请求
        request = MagicMock(spec=Request)
        request.url = MagicMock()
        request.url.path = "/api/v1/analyze"

        # 创建模拟响应
        response = Response(content="test")
        call_next = AsyncMock(return_value=response)

        # 使用 asyncio.run 执行异步函数
        result = asyncio.get_event_loop().run_until_complete(
            middleware.dispatch(request, call_next)
        )

        # 验证安全头
        assert result.headers.get("X-Content-Type-Options") == "nosniff"
        assert result.headers.get("X-Frame-Options") == "DENY"
        assert result.headers.get("X-XSS-Protection") == "1; mode=block"
        assert result.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_adds_cache_control_for_api(self):
        """测试 API 路径添加缓存控制头"""
        middleware = SecurityHeadersMiddleware(app=MagicMock())

        request = MagicMock(spec=Request)
        request.url = MagicMock()
        request.url.path = "/api/v1/analyze"

        response = Response(content="test")
        call_next = AsyncMock(return_value=response)

        result = asyncio.get_event_loop().run_until_complete(
            middleware.dispatch(request, call_next)
        )

        # API 路径应禁用缓存
        assert result.headers.get("Cache-Control") == "no-store, no-cache, must-revalidate"
        assert result.headers.get("Pragma") == "no-cache"

    def test_no_cache_control_for_non_api(self):
        """测试非 API 路径不添加缓存控制"""
        middleware = SecurityHeadersMiddleware(app=MagicMock())

        request = MagicMock(spec=Request)
        request.url = MagicMock()
        request.url.path = "/docs"

        response = Response(content="test")
        call_next = AsyncMock(return_value=response)

        result = asyncio.get_event_loop().run_until_complete(
            middleware.dispatch(request, call_next)
        )

        # 非 API 路径不应有缓存控制
        assert result.headers.get("Cache-Control") is None


# ==================== require_safe_input 装饰器测试 ====================

class TestRequireSafeInput:
    """安全输入装饰器测试"""

    def test_safe_query_passes(self):
        """测试安全查询通过"""
        @require_safe_input
        async def handler(query: str):
            return {"result": query}

        result = asyncio.get_event_loop().run_until_complete(
            handler(query="分析苹果股票")
        )
        assert result["result"] == "分析苹果股票"

    def test_unsafe_query_blocked(self):
        """测试不安全查询被阻止"""
        @require_safe_input
        async def handler(query: str):
            return {"result": query}

        with pytest.raises(HTTPException) as exc_info:
            asyncio.get_event_loop().run_until_complete(
                handler(query="SELECT * FROM users")
            )

        assert exc_info.value.status_code == 400
        assert "不安全" in exc_info.value.detail

    def test_empty_query_passes(self):
        """测试空查询通过"""
        @require_safe_input
        async def handler(query: str = None):
            return {"result": query}

        result = asyncio.get_event_loop().run_until_complete(
            handler(query=None)
        )
        assert result["result"] is None

    def test_positional_argument(self):
        """测试位置参数"""
        @require_safe_input
        async def handler(query: str):
            return {"result": query}

        # 作为位置参数传递
        result = asyncio.get_event_loop().run_until_complete(
            handler("正常查询")
        )
        assert result["result"] == "正常查询"


# ==================== 综合测试 ====================

class TestSecurityIntegration:
    """安全模块综合测试"""

    def test_all_modules_importable(self):
        """测试所有模块可导入"""
        from finsight.infrastructure.security import (
            SecurityHeadersMiddleware,
            InputSanitizer,
            RequestValidator,
            SecurityConfig,
            require_safe_input,
        )
        assert SecurityHeadersMiddleware is not None
        assert InputSanitizer is not None
        assert RequestValidator is not None
        assert SecurityConfig is not None
        assert require_safe_input is not None

    def test_security_workflow(self):
        """测试安全工作流程"""
        # 1. 验证股票代码
        ticker = InputSanitizer.sanitize_ticker("aapl")
        assert ticker == "AAPL"

        # 2. 验证查询安全
        query = f"分析 {ticker} 股票"
        assert InputSanitizer.is_safe_query(query) is True

        # 3. 清理显示内容
        safe_output = InputSanitizer.sanitize_string(query)
        assert safe_output == query

    def test_sql_injection_variants(self):
        """测试各种 SQL 注入变体（仅检测带关键字的注入）"""
        # 这些模式包含 SQL 关键字，会被检测到
        injections = [
            "'; DROP TABLE users; --",
            "UNION SELECT * FROM",
            "INSERT INTO logs",
            "ALTER TABLE users",
            "CREATE TABLE hack",
            "DELETE FROM records",
        ]
        for injection in injections:
            assert InputSanitizer.is_safe_query(injection) is False, f"未检测到: {injection}"

    def test_xss_variants(self):
        """测试各种 XSS 变体"""
        xss_attempts = [
            "<script>evil()</script>",
            "<img onerror=alert(1)>",
            "javascript:void(0)",
            "<div onclick=hack()>",
        ]
        for xss in xss_attempts:
            assert InputSanitizer.is_safe_query(xss) is False, f"未检测到: {xss}"

    def test_safe_financial_queries(self):
        """测试金融相关的安全查询"""
        safe_queries = [
            "分析苹果公司股票",
            "查看特斯拉最新新闻",
            "比较 AAPL 和 MSFT 的收益",
            "市场情绪如何？",
            "获取经济日历",
            "TSLA 股价是多少",
            "恐慌与贪婪指数",
        ]
        for query in safe_queries:
            assert InputSanitizer.is_safe_query(query) is True, f"误报: {query}"

"""
Infrastructure 层测试 - 日志、指标、错误处理
"""

import pytest
import logging
import time
from unittest.mock import Mock, patch, MagicMock
from io import StringIO

from finsight.infrastructure.logging import (
    setup_logging,
    get_logger,
    LogContext,
    log_performance,
    StructuredFormatter,
    SimpleFormatter,
)
from finsight.infrastructure.metrics import (
    MetricsRegistry,
    Counter,
    Gauge,
    Histogram,
    Timer,
    get_metrics_registry,
    increment_counter,
    record_histogram,
    set_gauge,
)
from finsight.infrastructure.errors import (
    FinSightError,
    ValidationError,
    ResourceNotFoundError,
    DataUnavailableError,
    RateLimitError,
    LLMError,
    TimeoutError,
    ErrorHandler,
    retry,
    error_boundary,
)
from finsight.domain.models import ErrorCode


class TestLogging:
    """日志系统测试"""

    def test_get_logger(self):
        """测试获取 logger"""
        logger = get_logger("test")
        assert logger is not None
        assert isinstance(logger, logging.Logger)

    def test_structured_formatter(self):
        """测试结构化格式化器"""
        formatter = StructuredFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)
        assert "Test message" in formatted

    def test_simple_formatter(self):
        """测试简单格式化器"""
        formatter = SimpleFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        formatted = formatter.format(record)
        assert "Test message" in formatted

    def test_log_context(self):
        """测试日志上下文"""
        logger = get_logger("test_context")
        with LogContext(logger=logger, operation="测试操作", request_id="test-123") as ctx:
            assert ctx.operation == "测试操作"
            assert ctx.request_id == "test-123"

    def test_log_performance_decorator(self):
        """测试性能日志装饰器"""
        logger = get_logger("test_perf")

        @log_performance(logger)
        def slow_function():
            time.sleep(0.01)
            return "done"

        result = slow_function()
        assert result == "done"


class TestMetrics:
    """指标系统测试"""

    def test_counter_increment(self):
        """测试计数器递增"""
        counter = Counter("test_counter", "Test counter")
        assert counter.get() == 0

        counter.inc()
        assert counter.get() == 1

        counter.inc(5)
        assert counter.get() == 6

    def test_gauge_set(self):
        """测试仪表设置"""
        gauge = Gauge("test_gauge", "Test gauge")
        assert gauge.get() == 0

        gauge.set(42)
        assert gauge.get() == 42

        gauge.inc(8)
        assert gauge.get() == 50

        gauge.dec(10)
        assert gauge.get() == 40

    def test_histogram_observe(self):
        """测试直方图观察"""
        histogram = Histogram("test_histogram", "Test histogram")

        histogram.observe(1.5)
        histogram.observe(2.5)
        histogram.observe(3.5)

        stats = histogram.get_stats()
        assert stats["count"] == 3
        assert stats["sum"] == 7.5

    def test_timer_context(self):
        """测试计时器上下文"""
        histogram = Histogram("test_timer", "Test timer")
        timer = Timer(histogram)

        with timer:
            time.sleep(0.01)

        stats = histogram.get_stats()
        assert stats["count"] == 1
        assert stats["sum"] > 0

    def test_metrics_registry(self):
        """测试指标注册表"""
        registry = MetricsRegistry()

        counter = registry.register_counter("test_counter_2", "Test counter")
        assert counter is not None

        gauge = registry.register_gauge("test_gauge_2", "Test gauge")
        assert gauge is not None

        histogram = registry.register_histogram("test_histogram_2", "Test histogram")
        assert histogram is not None

    def test_get_metrics_registry_singleton(self):
        """测试指标注册表单例"""
        registry1 = get_metrics_registry()
        registry2 = get_metrics_registry()
        assert registry1 is registry2

    def test_increment_counter_helper(self):
        """测试计数器递增辅助函数"""
        registry = get_metrics_registry()
        registry.register_counter("test_helper_counter", "Test helper")

        increment_counter("test_helper_counter")
        increment_counter("test_helper_counter", 5)
        # 应该不抛出异常

    def test_set_gauge_helper(self):
        """测试仪表设置辅助函数"""
        registry = get_metrics_registry()
        registry.register_gauge("test_helper_gauge", "Test helper")

        set_gauge("test_helper_gauge", 42)
        # 应该不抛出异常

    def test_record_histogram_helper(self):
        """测试直方图记录辅助函数"""
        registry = get_metrics_registry()
        registry.register_histogram("test_helper_histogram", "Test helper")

        record_histogram("test_helper_histogram", 1.5)
        # 应该不抛出异常


class TestErrors:
    """错误处理测试"""

    def test_finsight_error(self):
        """测试基础错误"""
        error = FinSightError(
            message="Test error",
            error_code=ErrorCode.INTERNAL_ERROR,
            details={"key": "value"},
        )

        assert error.message == "Test error"
        assert error.error_code == ErrorCode.INTERNAL_ERROR
        assert error.details == {"key": "value"}

        error_dict = error.to_dict()
        assert error_dict["message"] == "Test error"
        assert error_dict["error_code"] == ErrorCode.INTERNAL_ERROR.value

    def test_validation_error(self):
        """测试验证错误"""
        error = ValidationError("Invalid input", field="email")

        assert error.message == "Invalid input"
        assert error.error_code == ErrorCode.INVALID_INPUT
        assert error.details.get("field") == "email"

    def test_resource_not_found_error(self):
        """测试资源未找到错误"""
        error = ResourceNotFoundError("Stock", "INVALID")

        assert "INVALID" in error.message
        assert error.error_code == ErrorCode.TICKER_NOT_FOUND

    def test_data_unavailable_error(self):
        """测试数据不可用错误"""
        error = DataUnavailableError("Yahoo Finance", "Rate limited")

        assert "Yahoo Finance" in error.message
        assert error.error_code == ErrorCode.DATA_UNAVAILABLE

    def test_rate_limit_error(self):
        """测试频率限制错误"""
        error = RateLimitError("API", retry_after=60)

        assert "API" in error.message
        assert error.details.get("retry_after") == 60
        assert error.error_code == ErrorCode.RATE_LIMITED

    def test_llm_error(self):
        """测试 LLM 错误"""
        error = LLMError("Model timeout", provider="OpenAI")

        assert error.message == "Model timeout"
        assert error.details.get("provider") == "OpenAI"
        assert error.error_code == ErrorCode.LLM_ERROR

    def test_timeout_error(self):
        """测试超时错误"""
        error = TimeoutError("fetch_data", 30.0)

        assert "fetch_data" in error.message
        assert "30" in error.message
        assert error.error_code == ErrorCode.TIMEOUT


class TestRetryMechanism:
    """重试机制测试"""

    def test_retry_success_first_attempt(self):
        """测试首次成功"""
        call_count = 0

        @retry(max_attempts=3)
        def successful_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = successful_func()
        assert result == "success"
        assert call_count == 1

    def test_retry_success_after_failures(self):
        """测试失败后成功"""
        call_count = 0

        @retry(max_attempts=3, delay=0.01)
        def eventually_successful():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("Temporary error")
            return "success"

        result = eventually_successful()
        assert result == "success"
        assert call_count == 3

    def test_retry_all_attempts_fail(self):
        """测试所有尝试都失败"""
        call_count = 0

        @retry(max_attempts=3, delay=0.01)
        def always_fail():
            nonlocal call_count
            call_count += 1
            raise ValueError("Always fails")

        with pytest.raises(ValueError):
            always_fail()

        assert call_count == 3

    def test_retry_specific_exceptions(self):
        """测试只重试特定异常"""
        call_count = 0

        @retry(max_attempts=3, delay=0.01, exceptions=(ValueError,))
        def specific_exception():
            nonlocal call_count
            call_count += 1
            raise TypeError("Not retried")

        with pytest.raises(TypeError):
            specific_exception()

        assert call_count == 1  # 不重试 TypeError


class TestErrorHandler:
    """错误处理器测试"""

    def test_handle_finsight_error(self):
        """测试处理 FinSightError"""
        original = ValidationError("Test")
        result = ErrorHandler.handle_exception(original)

        assert result is original

    def test_handle_timeout_exception(self):
        """测试处理超时异常"""
        import asyncio
        try:
            raise asyncio.TimeoutError("Timeout")
        except Exception as e:
            result = ErrorHandler.handle_exception(e, "test_operation")
            assert isinstance(result, TimeoutError)

    def test_handle_generic_exception(self):
        """测试处理通用异常"""
        try:
            raise ValueError("Generic error")
        except Exception as e:
            result = ErrorHandler.handle_exception(e, "test_context")
            assert isinstance(result, FinSightError)
            assert result.error_code == ErrorCode.INTERNAL_ERROR

    def test_safe_execute_success(self):
        """测试安全执行成功"""
        def success_func():
            return "result"

        result = ErrorHandler.safe_execute(success_func)
        assert result == "result"

    def test_safe_execute_failure(self):
        """测试安全执行失败"""
        def fail_func():
            raise ValueError("Error")

        result = ErrorHandler.safe_execute(fail_func, default="default")
        assert result == "default"


class TestErrorBoundary:
    """错误边界测试"""

    def test_error_boundary_success(self):
        """测试错误边界成功"""
        @error_boundary(default=None)
        def success_func():
            return "result"

        result = success_func()
        assert result == "result"

    def test_error_boundary_failure(self):
        """测试错误边界失败"""
        @error_boundary(default="fallback")
        def fail_func():
            raise ValueError("Error")

        result = fail_func()
        assert result == "fallback"

    def test_error_boundary_reraise(self):
        """测试错误边界重抛"""
        @error_boundary(default=None, reraise=True)
        def fail_func():
            raise ValueError("Error")

        with pytest.raises(FinSightError):
            fail_func()

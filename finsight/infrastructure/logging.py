"""
日志系统 - 结构化日志配置

提供：
- 结构化 JSON 日志
- 请求追踪
- 性能指标记录
- 多输出目标支持
"""

import logging
import json
import sys
from datetime import datetime
from typing import Optional, Dict, Any
from functools import wraps
import time


class StructuredFormatter(logging.Formatter):
    """结构化 JSON 日志格式化器"""

    def format(self, record: logging.LogRecord) -> str:
        """格式化日志记录为 JSON"""
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
            "function": record.funcName,
            "line": record.lineno,
        }

        # 添加额外字段
        if hasattr(record, 'request_id'):
            log_data["request_id"] = record.request_id
        if hasattr(record, 'user_id'):
            log_data["user_id"] = record.user_id
        if hasattr(record, 'duration_ms'):
            log_data["duration_ms"] = record.duration_ms
        if hasattr(record, 'extra_data'):
            log_data["data"] = record.extra_data

        # 异常信息
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


class SimpleFormatter(logging.Formatter):
    """简单的彩色日志格式化器（开发环境）"""

    COLORS = {
        'DEBUG': '\033[36m',     # 青色
        'INFO': '\033[32m',      # 绿色
        'WARNING': '\033[33m',   # 黄色
        'ERROR': '\033[31m',     # 红色
        'CRITICAL': '\033[35m',  # 紫色
    }
    RESET = '\033[0m'

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, self.RESET)
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 构建基础消息
        msg = f"{color}[{timestamp}] [{record.levelname}]{self.RESET} {record.getMessage()}"

        # 添加请求 ID
        if hasattr(record, 'request_id'):
            msg = f"{color}[{record.request_id}]{self.RESET} {msg}"

        # 添加持续时间
        if hasattr(record, 'duration_ms'):
            msg += f" ({record.duration_ms:.2f}ms)"

        return msg


def setup_logging(
    level: str = "INFO",
    json_format: bool = False,
    log_file: Optional[str] = None
) -> logging.Logger:
    """
    配置日志系统

    Args:
        level: 日志级别
        json_format: 是否使用 JSON 格式
        log_file: 日志文件路径（可选）

    Returns:
        logging.Logger: 根日志记录器
    """
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))

    # 清除现有处理器
    root_logger.handlers.clear()

    # 控制台处理器
    console_handler = logging.StreamHandler(sys.stdout)
    if json_format:
        console_handler.setFormatter(StructuredFormatter())
    else:
        console_handler.setFormatter(SimpleFormatter())
    root_logger.addHandler(console_handler)

    # 文件处理器（可选）
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(StructuredFormatter())
        root_logger.addHandler(file_handler)

    return root_logger


def get_logger(name: str) -> logging.Logger:
    """获取命名日志记录器"""
    return logging.getLogger(name)


class LogContext:
    """日志上下文管理器"""

    def __init__(
        self,
        logger: logging.Logger,
        operation: str,
        request_id: Optional[str] = None,
        **extra
    ):
        self.logger = logger
        self.operation = operation
        self.request_id = request_id
        self.extra = extra
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        self.logger.info(
            f"开始 {self.operation}",
            extra={
                'request_id': self.request_id,
                'extra_data': self.extra
            }
        )
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = (time.time() - self.start_time) * 1000
        if exc_type:
            self.logger.error(
                f"失败 {self.operation}: {exc_val}",
                extra={
                    'request_id': self.request_id,
                    'duration_ms': duration,
                    'extra_data': self.extra
                },
                exc_info=True
            )
        else:
            self.logger.info(
                f"完成 {self.operation}",
                extra={
                    'request_id': self.request_id,
                    'duration_ms': duration,
                    'extra_data': self.extra
                }
            )
        return False


def log_performance(logger: Optional[logging.Logger] = None):
    """性能日志装饰器"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            nonlocal logger
            if logger is None:
                logger = get_logger(func.__module__)

            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                duration = (time.time() - start_time) * 1000
                logger.info(
                    f"{func.__name__} 执行成功",
                    extra={'duration_ms': duration}
                )
                return result
            except Exception as e:
                duration = (time.time() - start_time) * 1000
                logger.error(
                    f"{func.__name__} 执行失败: {e}",
                    extra={'duration_ms': duration},
                    exc_info=True
                )
                raise
        return wrapper
    return decorator


def log_async_performance(logger: Optional[logging.Logger] = None):
    """异步性能日志装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            nonlocal logger
            if logger is None:
                logger = get_logger(func.__module__)

            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                duration = (time.time() - start_time) * 1000
                logger.info(
                    f"{func.__name__} 执行成功",
                    extra={'duration_ms': duration}
                )
                return result
            except Exception as e:
                duration = (time.time() - start_time) * 1000
                logger.error(
                    f"{func.__name__} 执行失败: {e}",
                    extra={'duration_ms': duration},
                    exc_info=True
                )
                raise
        return wrapper
    return decorator

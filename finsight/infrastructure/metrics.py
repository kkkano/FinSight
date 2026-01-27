"""
指标系统 - 应用性能监控

提供：
- 请求计数
- 延迟统计
- 错误率追踪
- 资源使用监控
"""

import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from collections import defaultdict
from threading import Lock, RLock
from enum import Enum


class MetricType(str, Enum):
    """指标类型"""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class MetricPoint:
    """指标数据点"""
    name: str
    value: float
    timestamp: datetime
    labels: Dict[str, str] = field(default_factory=dict)
    metric_type: MetricType = MetricType.GAUGE


class Counter:
    """计数器 - 只增不减的指标"""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._value = 0.0
        self._lock = Lock()

    def inc(self, value: float = 1.0):
        """增加计数"""
        with self._lock:
            self._value += value

    def get(self) -> float:
        """获取当前值"""
        with self._lock:
            return self._value


class Gauge:
    """仪表盘 - 可增可减的指标"""

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._value = 0.0
        self._lock = Lock()

    def set(self, value: float):
        """设置值"""
        with self._lock:
            self._value = value

    def inc(self, value: float = 1.0):
        """增加"""
        with self._lock:
            self._value += value

    def dec(self, value: float = 1.0):
        """减少"""
        with self._lock:
            self._value -= value

    def get(self) -> float:
        """获取当前值"""
        with self._lock:
            return self._value


class Histogram:
    """直方图 - 记录值的分布"""

    DEFAULT_BUCKETS = [0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10]

    def __init__(
        self,
        name: str,
        description: str = "",
        buckets: Optional[List[float]] = None
    ):
        self.name = name
        self.description = description
        self.buckets = buckets or self.DEFAULT_BUCKETS
        self._counts = defaultdict(int)
        self._sum = 0.0
        self._count = 0
        self._lock = RLock()  # 使用可重入锁以支持 get_stats 中嵌套调用 get_percentile

    def observe(self, value: float):
        """记录一个观察值"""
        with self._lock:
            self._sum += value
            self._count += 1
            for bucket in self.buckets:
                if value <= bucket:
                    self._counts[bucket] += 1

    def get_percentile(self, p: float) -> float:
        """获取百分位数"""
        with self._lock:
            if self._count == 0:
                return 0.0
            target = self._count * p / 100
            cumulative = 0
            for bucket in sorted(self.buckets):
                cumulative += self._counts[bucket]
                if cumulative >= target:
                    return bucket
            return self.buckets[-1]

    def get_stats(self) -> Dict[str, float]:
        """获取统计信息"""
        with self._lock:
            return {
                "count": self._count,
                "sum": self._sum,
                "avg": self._sum / self._count if self._count > 0 else 0,
                "p50": self.get_percentile(50),
                "p90": self.get_percentile(90),
                "p95": self.get_percentile(95),
                "p99": self.get_percentile(99),
            }


class Timer:
    """计时器 - 用于测量代码执行时间"""

    def __init__(self, histogram: Histogram):
        self.histogram = histogram
        self.start_time = None

    def __enter__(self):
        self.start_time = time.time()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = time.time() - self.start_time
        self.histogram.observe(duration)
        return False


class MetricsRegistry:
    """指标注册表 - 管理所有指标"""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._metrics: Dict[str, Any] = {}
        self._lock = Lock()
        self._initialized = True

        # 注册默认指标
        self._setup_default_metrics()

    def _setup_default_metrics(self):
        """设置默认指标"""
        # 请求指标
        self.register_counter(
            "finsight_requests_total",
            "总请求数"
        )
        self.register_counter(
            "finsight_requests_success",
            "成功请求数"
        )
        self.register_counter(
            "finsight_requests_failed",
            "失败请求数"
        )

        # 延迟指标
        self.register_histogram(
            "finsight_request_duration_seconds",
            "请求处理时间",
            buckets=[0.1, 0.5, 1, 2, 5, 10, 30]
        )

        # 意图分类指标
        self.register_counter(
            "finsight_intent_total",
            "按意图分类的请求数"
        )

        # 工具调用指标
        self.register_counter(
            "finsight_tool_calls_total",
            "工具调用次数"
        )
        self.register_histogram(
            "finsight_tool_duration_seconds",
            "工具执行时间"
        )

        # 活跃请求
        self.register_gauge(
            "finsight_active_requests",
            "当前活跃请求数"
        )

    def register_counter(self, name: str, description: str = "") -> Counter:
        """注册计数器"""
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = Counter(name, description)
            return self._metrics[name]

    def register_gauge(self, name: str, description: str = "") -> Gauge:
        """注册仪表盘"""
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = Gauge(name, description)
            return self._metrics[name]

    def register_histogram(
        self,
        name: str,
        description: str = "",
        buckets: Optional[List[float]] = None
    ) -> Histogram:
        """注册直方图"""
        with self._lock:
            if name not in self._metrics:
                self._metrics[name] = Histogram(name, description, buckets)
            return self._metrics[name]

    def get(self, name: str) -> Any:
        """获取指标"""
        with self._lock:
            return self._metrics.get(name)

    def get_all_metrics(self) -> Dict[str, Any]:
        """获取所有指标的当前值"""
        result = {}
        with self._lock:
            for name, metric in self._metrics.items():
                if isinstance(metric, Counter):
                    result[name] = {"type": "counter", "value": metric.get()}
                elif isinstance(metric, Gauge):
                    result[name] = {"type": "gauge", "value": metric.get()}
                elif isinstance(metric, Histogram):
                    result[name] = {"type": "histogram", **metric.get_stats()}
        return result


# 全局指标注册表
_registry = None


def get_metrics_registry() -> MetricsRegistry:
    """获取全局指标注册表"""
    global _registry
    if _registry is None:
        _registry = MetricsRegistry()
    return _registry


# 便捷函数
def increment_counter(name: str, value: float = 1.0):
    """增加计数器"""
    registry = get_metrics_registry()
    counter = registry.get(name)
    if counter:
        counter.inc(value)


def record_histogram(name: str, value: float):
    """记录直方图值"""
    registry = get_metrics_registry()
    histogram = registry.get(name)
    if histogram:
        histogram.observe(value)


def set_gauge(name: str, value: float):
    """设置仪表盘值"""
    registry = get_metrics_registry()
    gauge = registry.get(name)
    if gauge:
        gauge.set(value)


def time_histogram(name: str) -> Timer:
    """创建计时器"""
    registry = get_metrics_registry()
    histogram = registry.get(name)
    return Timer(histogram) if histogram else Timer(Histogram(name))

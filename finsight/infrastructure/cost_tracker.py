"""
成本追踪系统 - API调用成本监控

提供：
- API调用计数
- 成本估算
- 预算告警
- 使用报告
"""

import time
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from threading import Lock, RLock
from enum import Enum
from collections import defaultdict


class CostTier(str, Enum):
    """成本等级"""
    FREE = "free"           # 免费
    LOW = "low"             # 低成本
    MEDIUM = "medium"       # 中等成本
    HIGH = "high"           # 高成本
    PREMIUM = "premium"     # 高级（LLM等）


@dataclass
class ServiceCost:
    """服务成本配置"""
    service_name: str
    tier: CostTier
    cost_per_call: float = 0.0      # 每次调用成本（美元）
    daily_free_quota: int = 0        # 每日免费配额
    monthly_budget: float = 0.0      # 月度预算
    description: str = ""


@dataclass
class UsageRecord:
    """使用记录"""
    service: str
    timestamp: float
    cost: float
    success: bool
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class UsageStats:
    """使用统计"""
    total_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    total_cost: float = 0.0
    avg_duration_ms: float = 0.0
    calls_today: int = 0
    cost_today: float = 0.0
    calls_this_month: int = 0
    cost_this_month: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """转为字典"""
        return {
            "total_calls": self.total_calls,
            "successful_calls": self.successful_calls,
            "failed_calls": self.failed_calls,
            "success_rate": round(
                self.successful_calls / self.total_calls * 100, 2
            ) if self.total_calls > 0 else 0.0,
            "total_cost": round(self.total_cost, 4),
            "avg_duration_ms": round(self.avg_duration_ms, 2),
            "calls_today": self.calls_today,
            "cost_today": round(self.cost_today, 4),
            "calls_this_month": self.calls_this_month,
            "cost_this_month": round(self.cost_this_month, 4),
        }


class CostTracker:
    """
    成本追踪器

    追踪单个服务的API调用成本。
    """

    def __init__(self, config: ServiceCost):
        """
        初始化追踪器

        Args:
            config: 服务成本配置
        """
        self.config = config
        self._records: List[UsageRecord] = []
        self._lock = Lock()
        self._total_duration_ms: float = 0.0

        # 告警回调
        self._alert_callbacks: List[Callable[[str, float, float], None]] = []

    def record_call(
        self,
        success: bool = True,
        duration_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> UsageRecord:
        """
        记录API调用

        Args:
            success: 是否成功
            duration_ms: 耗时（毫秒）
            metadata: 额外元数据

        Returns:
            使用记录
        """
        with self._lock:
            # 计算成本（免费配额内不计费）
            today_calls = self._count_calls_today()
            if today_calls < self.config.daily_free_quota:
                cost = 0.0
            else:
                cost = self.config.cost_per_call

            record = UsageRecord(
                service=self.config.service_name,
                timestamp=time.time(),
                cost=cost,
                success=success,
                duration_ms=duration_ms,
                metadata=metadata or {},
            )

            self._records.append(record)
            self._total_duration_ms += duration_ms

            # 检查预算告警
            self._check_budget_alert()

            return record

    def _count_calls_today(self) -> int:
        """统计今日调用次数"""
        today_start = datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ).timestamp()

        return sum(
            1 for r in self._records
            if r.timestamp >= today_start
        )

    def _check_budget_alert(self) -> None:
        """检查预算告警"""
        if self.config.monthly_budget <= 0:
            return

        month_cost = self._get_month_cost()
        usage_percent = month_cost / self.config.monthly_budget

        # 80% 和 100% 告警
        if usage_percent >= 1.0:
            self._trigger_alert("budget_exceeded", month_cost, self.config.monthly_budget)
        elif usage_percent >= 0.8:
            self._trigger_alert("budget_warning", month_cost, self.config.monthly_budget)

    def _get_month_cost(self) -> float:
        """获取本月成本"""
        month_start = datetime.now().replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        ).timestamp()

        return sum(
            r.cost for r in self._records
            if r.timestamp >= month_start
        )

    def _trigger_alert(
        self,
        alert_type: str,
        current: float,
        threshold: float
    ) -> None:
        """触发告警"""
        for callback in self._alert_callbacks:
            try:
                callback(alert_type, current, threshold)
            except Exception:
                pass

    def add_alert_callback(
        self,
        callback: Callable[[str, float, float], None]
    ) -> None:
        """添加告警回调"""
        with self._lock:
            self._alert_callbacks.append(callback)

    def get_stats(self) -> UsageStats:
        """获取使用统计"""
        with self._lock:
            now = time.time()
            today_start = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            ).timestamp()
            month_start = datetime.now().replace(
                day=1, hour=0, minute=0, second=0, microsecond=0
            ).timestamp()

            total_calls = len(self._records)
            successful_calls = sum(1 for r in self._records if r.success)
            failed_calls = total_calls - successful_calls
            total_cost = sum(r.cost for r in self._records)

            calls_today = sum(1 for r in self._records if r.timestamp >= today_start)
            cost_today = sum(r.cost for r in self._records if r.timestamp >= today_start)

            calls_this_month = sum(1 for r in self._records if r.timestamp >= month_start)
            cost_this_month = sum(r.cost for r in self._records if r.timestamp >= month_start)

            avg_duration = (
                self._total_duration_ms / total_calls
                if total_calls > 0 else 0.0
            )

            return UsageStats(
                total_calls=total_calls,
                successful_calls=successful_calls,
                failed_calls=failed_calls,
                total_cost=total_cost,
                avg_duration_ms=avg_duration,
                calls_today=calls_today,
                cost_today=cost_today,
                calls_this_month=calls_this_month,
                cost_this_month=cost_this_month,
            )

    def cleanup_old_records(self, days: int = 30) -> int:
        """
        清理旧记录

        Args:
            days: 保留天数

        Returns:
            清理的记录数
        """
        with self._lock:
            cutoff = time.time() - days * 24 * 3600
            old_count = len(self._records)

            self._records = [
                r for r in self._records
                if r.timestamp >= cutoff
            ]

            return old_count - len(self._records)


class CostTrackerManager:
    """
    成本追踪管理器

    管理多个服务的成本追踪。
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._trackers: Dict[str, CostTracker] = {}
        self._lock = RLock()  # 使用可重入锁避免死锁
        self._initialized = True
        self._global_callbacks: List[Callable[[str, str, float, float], None]] = []

        # 注册默认追踪器
        self._setup_default_trackers()

    def _setup_default_trackers(self):
        """设置默认追踪器"""
        # Yahoo Finance（免费）
        self.register_tracker(ServiceCost(
            service_name="yfinance",
            tier=CostTier.FREE,
            cost_per_call=0.0,
            daily_free_quota=1000,
            monthly_budget=0.0,
            description="Yahoo Finance 市场数据",
        ))

        # DuckDuckGo Search（免费）
        self.register_tracker(ServiceCost(
            service_name="ddgs",
            tier=CostTier.FREE,
            cost_per_call=0.0,
            daily_free_quota=500,
            monthly_budget=0.0,
            description="DuckDuckGo 搜索",
        ))

        # CNN Fear & Greed（免费）
        self.register_tracker(ServiceCost(
            service_name="cnn",
            tier=CostTier.FREE,
            cost_per_call=0.0,
            daily_free_quota=100,
            monthly_budget=0.0,
            description="CNN Fear & Greed 指数",
        ))

        # OpenAI API（付费）
        self.register_tracker(ServiceCost(
            service_name="openai",
            tier=CostTier.PREMIUM,
            cost_per_call=0.003,  # 估算，实际按token计费
            daily_free_quota=0,
            monthly_budget=10.0,  # $10/月预算
            description="OpenAI GPT API",
        ))

        # 通用追踪器
        self.register_tracker(ServiceCost(
            service_name="default",
            tier=CostTier.LOW,
            cost_per_call=0.0,
            daily_free_quota=10000,
            monthly_budget=0.0,
            description="默认追踪器",
        ))

    def register_tracker(self, config: ServiceCost) -> CostTracker:
        """
        注册追踪器

        Args:
            config: 服务成本配置

        Returns:
            追踪器实例
        """
        with self._lock:
            if config.service_name not in self._trackers:
                tracker = CostTracker(config)

                # 添加全局告警转发
                def forward_alert(alert_type, current, threshold):
                    for callback in self._global_callbacks:
                        callback(config.service_name, alert_type, current, threshold)

                tracker.add_alert_callback(forward_alert)
                self._trackers[config.service_name] = tracker

            return self._trackers[config.service_name]

    def get_tracker(self, service: str) -> CostTracker:
        """
        获取追踪器

        Args:
            service: 服务名称

        Returns:
            追踪器实例
        """
        with self._lock:
            return self._trackers.get(service, self._trackers.get("default"))

    def record_call(
        self,
        service: str,
        success: bool = True,
        duration_ms: float = 0.0,
        metadata: Optional[Dict[str, Any]] = None
    ) -> UsageRecord:
        """
        记录API调用

        Args:
            service: 服务名称
            success: 是否成功
            duration_ms: 耗时
            metadata: 元数据

        Returns:
            使用记录
        """
        tracker = self.get_tracker(service)
        if tracker:
            return tracker.record_call(success, duration_ms, metadata)
        return None

    def add_global_alert_callback(
        self,
        callback: Callable[[str, str, float, float], None]
    ) -> None:
        """
        添加全局告警回调

        Args:
            callback: 回调函数(service, alert_type, current, threshold)
        """
        with self._lock:
            self._global_callbacks.append(callback)

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取所有服务的统计信息"""
        with self._lock:
            return {
                name: tracker.get_stats().to_dict()
                for name, tracker in self._trackers.items()
            }

    def get_total_cost(self) -> Dict[str, float]:
        """获取总成本摘要"""
        with self._lock:
            result = {
                "total": 0.0,
                "today": 0.0,
                "this_month": 0.0,
                "by_service": {},
            }

            for name, tracker in self._trackers.items():
                stats = tracker.get_stats()
                result["total"] += stats.total_cost
                result["today"] += stats.cost_today
                result["this_month"] += stats.cost_this_month
                result["by_service"][name] = {
                    "total": stats.total_cost,
                    "today": stats.cost_today,
                    "this_month": stats.cost_this_month,
                }

            return result

    def generate_usage_report(self) -> Dict[str, Any]:
        """生成使用报告"""
        with self._lock:
            report = {
                "generated_at": datetime.now().isoformat(),
                "summary": self.get_total_cost(),
                "services": {},
            }

            for name, tracker in self._trackers.items():
                stats = tracker.get_stats()
                report["services"][name] = {
                    "config": {
                        "tier": tracker.config.tier.value,
                        "cost_per_call": tracker.config.cost_per_call,
                        "daily_free_quota": tracker.config.daily_free_quota,
                        "monthly_budget": tracker.config.monthly_budget,
                    },
                    "stats": stats.to_dict(),
                }

            return report

    def cleanup_all_old_records(self, days: int = 30) -> Dict[str, int]:
        """清理所有追踪器的旧记录"""
        with self._lock:
            return {
                name: tracker.cleanup_old_records(days)
                for name, tracker in self._trackers.items()
            }


# 全局成本追踪管理器
_cost_tracker_manager = None


def get_cost_tracker_manager() -> CostTrackerManager:
    """获取全局成本追踪管理器"""
    global _cost_tracker_manager
    if _cost_tracker_manager is None:
        _cost_tracker_manager = CostTrackerManager()
    return _cost_tracker_manager


def track_cost(service: str):
    """
    成本追踪装饰器

    Args:
        service: 服务名称

    Returns:
        装饰器函数
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            manager = get_cost_tracker_manager()
            start_time = time.time()
            success = True

            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                success = False
                raise
            finally:
                duration_ms = (time.time() - start_time) * 1000
                manager.record_call(
                    service=service,
                    success=success,
                    duration_ms=duration_ms,
                )

        return wrapper
    return decorator

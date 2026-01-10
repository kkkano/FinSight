# -*- coding: utf-8 -*-
"""
ToolOrchestrator - 工具编排器
负责数据源管理、多源回退、缓存集成、数据验证
"""

import sys
import os
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime, timezone
import time
import os

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.orchestration.cache import DataCache
from backend.orchestration.validator import DataValidator, ValidationResult
from backend.services import CircuitBreaker


@dataclass
class DataSource:
    """数据源定义"""
    name: str
    fetch_func: Callable
    priority: int  # 优先级，数字越小越优先
    rate_limit: int  # 每分钟请求限制
    last_success: Optional[datetime] = None
    consecutive_failures: int = 0
    total_calls: int = 0
    total_successes: int = 0
    cooldown_seconds: int = 0
    last_fail: Optional[datetime] = None


@dataclass
class FetchResult:
    """获取结果"""
    success: bool
    data: Any = None
    source: str = ""
    cached: bool = False
    validation: Optional[ValidationResult] = None
    error: Optional[str] = None
    duration_ms: float = 0
    as_of: Optional[str] = None
    # 新增：辅助可观测性的字段
    fallback_used: bool = False
    tried_sources: List[str] = field(default_factory=list)
    trace: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'success': self.success,
            'data': self.data,
            'source': self.source,
            'cached': self.cached,
            'validation': self.validation.to_dict() if self.validation else None,
            'error': self.error,
            'duration_ms': self.duration_ms,
            'as_of': self.as_of,
            'fallback_used': self.fallback_used,
            'tried_sources': self.tried_sources,
            'trace': self.trace,
        }


class ToolOrchestrator:
    """
    工具编排器
    
    功能：
    - 多数据源管理与优先级排序
    - 智能回退（失败自动切换数据源）
    - 缓存集成（避免重复请求）
    - 数据验证（确保数据质量）
    - 调用统计
    """
    
    def __init__(self, tools_module=None, circuit_breaker: Optional[CircuitBreaker] = None):
        """
        初始化编排器
        
        Args:
            tools_module: 工具模块（如 tools.py），如果不提供则延迟加载
        """
        self.cache = DataCache()
        self.validator = DataValidator()
        self.sources: Dict[str, List[DataSource]] = {}
        self.tools_module = tools_module
        self.circuit_breaker = circuit_breaker or CircuitBreaker(
            failure_threshold=int(os.getenv("CB_FAILURE_THRESHOLD", "3")),
            recovery_timeout=int(os.getenv("CB_RECOVERY_TIMEOUT", "120")),
            half_open_success_threshold=int(os.getenv("CB_HALF_OPEN_SUCCESS", "1")),
        )
        self._stats = {
            'total_requests': 0,
            'cache_hits': 0,
            'fallback_used': 0,
            'total_failures': 0,
            'sources': {},  # name -> {'calls': int, 'success': int, 'fail': int}
        }
        # 健康阈值默认值（可在 _init_sources 时用 ENV 覆盖）
        self.health_fail_rate_threshold = 0.6
        self.health_min_calls = 3
        self.health_skip_seconds = 300
        self.health_latency_threshold_ms = int(os.getenv("PRICE_HEALTH_LATENCY_MS", "5000"))
        
        # 如果提供了工具模块，立即初始化数据源
        if tools_module:
            self._init_sources()
    
    def _init_sources(self):
        """初始化数据源优先级映射"""
        if not self.tools_module:
            return
        
        # 健康阈值（用于跳过坏源 / 动态优先级）
        self.health_fail_rate_threshold = float(os.getenv("PRICE_HEALTH_FAIL_RATE", "0.6"))
        self.health_min_calls = int(os.getenv("PRICE_HEALTH_MIN_CALLS", "3"))
        self.health_skip_seconds = int(os.getenv("PRICE_HEALTH_SKIP_SECONDS", "300"))
        
        def _cfg_int(name: str, default: int) -> int:
            try:
                return int(os.getenv(name, default))
            except Exception:
                return default

        def _is_configured(source_name: str) -> bool:
            key_map = {
                'tiingo': 'TIINGO_API_KEY',
                'iex_cloud': 'IEX_CLOUD_API_KEY',
                'twelve_data': 'TWELVE_DATA_API_KEY',
                'alpha_vantage': 'ALPHA_VANTAGE_API_KEY',
                'finnhub': 'FINNHUB_API_KEY',
            }
            key_attr = key_map.get(source_name)
            if not key_attr:
                return True
            val = getattr(self.tools_module, key_attr, "") if self.tools_module else ""
            return bool(val)
        
        # 从 tools.py 中获取各个数据获取函数
        # 注意：这里使用 getattr 安全获取，避免模块中不存在某函数时报错
        
        # 股价数据源
        self.sources['price'] = []
        price_funcs = [
            ('index_price', getattr(self.tools_module, '_fetch_index_price', None), _cfg_int('PRICE_PRIORITY_INDEX', 1), _cfg_int('PRICE_RATE_INDEX', 10), _cfg_int('PRICE_COOLDOWN_INDEX', 0)),
            ('alpha_vantage', getattr(self.tools_module, '_fetch_with_alpha_vantage', None), _cfg_int('PRICE_PRIORITY_ALPHA', 1), _cfg_int('PRICE_RATE_ALPHA', 5), _cfg_int('PRICE_COOLDOWN_ALPHA', 0)),
            ('finnhub', getattr(self.tools_module, '_fetch_with_finnhub', None), _cfg_int('PRICE_PRIORITY_FINNHUB', 2), _cfg_int('PRICE_RATE_FINNHUB', 60), _cfg_int('PRICE_COOLDOWN_FINNHUB', 0)),
            ('yfinance', getattr(self.tools_module, '_fetch_with_yfinance', None), _cfg_int('PRICE_PRIORITY_YFIN', 3), _cfg_int('PRICE_RATE_YFIN', 30), _cfg_int('PRICE_COOLDOWN_YFIN', 0)),
            ('twelve_data', getattr(self.tools_module, '_fetch_with_twelve_data_price', None), _cfg_int('PRICE_PRIORITY_TWELVEDATA', 4), _cfg_int('PRICE_RATE_TWELVEDATA', 30), _cfg_int('PRICE_COOLDOWN_TWELVEDATA', 0)),
            ('yahoo_scrape', getattr(self.tools_module, '_scrape_yahoo_finance', None), _cfg_int('PRICE_PRIORITY_YAHOO', 5), _cfg_int('PRICE_RATE_YAHOO', 10), _cfg_int('PRICE_COOLDOWN_YAHOO', 0)),
            ('search', getattr(self.tools_module, '_search_for_price', None), _cfg_int('PRICE_PRIORITY_SEARCH', 6), _cfg_int('PRICE_RATE_SEARCH', 30), _cfg_int('PRICE_COOLDOWN_SEARCH', 0)),
        ]
        for name, func, priority, rate_limit, cooldown in price_funcs:
            if func:
                if not _is_configured(name):
                    continue
                self.sources['price'].append(DataSource(name, func, priority, rate_limit, cooldown_seconds=cooldown))
    
    def set_tools_module(self, tools_module):
        """设置工具模块并初始化数据源"""
        self.tools_module = tools_module
        self._init_sources()
    
    def fetch(
        self, 
        data_type: str, 
        ticker: str, 
        force_refresh: bool = False,
        **kwargs
    ) -> FetchResult:
        """
        获取数据，带智能回退
        
        Args:
            data_type: 数据类型（price, company_info, news 等）
            ticker: 股票代码
            force_refresh: 是否强制刷新（忽略缓存）
            **kwargs: 传递给数据源函数的额外参数
            
        Returns:
            FetchResult 获取结果
        """
        self._stats['total_requests'] += 1
        start_time = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()
        
        # 1. 检查缓存（除非强制刷新）
        if not force_refresh:
            cache_key = f"{data_type}:{ticker}"
            cached_data = self.cache.get(cache_key)
            if cached_data is not None:
                self._stats['cache_hits'] += 1
                # cache created_at not stored directly; approximate with current time
                cached_as_of = now_iso
                duration = (time.time() - start_time) * 1000
                return FetchResult(
                    success=True,
                    data=cached_data,
                    source="cache",
                    cached=True,
                    duration_ms=duration,
                    as_of=cached_as_of,
                    fallback_used=False,
                    tried_sources=['cache'],
                    trace={
                        'tried_sources': ['cache'],
                        'duration_ms': duration,
                        'cached': True,
                    },
                )
        
        # 2. 按优先级尝试数据源
        sources = self.sources.get(data_type, [])
        if not sources:
            # 没有配置数据源，尝试直接调用工具模块的函数
            return self._fallback_direct_call(data_type, ticker, start_time)
        
        # 动态排序：按失败率 / 连续失败 / 手工优先级
        def _fail_rate(src: DataSource) -> float:
            if src.total_calls == 0:
                return 0.0
            return 1.0 - (src.total_successes / src.total_calls)
        
        def _latency_penalty(src: DataSource) -> float:
            # 简化：用平均耗时（如果有 trace 中记录的话）; 这里保留接口，暂不改变排序
            return 0.0
        
        now_dt = datetime.now()
        sorted_sources = []
        for src in sources:
            # 健康跳过：达到最小调用数且失败率过高，且仍在 skip 窗口
            fr = _fail_rate(src)
            if (
                src.total_calls >= self.health_min_calls
                and fr >= self.health_fail_rate_threshold
                and src.last_fail
                and (now_dt - src.last_fail).total_seconds() < self.health_skip_seconds
            ):
                continue
            sorted_sources.append((fr, src.consecutive_failures, src.priority, src))
        
        # 如果全部被跳过，退回原列表
        if not sorted_sources:
            sorted_sources = [( _fail_rate(s), s.consecutive_failures, s.priority, s) for s in sources]
        
        sources = [item[3] for item in sorted(sorted_sources, key=lambda x: (x[0], x[1], x[2]))]
        
        tried_sources = []
        last_error = None
        
        for i, source in enumerate(sources):
            # 冷却期跳过
            if source.cooldown_seconds > 0 and source.last_fail:
                elapsed = (datetime.now() - source.last_fail).total_seconds()
                if elapsed < source.cooldown_seconds:
                    continue

            if self.circuit_breaker and not self.circuit_breaker.can_call(source.name):
                tried_sources.append(f"{source.name}(circuit_open)")
                continue

            tried_sources.append(source.name)
            self._stats['sources'].setdefault(source.name, {'calls': 0, 'success': 0, 'fail': 0})
            self._stats['sources'][source.name]['calls'] += 1
            
            try:
                result = self._try_source(source, ticker, **kwargs)
                
                if result is None:
                    source.consecutive_failures += 1
                    source.last_fail = datetime.now()
                    self._stats['total_failures'] += 1
                    self._stats['sources'][source.name]['fail'] += 1
                    if self.circuit_breaker:
                        self.circuit_breaker.record_failure(source.name)
                    continue

                # 3. 验证数据
                validation = self.validator.validate(data_type, result)
                
                if validation.is_valid:
                    # 4. 更新缓存
                    cache_key = f"{data_type}:{ticker}"
                    self.cache.set(cache_key, result, data_type=data_type)
                    
                    # 更新统计
                    source.last_success = datetime.now()
                    source.consecutive_failures = 0
                    source.total_successes += 1
                    self._stats['sources'][source.name]['success'] += 1
                    if self.circuit_breaker:
                        self.circuit_breaker.record_success(source.name)
                    
                    if i > 0:
                        self._stats['fallback_used'] += 1
                    
                    duration = (time.time() - start_time) * 1000
                    return FetchResult(
                        success=True,
                        data=result,
                        source=source.name,
                        cached=False,
                        validation=validation,
                        duration_ms=duration,
                        as_of=now_iso,
                        fallback_used=(i > 0),
                        tried_sources=list(tried_sources),
                        trace={
                            'tried_sources': list(tried_sources),
                            'duration_ms': duration,
                            'validation': validation.to_dict() if validation else None,
                        },
                    )
                else:
                    print(f"[Orchestrator] {source.name} 数据验证失败: {validation.issues}")
                    last_error = f"Validation failed: {validation.issues}"
                    source.consecutive_failures += 1
                    source.last_fail = datetime.now()
                    self._stats['total_failures'] += 1
                    self._stats['sources'][source.name]['fail'] += 1
                    if self.circuit_breaker:
                        self.circuit_breaker.record_failure(source.name)
                
            except Exception as e:
                source.consecutive_failures += 1
                source.last_fail = datetime.now()
                last_error = str(e)
                self._stats['total_failures'] += 1
                self._stats['sources'][source.name]['fail'] += 1
                if self.circuit_breaker:
                    self.circuit_breaker.record_failure(source.name)
                print(f"[Orchestrator] {source.name} 失败: {e}")
                continue
            
            # 短暂延迟，避免请求过快
            time.sleep(0.3)
        duration = (time.time() - start_time) * 1000
        
        return FetchResult(
            success=False,
            error=f"所有数据源均失败: {last_error}",
            source=f"tried: {', '.join(tried_sources)}",
            duration_ms=duration,
            as_of=now_iso,
            fallback_used=(len(tried_sources) > 1),
            tried_sources=list(tried_sources),
            trace={
                'tried_sources': list(tried_sources),
                'duration_ms': duration,
                'error': last_error,
            },
        )
    
    def _try_source(self, source: DataSource, ticker: str, **kwargs) -> Optional[Any]:
        """尝试单个数据源"""
        source.total_calls += 1
        
        try:
            result = source.fetch_func(ticker, **kwargs) if kwargs else source.fetch_func(ticker)
            
            # 检查是否为有效结果
            if result is None:
                return None
            
            if isinstance(result, str):
                # 字符串结果检查错误标记
                if "Error" in result or "error" in result.lower():
                    if "rate limit" in result.lower() or "too many requests" in result.lower():
                        print(f"[Orchestrator] {source.name} 被限速")
                    return None
            
            return result
            
        except Exception as e:
            raise e
    
    def _fallback_direct_call(
        self, 
        data_type: str, 
        ticker: str, 
        start_time: float
    ) -> FetchResult:
        """直接调用工具模块函数（无数据源配置时的回退）"""
        if not self.tools_module:
            return FetchResult(
                success=False,
                error="工具模块未加载",
                duration_ms=(time.time() - start_time) * 1000,
                as_of=datetime.utcnow().isoformat() + "Z",
                fallback_used=False,
                tried_sources=[],
                trace={'error': 'tools_module_not_loaded'},
            )
        
        # 数据类型到函数的映射
        func_map = {
            'price': 'get_stock_price',
            'company_info': 'get_company_info',
            'news': 'get_company_news',
            'sentiment': 'get_market_sentiment',
            'news_sentiment': 'get_news_sentiment',
            'economic_events': 'get_economic_events',
        }
        
        func_name = func_map.get(data_type)
        if not func_name:
            return FetchResult(
                success=False,
                error=f"未知的数据类型: {data_type}",
                duration_ms=(time.time() - start_time) * 1000,
                as_of=datetime.utcnow().isoformat() + "Z",
                fallback_used=False,
                tried_sources=[],
                trace={'error': 'unknown_data_type', 'data_type': data_type},
            )
        
        func = getattr(self.tools_module, func_name, None)
        if not func:
            return FetchResult(
                success=False,
                error=f"工具函数不存在: {func_name}",
                duration_ms=(time.time() - start_time) * 1000,
                as_of=datetime.utcnow().isoformat() + "Z",
                fallback_used=False,
                tried_sources=[],
                trace={'error': 'func_not_found', 'func_name': func_name},
            )
        
        try:
            if data_type in ['sentiment', 'economic_events']:
                result = func()
            else:
                result = func(ticker)
            
            # 验证
            validation = self.validator.validate(data_type, result)
            
            # 缓存
            if validation.is_valid:
                cache_key = f"{data_type}:{ticker}"
                self.cache.set(cache_key, result, data_type=data_type)
            
            duration = (time.time() - start_time) * 1000
            return FetchResult(
                success=validation.is_valid,
                data=result,
                source=f"direct:{func_name}",
                cached=False,
                validation=validation,
                duration_ms=duration,
                as_of=datetime.utcnow().isoformat() + "Z",
                fallback_used=False,
                tried_sources=[f"direct:{func_name}"],
                trace={
                    'tried_sources': [f"direct:{func_name}"],
                    'duration_ms': duration,
                    'validation': validation.to_dict() if validation else None,
                },
            )
            
        except Exception as e:
            return FetchResult(
                success=False,
                error=str(e),
                source=f"direct:{func_name}",
                duration_ms=(time.time() - start_time) * 1000,
                as_of=datetime.utcnow().isoformat() + "Z",
                fallback_used=False,
                tried_sources=[f"direct:{func_name}"],
                trace={'error': str(e), 'tried_sources': [f"direct:{func_name}"]},
            )
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        cache_stats = self.cache.get_stats()
        now_dt = datetime.now()
        
        source_stats = {}
        for data_type, sources in self.sources.items():
            entries = []
            for s in sources:
                cb_state = self.circuit_breaker.get_state(s.name) if self.circuit_breaker else {}
                skip_reason = None

                if cb_state.get("state") == "OPEN":
                    cooldown = int(cb_state.get("cooldown_remaining") or 0)
                    skip_reason = f"circuit_open:{cooldown}s"
                elif cb_state.get("state") == "HALF_OPEN":
                    skip_reason = "circuit_half_open"
                elif s.total_calls >= self.health_min_calls and s.last_fail:
                    fail_rate = 1.0 - (s.total_successes / s.total_calls) if s.total_calls > 0 else 0.0
                    if fail_rate >= self.health_fail_rate_threshold:
                        elapsed = (now_dt - s.last_fail).total_seconds()
                        if elapsed < self.health_skip_seconds:
                            skip_reason = f"high_fail_rate:{fail_rate:.2f};cooldown:{int(self.health_skip_seconds - elapsed)}s"

                entries.append({
                    'name': s.name,
                    'priority': s.priority,
                    'total_calls': s.total_calls,
                    'total_successes': s.total_successes,
                    'consecutive_failures': s.consecutive_failures,
                    'success_rate': f"{s.total_successes / s.total_calls:.1%}" if s.total_calls > 0 else "N/A",
                    'fail_rate': 1.0 - (s.total_successes / s.total_calls) if s.total_calls > 0 else 0.0,
                    'cooldown_remaining': max(0, s.cooldown_seconds - ((now_dt - s.last_fail).total_seconds() if s.last_fail else 0)),
                    'last_fail': s.last_fail.isoformat() if s.last_fail else None,
                    'last_success': s.last_success.isoformat() if s.last_success else None,
                    'skip_reason': skip_reason,
                    'health_score': max(0.0, 1.0 - (1.0 - (s.total_successes / s.total_calls) if s.total_calls > 0 else 0.0)),
                    'circuit_state': cb_state.get("state"),
                    'circuit_cooldown': cb_state.get("cooldown_remaining"),
                    'circuit_can_call': cb_state.get("can_call"),
                })

            source_stats[data_type] = entries
        
        return {
            'orchestrator': self._stats,
            'cache': cache_stats,
            'sources': source_stats,
        }
    
    def reset_stats(self):
        """重置统计"""
        self._stats = {
            'total_requests': 0,
            'cache_hits': 0,
            'fallback_used': 0,
            'total_failures': 0,
            'sources': {},
        }
        for sources in self.sources.values():
            for source in sources:
                source.total_calls = 0
                source.total_successes = 0
                source.consecutive_failures = 0


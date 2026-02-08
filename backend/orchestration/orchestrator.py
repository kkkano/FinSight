# -*- coding: utf-8 -*-
"""
ToolOrchestrator utilities for data source orchestration,
fallback handling, caching, validation, and trace metadata.
"""

import sys
import os
import logging
from typing import Dict, List, Optional, Any, Callable, Union
from dataclasses import dataclass, field
from datetime import datetime, timezone
import time

# 娣诲姞椤圭洰鏍圭洰褰曞埌璺緞
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.orchestration.cache import DataCache
from backend.orchestration.validator import DataValidator, ValidationResult
from backend.orchestration.data_context import DataContextCollector, extract_context_fields
from backend.orchestration.trace_emitter import get_trace_emitter
from backend.services import CircuitBreaker
from backend.metrics import (
    observe_orch_latency,
    increment_cache_hit,
    increment_fallback,
    increment_failure,
)

logger = logging.getLogger(__name__)


@dataclass
class DataSource:
    """Data source definition."""
    name: str
    fetch_func: Callable
    priority: int  # 浼樺厛绾э紝鏁板瓧瓒婂皬瓒婁紭鍏?
    rate_limit: int  # 姣忓垎閽熻姹傞檺鍒?
    last_success: Optional[datetime] = None
    consecutive_failures: int = 0
    total_calls: int = 0
    total_successes: int = 0
    cooldown_seconds: int = 0
    last_fail: Optional[datetime] = None


@dataclass
class FetchResult:
    """鑾峰彇缁撴灉"""
    success: bool
    data: Any = None
    source: str = ""
    cached: bool = False
    validation: Optional[ValidationResult] = None
    error: Optional[str] = None
    duration_ms: float = 0
    as_of: Optional[str] = None
    currency: Optional[str] = None
    adjustment: Optional[str] = None
    data_context: Optional[Dict[str, Any]] = None
    # 鏂板锛氳緟鍔╁彲瑙傛祴鎬х殑瀛楁
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
            'currency': self.currency,
            'adjustment': self.adjustment,
            'data_context': self.data_context,
            'fallback_used': self.fallback_used,
            'tried_sources': self.tried_sources,
            'trace': self.trace,
        }


class ToolOrchestrator:
    """
    Orchestrates multi-source data retrieval with:
    - priority-aware source selection
    - fallback when primary sources fail
    - caching and validation
    - source statistics and trace metadata
    """
    
    def __init__(self, tools_module=None, circuit_breaker: Optional[CircuitBreaker] = None):
        """Initialize orchestrator and optional tool module."""
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
        # 鍋ュ悍闃堝€奸粯璁ゅ€硷紙鍙湪 _init_sources 鏃剁敤 ENV 瑕嗙洊锛?
        self.health_fail_rate_threshold = 0.6
        self.health_min_calls = 3
        self.health_skip_seconds = 300
        self.health_latency_threshold_ms = int(os.getenv("PRICE_HEALTH_LATENCY_MS", "5000"))
        
        # 濡傛灉鎻愪緵浜嗗伐鍏锋ā鍧楋紝绔嬪嵆鍒濆鍖栨暟鎹簮
        if tools_module:
            self._init_sources()
    
    def _init_sources(self):
        """Initialize source priority mappings."""
        if not self.tools_module:
            return
        
        # 鍋ュ悍闃堝€硷紙鐢ㄤ簬璺宠繃鍧忔簮 / 鍔ㄦ€佷紭鍏堢骇锛?
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
        
        # 浠?backend.tools 涓幏鍙栧悇涓暟鎹幏鍙栧嚱鏁?
        # 娉ㄦ剰锛氳繖閲屼娇鐢?getattr 瀹夊叏鑾峰彇锛岄伩鍏嶆ā鍧椾腑涓嶅瓨鍦ㄦ煇鍑芥暟鏃舵姤閿?
        
        # 鑲′环鏁版嵁婧?
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
        """Set tools module and reinitialize sources."""
        self.tools_module = tools_module
        self._init_sources()
    
    def _build_data_context(
        self,
        source: str,
        data: Any,
        as_of: Optional[str],
        ticker: Optional[str] = None,
    ) -> tuple[Optional[str], Optional[str], Optional[str], Dict[str, Any]]:
        resolved_as_of, currency, adjustment = extract_context_fields(data, ticker=ticker)
        if not resolved_as_of:
            resolved_as_of = as_of
        collector = DataContextCollector()
        collector.add(
            source,
            data=data,
            as_of=resolved_as_of,
            currency=currency,
            adjustment=adjustment,
            ticker=ticker,
        )
        return resolved_as_of, currency, adjustment, collector.summarize().to_dict()

    def fetch(
        self, 
        data_type: str, 
        ticker: str, 
        force_refresh: bool = False,
        **kwargs
    ) -> FetchResult:
        """
        鑾峰彇鏁版嵁锛屽甫鏅鸿兘鍥為€€
        
        Args:
            data_type: 鏁版嵁绫诲瀷锛坧rice, company_info, news 绛夛級
            ticker: 鑲＄エ浠ｇ爜
            force_refresh: 鏄惁寮哄埗鍒锋柊锛堝拷鐣ョ紦瀛橈級
            **kwargs: 浼犻€掔粰鏁版嵁婧愬嚱鏁扮殑棰濆鍙傛暟
            
        Returns:
            FetchResult 鑾峰彇缁撴灉
        """
        self._stats['total_requests'] += 1
        start_time = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()
        trace_emitter = get_trace_emitter()

        # 1. 妫€鏌ョ紦瀛橈紙闄ら潪寮哄埗鍒锋柊锛?
        if not force_refresh:
            cache_key = f"{data_type}:{ticker}"
            cached_data = self.cache.get(cache_key)
            if cached_data is not None:
                self._stats['cache_hits'] += 1
                increment_cache_hit(data_type)
                trace_emitter.emit_cache_hit(cache_key, source="orchestrator")
                # cache created_at not stored directly; approximate with current time
                cached_as_of = now_iso
                cached_as_of, currency, adjustment, data_context = self._build_data_context(
                    "cache",
                    cached_data,
                    cached_as_of,
                    ticker=ticker,
                )
                duration = (time.time() - start_time) * 1000
                observe_orch_latency(data_type, duration)
                return FetchResult(
                    success=True,
                    data=cached_data,
                    source="cache",
                    cached=True,
                    duration_ms=duration,
                    as_of=cached_as_of,
                    currency=currency,
                    adjustment=adjustment,
                    data_context=data_context,
                    fallback_used=False,
                    tried_sources=['cache'],
                    trace={
                        'tried_sources': ['cache'],
                        'duration_ms': duration,
                        'cached': True,
                    },
                )
        
        # 2. 鎸変紭鍏堢骇灏濊瘯鏁版嵁婧?
        sources = self.sources.get(data_type, [])
        if not sources:
            # 娌℃湁閰嶇疆鏁版嵁婧愶紝灏濊瘯鐩存帴璋冪敤宸ュ叿妯″潡鐨勫嚱鏁?
            trace_emitter.emit_cache_miss(f"{data_type}:{ticker}", source="orchestrator")
            return self._fallback_direct_call(data_type, ticker, start_time)
        
        # 鍔ㄦ€佹帓搴忥細鎸夊け璐ョ巼 / 杩炵画澶辫触 / 鎵嬪伐浼樺厛绾?
        def _fail_rate(src: DataSource) -> float:
            if src.total_calls == 0:
                return 0.0
            return 1.0 - (src.total_successes / src.total_calls)
        
        def _latency_penalty(src: DataSource) -> float:
            # 绠€鍖栵細鐢ㄥ钩鍧囪€楁椂锛堝鏋滄湁 trace 涓褰曠殑璇濓級; 杩欓噷淇濈暀鎺ュ彛锛屾殏涓嶆敼鍙樻帓搴?
            return 0.0
        
        now_dt = datetime.now()
        sorted_sources = []
        for src in sources:
            # 鍋ュ悍璺宠繃锛氳揪鍒版渶灏忚皟鐢ㄦ暟涓斿け璐ョ巼杩囬珮锛屼笖浠嶅湪 skip 绐楀彛
            fr = _fail_rate(src)
            if (
                src.total_calls >= self.health_min_calls
                and fr >= self.health_fail_rate_threshold
                and src.last_fail
                and (now_dt - src.last_fail).total_seconds() < self.health_skip_seconds
            ):
                continue
            sorted_sources.append((fr, src.consecutive_failures, src.priority, src))
        
        # 濡傛灉鍏ㄩ儴琚烦杩囷紝閫€鍥炲師鍒楄〃
        if not sorted_sources:
            sorted_sources = [( _fail_rate(s), s.consecutive_failures, s.priority, s) for s in sources]
        
        sources = [item[3] for item in sorted(sorted_sources, key=lambda x: (x[0], x[1], x[2]))]
        
        tried_sources = []
        last_error = None

        # 缂撳瓨鏈懡涓紝寮€濮嬪皾璇曟暟鎹簮
        trace_emitter.emit_cache_miss(f"{data_type}:{ticker}", source="orchestrator")

        for i, source in enumerate(sources):
            # 鍐峰嵈鏈熻烦杩?
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

            # 鍙戝皠鏁版嵁婧愯皟鐢ㄥ紑濮嬩簨浠?
            source_start_time = time.time()
            trace_emitter.emit_data_source_query(
                source.name, data_type, ticker=ticker,
                success=True, fallback=(i > 0), tried_sources=list(tried_sources)
            )

            try:
                result = self._try_source(source, ticker, **kwargs)
                source_duration_ms = int((time.time() - source_start_time) * 1000)

                if result is None:
                    source.consecutive_failures += 1
                    source.last_fail = datetime.now()
                    self._stats['total_failures'] += 1
                    self._stats['sources'][source.name]['fail'] += 1
                    if self.circuit_breaker:
                        self.circuit_breaker.record_failure(source.name)
                    increment_failure(data_type, source.name)
                    trace_emitter.emit_data_source_query(
                        source.name, data_type, ticker=ticker,
                        success=False, duration_ms=source_duration_ms,
                        error="empty_result", fallback=(i > 0), tried_sources=list(tried_sources)
                    )
                    continue

                # 3. 楠岃瘉鏁版嵁
                validation = self.validator.validate(data_type, result)
                
                if validation.is_valid:
                    # 4. 鏇存柊缂撳瓨
                    cache_key = f"{data_type}:{ticker}"
                    self.cache.set(cache_key, result, data_type=data_type)
                    trace_emitter.emit_cache_set(cache_key)

                    # 鏇存柊缁熻
                    source.last_success = datetime.now()
                    source.consecutive_failures = 0
                    source.total_successes += 1
                    self._stats['sources'][source.name]['success'] += 1
                    if self.circuit_breaker:
                        self.circuit_breaker.record_success(source.name)

                    if i > 0:
                        self._stats['fallback_used'] += 1
                        increment_fallback(data_type)

                    resolved_as_of, currency, adjustment, data_context = self._build_data_context(
                        source.name,
                        result,
                        now_iso,
                        ticker=ticker,
                    )
                    duration = (time.time() - start_time) * 1000

                    # 鍙戝皠鏁版嵁婧愭垚鍔熶簨浠?
                    trace_emitter.emit_data_source_query(
                        source.name, data_type, ticker=ticker,
                        success=True, duration_ms=source_duration_ms,
                        fallback=(i > 0), tried_sources=list(tried_sources)
                    )

                    observe_orch_latency(data_type, duration)
                    return FetchResult(
                        success=True,
                        data=result,
                        source=source.name,
                        cached=False,
                        validation=validation,
                        duration_ms=duration,
                        as_of=resolved_as_of,
                        currency=currency,
                        adjustment=adjustment,
                        data_context=data_context,
                        fallback_used=(i > 0),
                        tried_sources=list(tried_sources),
                        trace={
                            'tried_sources': list(tried_sources),
                            'duration_ms': duration,
                            'validation': validation.to_dict() if validation else None,
                        },
                    )
                else:
                    logger.info(f"[Orchestrator] {source.name} 鏁版嵁楠岃瘉澶辫触: {validation.issues}")
                    last_error = f"Validation failed: {validation.issues}"
                    source.consecutive_failures += 1
                    source.last_fail = datetime.now()
                    self._stats['total_failures'] += 1
                    self._stats['sources'][source.name]['fail'] += 1
                    if self.circuit_breaker:
                        self.circuit_breaker.record_failure(source.name)
                    increment_failure(data_type, source.name)
                    trace_emitter.emit_data_source_query(
                        source.name, data_type, ticker=ticker,
                        success=False, duration_ms=source_duration_ms,
                        error=f"楠岃瘉澶辫触: {validation.issues}", fallback=(i > 0), tried_sources=list(tried_sources)
                    )

            except Exception as e:
                source_duration_ms = int((time.time() - source_start_time) * 1000)
                source.consecutive_failures += 1
                source.last_fail = datetime.now()
                last_error = str(e)
                self._stats['total_failures'] += 1
                self._stats['sources'][source.name]['fail'] += 1
                if self.circuit_breaker:
                    self.circuit_breaker.record_failure(source.name)
                increment_failure(data_type, source.name)
                trace_emitter.emit_data_source_query(
                    source.name, data_type, ticker=ticker,
                    success=False, duration_ms=source_duration_ms,
                    error=str(e), fallback=(i > 0), tried_sources=list(tried_sources)
                )
                logger.info(f"[Orchestrator] {source.name} 澶辫触: {e}")
                continue
            
            # 鐭殏寤惰繜锛岄伩鍏嶈姹傝繃蹇?
            time.sleep(0.3)
        duration = (time.time() - start_time) * 1000
        observe_orch_latency(data_type, duration)
        
        cache_key = f"{data_type}:{ticker}"
        if self._should_negative_cache(last_error):
            negative_ttl = int(os.getenv("CACHE_NEGATIVE_TTL", "60"))
            self.cache.set_negative(
                cache_key,
                reason=f"{data_type} not found: {last_error}",
                ttl=negative_ttl,
            )

        return FetchResult(
            success=False,
            error=f"鎵€鏈夋暟鎹簮鍧囧け璐? {last_error}",
            source=f"tried: {', '.join(tried_sources)}",
            duration_ms=duration,
            as_of=now_iso,
            currency=None,
            adjustment=None,
            data_context=None,
            fallback_used=(len(tried_sources) > 1),
            tried_sources=list(tried_sources),
            trace={
                'tried_sources': list(tried_sources),
                'duration_ms': duration,
                'error': last_error,
            },
        )

    def _should_negative_cache(self, error: Optional[str]) -> bool:
        if not error:
            return False
        lower = error.lower()
        tokens = [
            "not found",
            "invalid",
            "unknown",
            "no data",
            "no results",
            "symbol",
            "404",
        ]
        return any(token in lower for token in tokens)

    def _try_source(self, source: DataSource, ticker: str, **kwargs) -> Optional[Any]:
        """Try fetching from a single source."""
        source.total_calls += 1
        
        try:
            result = source.fetch_func(ticker, **kwargs) if kwargs else source.fetch_func(ticker)
            
            # 妫€鏌ユ槸鍚︿负鏈夋晥缁撴灉
            if result is None:
                return None
            
            if isinstance(result, str):
                # 瀛楃涓茬粨鏋滄鏌ラ敊璇爣璁?
                if "Error" in result or "error" in result.lower():
                    if "rate limit" in result.lower() or "too many requests" in result.lower():
                        logger.info(f"[Orchestrator] {source.name} rate limited")
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
        """
        Direct tool fallback when no data sources are configured.
        """
        fallback_as_of = datetime.utcnow().isoformat() + "Z"
        if not self.tools_module:
            duration = (time.time() - start_time) * 1000
            observe_orch_latency(data_type, duration)
            return FetchResult(
                success=False,
                error="tools_module_not_loaded",
                duration_ms=duration,
                as_of=fallback_as_of,
                currency=None,
                adjustment=None,
                data_context=None,
                fallback_used=False,
                tried_sources=[],
                trace={'error': 'tools_module_not_loaded'},
            )

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
            duration = (time.time() - start_time) * 1000
            observe_orch_latency(data_type, duration)
            return FetchResult(
                success=False,
                error=f"unknown_data_type:{data_type}",
                duration_ms=duration,
                as_of=fallback_as_of,
                currency=None,
                adjustment=None,
                data_context=None,
                fallback_used=False,
                tried_sources=[],
                trace={'error': 'unknown_data_type', 'data_type': data_type},
            )

        func = getattr(self.tools_module, func_name, None)
        if not func:
            duration = (time.time() - start_time) * 1000
            observe_orch_latency(data_type, duration)
            return FetchResult(
                success=False,
                error=f"tool_function_not_found:{func_name}",
                duration_ms=duration,
                as_of=fallback_as_of,
                currency=None,
                adjustment=None,
                data_context=None,
                fallback_used=False,
                tried_sources=[],
                trace={'error': 'func_not_found', 'func_name': func_name},
            )

        try:
            if data_type in ['sentiment', 'economic_events']:
                result = func()
            else:
                result = func(ticker)

            validation = self.validator.validate(data_type, result)

            if validation.is_valid:
                cache_key = f"{data_type}:{ticker}"
                self.cache.set(cache_key, result, data_type=data_type)

            resolved_as_of, currency, adjustment, data_context = self._build_data_context(
                f"direct:{func_name}",
                result,
                fallback_as_of,
                ticker=ticker,
            )
            duration = (time.time() - start_time) * 1000
            observe_orch_latency(data_type, duration)
            return FetchResult(
                success=validation.is_valid,
                data=result,
                source=f"direct:{func_name}",
                cached=False,
                validation=validation,
                duration_ms=duration,
                as_of=resolved_as_of,
                currency=currency,
                adjustment=adjustment,
                data_context=data_context,
                fallback_used=False,
                tried_sources=[f"direct:{func_name}"],
                trace={
                    'tried_sources': [f"direct:{func_name}"],
                    'duration_ms': duration,
                    'validation': validation.to_dict() if validation else None,
                },
            )

        except Exception as e:
            duration = (time.time() - start_time) * 1000
            observe_orch_latency(data_type, duration)
            return FetchResult(
                success=False,
                error=str(e),
                source=f"direct:{func_name}",
                duration_ms=duration,
                as_of=fallback_as_of,
                currency=None,
                adjustment=None,
                data_context=None,
                fallback_used=False,
                tried_sources=[f"direct:{func_name}"],
                trace={'error': str(e), 'tried_sources': [f"direct:{func_name}"]},
            )

    def get_stats(self) -> Dict[str, Any]:
        """鑾峰彇缁熻淇℃伅"""
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
        """閲嶇疆缁熻"""
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




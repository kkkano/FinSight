# -*- coding: utf-8 -*-
"""
DataCache - 智能数据缓存模块
负责缓存 API 响应，减少重复请求
"""

from typing import Any, Optional, Dict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import threading


@dataclass
class CacheEntry:
    """缓存条目"""
    data: Any
    created_at: datetime
    ttl_seconds: int
    hits: int = 0
    
    def is_expired(self) -> bool:
        """检查是否过期"""
        return datetime.now() > self.created_at + timedelta(seconds=self.ttl_seconds)


class DataCache:
    """
    数据缓存类
    
    功能：
    - TTL 过期机制
    - 线程安全
    - 缓存命中统计
    """
    
    # 默认 TTL 配置（秒）
    DEFAULT_TTL = {
        'price': 60,           # 股价：1分钟
        'company_info': 86400, # 公司信息：24小时
        'news': 1800,          # 新闻：30分钟
        'financials': 86400,   # 财务数据：24小时
        'sentiment': 3600,     # 情绪指数：1小时
        'default': 300,        # 默认：5分钟
    }
    
    def __init__(self):
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = threading.RLock()
        self._stats = {
            'hits': 0,
            'misses': 0,
        }
    
    def get(self, key: str) -> Optional[Any]:
        """
        获取缓存数据
        
        Args:
            key: 缓存键（如 "price:AAPL"）
            
        Returns:
            缓存的数据，如果不存在或已过期返回 None
        """
        with self._lock:
            entry = self._cache.get(key)
            
            if entry is None:
                self._stats['misses'] += 1
                return None
            
            if entry.is_expired():
                # 过期，删除并返回 None
                del self._cache[key]
                self._stats['misses'] += 1
                return None
            
            # 命中
            entry.hits += 1
            self._stats['hits'] += 1
            return entry.data
    
    def set(self, key: str, data: Any, ttl: Optional[int] = None, data_type: str = 'default') -> None:
        """
        设置缓存数据
        
        Args:
            key: 缓存键
            data: 要缓存的数据
            ttl: 过期时间（秒），如果不指定则根据 data_type 使用默认值
            data_type: 数据类型，用于确定默认 TTL
        """
        if ttl is None:
            ttl = self.DEFAULT_TTL.get(data_type, self.DEFAULT_TTL['default'])
        
        with self._lock:
            self._cache[key] = CacheEntry(
                data=data,
                created_at=datetime.now(),
                ttl_seconds=ttl
            )
    
    def delete(self, key: str) -> bool:
        """删除缓存"""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False
    
    def clear(self) -> None:
        """清空所有缓存"""
        with self._lock:
            self._cache.clear()
    
    def cleanup_expired(self) -> int:
        """清理过期缓存，返回清理的数量"""
        with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items() 
                if entry.is_expired()
            ]
            for key in expired_keys:
                del self._cache[key]
            return len(expired_keys)
    
    def get_stats(self) -> Dict[str, Any]:
        """获取缓存统计信息"""
        with self._lock:
            total = self._stats['hits'] + self._stats['misses']
            hit_rate = self._stats['hits'] / total if total > 0 else 0.0
            
            return {
                'hits': self._stats['hits'],
                'misses': self._stats['misses'],
                'hit_rate': f"{hit_rate:.2%}",
                'size': len(self._cache),
            }
    
    def __contains__(self, key: str) -> bool:
        """支持 'key in cache' 语法"""
        with self._lock:
            entry = self._cache.get(key)
            return entry is not None and not entry.is_expired()
    
    def __len__(self) -> int:
        """返回缓存大小"""
        return len(self._cache)


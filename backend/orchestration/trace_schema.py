# -*- coding: utf-8 -*-
"""
TraceEvent Schema v1 - 统一可观测性事件格式
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Any, Dict, List, Optional
from enum import Enum


class TraceEventType(str, Enum):
    """标准事件类型"""
    # Agent 生命周期
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    # 搜索相关
    SEARCH_START = "search_start"
    SEARCH_RESULT = "search_result"
    # 反思循环
    REFLECTION_GAP = "reflection_gap"
    REFLECTION_SEARCH = "reflection_search"
    # 收敛相关
    CONVERGENCE_CHECK = "convergence_check"
    CONVERGENCE_STOP = "convergence_stop"
    # 摘要
    SUMMARY_INIT = "summary_init"
    SUMMARY_UPDATE = "summary_update"
    # 通用
    STEP = "step"
    ERROR = "error"


@dataclass
class TraceEvent:
    """
    TraceEvent Schema v1
    统一的可观测性事件格式
    """
    schema_version: str = "v1"
    event_type: str = ""
    timestamp: str = ""
    duration_ms: Optional[int] = None
    agent: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TraceEvent":
        return cls(
            schema_version=data.get("schema_version", "v1"),
            event_type=data.get("event_type", data.get("stage", "step")),
            timestamp=data.get("timestamp", ""),
            duration_ms=data.get("duration_ms"),
            agent=data.get("agent", ""),
            metadata=data.get("metadata", data.get("data", {})),
        )


def create_trace_event(
    event_type: str,
    agent: str = "",
    duration_ms: Optional[int] = None,
    **metadata
) -> Dict[str, Any]:
    """创建标准 trace 事件"""
    return TraceEvent(
        event_type=event_type,
        agent=agent,
        duration_ms=duration_ms,
        metadata=metadata,
    ).to_dict()


def normalize_to_v1(raw: Any, agent_name: str = "") -> List[Dict[str, Any]]:
    """将旧格式 trace 转换为 v1 schema"""
    if not raw:
        return []

    items: List[Any] = raw if isinstance(raw, list) else [raw]
    normalized: List[Dict[str, Any]] = []

    for item in items:
        if not isinstance(item, dict):
            item = {"message": str(item)}

        # 提取事件类型（兼容多种字段名）
        event_type = (
            item.get("event_type") or
            item.get("event") or
            item.get("stage") or
            item.get("type") or
            "step"
        )

        # 提取元数据（兼容多种字段名）
        metadata = item.get("metadata") or item.get("data") or item.get("payload") or {}
        if not isinstance(metadata, dict):
            metadata = {"value": metadata}

        # 移除已提取的字段，剩余作为额外元数据
        skip_keys = {"event_type", "event", "stage", "type", "timestamp",
                     "duration_ms", "duration", "metadata", "data", "payload",
                     "schema_version", "agent"}
        extra = {k: v for k, v in item.items() if k not in skip_keys}
        metadata.update(extra)

        normalized.append(TraceEvent(
            event_type=event_type,
            timestamp=item.get("timestamp") or datetime.now().isoformat(),
            duration_ms=item.get("duration_ms") or item.get("duration"),
            agent=item.get("agent") or agent_name,
            metadata=metadata,
        ).to_dict())

    return normalized

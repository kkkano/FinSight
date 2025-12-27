# -*- coding: utf-8 -*-
"""
ReportIR (Intermediate Representation) - 研报中间表示层
定义深度研报的标准数据结构，用于前后端解耦和结构化渲染。
"""

from typing import List, Optional, Dict, Any, Literal
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

class Sentiment(str, Enum):
    BULLISH = "bullish"   # 看涨
    BEARISH = "bearish"   # 看跌
    NEUTRAL = "neutral"   # 中性

class ContentType(str, Enum):
    TEXT = "text"
    CHART = "chart"
    TABLE = "table"
    IMAGE = "image"

@dataclass
class Citation:
    """引用来源"""
    source_id: str          # 引用ID (e.g., "1", "ref-1")
    title: str              # 来源标题
    url: str                # 链接
    snippet: str            # 摘录片段
    published_date: str     # 发布日期

@dataclass
class ReportContent:
    """报告内容块"""
    type: ContentType
    content: Any            # 文本字符串、图表配置字典、或表格数据
    citation_refs: List[str] = field(default_factory=list) # 关联的引用ID列表 (e.g., ["1", "3"])
    metadata: Dict[str, Any] = field(default_factory=dict) # 额外元数据 (样式、图表类型等)

@dataclass
class ReportSection:
    """报告章节"""
    title: str
    order: int
    contents: List[ReportContent]
    subsections: List['ReportSection'] = field(default_factory=list)
    is_collapsible: bool = True
    default_collapsed: bool = False

@dataclass
class ReportIR:
    """完整研报对象"""
    report_id: str
    ticker: str
    company_name: str
    title: str
    summary: str            # 核心观点摘要
    sentiment: Sentiment    # 整体情绪
    confidence_score: float # AI置信度 (0.0 - 1.0)

    sections: List[ReportSection]
    citations: List[Citation]

    generated_at: str = field(default_factory=lambda: datetime.now().isoformat())
    meta: Dict[str, Any] = field(default_factory=dict) # 耗时、模型版本、Agent轨迹等

    def to_dict(self) -> Dict[str, Any]:
        """序列化为字典，供 API 返回"""
        # 简单递归序列化实现
        return _dataclass_to_dict(self)

def _dataclass_to_dict(obj):
    if isinstance(obj, list):
        return [_dataclass_to_dict(item) for item in obj]
    if hasattr(obj, "__dataclass_fields__"):
        return {k: _dataclass_to_dict(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, Enum):
        return obj.value
    return obj

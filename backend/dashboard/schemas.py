"""
Dashboard Pydantic V2 Schema

定义 Dashboard 所有数据模型，与前端 types/dashboard.ts 一一对应。
"""
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Literal, Optional


class ActiveAsset(BaseModel):
    """
    当前激活资产

    用于标识用户当前查看的资产，包含代码、类型和显示名称。
    """
    symbol: str = Field(..., description="标准化代码")
    type: Literal["equity", "index", "etf", "crypto", "portfolio"] = Field(
        ..., description="资产类型"
    )
    display_name: str = Field(..., description="显示名称")


class Capabilities(BaseModel):
    """
    仪表盘能力集 - 决定前端渲染哪些组件

    根据资产类型，不同组件会被启用或禁用。
    例如：equity 显示 revenue_trend，index 显示 sector_weights。
    """
    revenue_trend: bool = Field(False, description="营收趋势图")
    segment_mix: bool = Field(False, description="分部收入饼图")
    sector_weights: bool = Field(False, description="行业权重饼图")
    top_constituents: bool = Field(False, description="成分股排行")
    holdings: bool = Field(False, description="持仓明细")
    market_chart: bool = Field(True, description="K线/折线图")


class WatchItem(BaseModel):
    """
    自选列表条目

    用于 watchlist 中的每一项，包含基本标识信息。
    """
    symbol: str = Field(..., description="代码")
    type: str = Field("equity", description="资产类型")
    name: str = Field("", description="显示名称")


class LayoutPrefs(BaseModel):
    """
    布局偏好

    用于保存用户的组件显示偏好，支持隐藏和排序。
    """
    hidden_widgets: List[str] = Field(default_factory=list, description="隐藏的组件 ID")
    order: List[str] = Field(default_factory=list, description="组件排序")


class NewsModeConfig(BaseModel):
    """
    新闻模式配置

    - market: 全市场新闻 7x24
    - impact: 与当前资产相关的影响新闻
    """
    mode: Literal["market", "impact"] = Field("market", description="新闻模式")


class DashboardState(BaseModel):
    """
    Dashboard 完整状态

    包含所有影响 Dashboard 渲染的状态信息。
    """
    active_asset: ActiveAsset
    capabilities: Capabilities
    watchlist: List[WatchItem]
    layout_prefs: LayoutPrefs
    news_mode: NewsModeConfig
    debug: Dict[str, Any] = Field(default_factory=dict)


class SnapshotData(BaseModel):
    """
    KPI 快照

    根据资产类型，不同字段会被填充：
    - equity: revenue, eps, gross_margin, fcf
    - index: index_level
    - etf: nav
    - crypto: index_level
    """
    revenue: Optional[float] = None
    eps: Optional[float] = None
    gross_margin: Optional[float] = None
    fcf: Optional[float] = None
    index_level: Optional[float] = None
    nav: Optional[float] = None


class NewsItem(BaseModel):
    """
    新闻条目

    单条新闻的结构化表示。
    """
    title: str
    url: str = ""
    source: str = ""
    ts: str = ""
    summary: str = ""


class DashboardData(BaseModel):
    """
    Dashboard 聚合数据

    包含所有展示数据：KPI 快照、图表数据、新闻列表。
    news 内部包含 ranked list (market/impact) 和 ranking_meta dict，
    因此类型为 Dict[str, Any] 而非严格的 Dict[str, List[...]]。
    """
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    charts: Dict[str, Any] = Field(default_factory=dict)
    news: Dict[str, Any] = Field(default_factory=dict)


class DashboardResponse(BaseModel):
    """
    Dashboard API 响应

    成功响应的标准格式。
    """
    success: bool = True
    state: DashboardState
    data: DashboardData


class DashboardErrorDetail(BaseModel):
    """
    错误详情

    结构化错误信息，便于前端处理和展示。
    """
    code: int = Field(..., description="错误码")
    message: str = Field(..., description="错误描述")
    details: Dict[str, Any] = Field(default_factory=dict)


class DashboardErrorResponse(BaseModel):
    """
    Dashboard 错误响应

    错误响应的标准格式。
    """
    success: bool = False
    error: DashboardErrorDetail

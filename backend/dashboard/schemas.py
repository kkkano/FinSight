"""
Dashboard Pydantic V2 Schema

定义 Dashboard 所有数据模型，与前端 types/dashboard.ts 一一对应。
Contract version: dashboard.data.v2
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


# ── Dashboard Data v2 新增模型 ────────────────────────────────


class ValuationData(BaseModel):
    """估值指标 (v2 新增)"""
    market_cap: Optional[float] = None
    trailing_pe: Optional[float] = None
    forward_pe: Optional[float] = None
    price_to_book: Optional[float] = None
    price_to_sales: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    dividend_yield: Optional[float] = None
    beta: Optional[float] = None
    week52_high: Optional[float] = None
    week52_low: Optional[float] = None


class FinancialStatement(BaseModel):
    """财务报表结构化 (v2 新增)"""
    periods: List[str] = Field(default_factory=list, description="e.g. ['2024Q4','2024Q3',...]")
    revenue: List[Optional[float]] = Field(default_factory=list)
    gross_profit: List[Optional[float]] = Field(default_factory=list)
    operating_income: List[Optional[float]] = Field(default_factory=list)
    net_income: List[Optional[float]] = Field(default_factory=list)
    eps: List[Optional[float]] = Field(default_factory=list)
    total_assets: List[Optional[float]] = Field(default_factory=list)
    total_liabilities: List[Optional[float]] = Field(default_factory=list)
    operating_cash_flow: List[Optional[float]] = Field(default_factory=list)
    free_cash_flow: List[Optional[float]] = Field(default_factory=list)


class TechnicalIndicator(BaseModel):
    """单个技术指标"""
    name: str
    value: Optional[float] = None
    signal: Optional[str] = None  # "buy" | "sell" | "neutral"


class TechnicalData(BaseModel):
    """技术面指标 (v2 新增)"""
    close: Optional[float] = None
    trend: Optional[str] = None  # "bullish" | "bearish" | "neutral"
    momentum: Optional[str] = None

    # 移动平均线
    ma5: Optional[float] = None
    ma10: Optional[float] = None
    ma20: Optional[float] = None
    ma50: Optional[float] = None
    ma100: Optional[float] = None
    ma200: Optional[float] = None
    ema12: Optional[float] = None
    ema26: Optional[float] = None

    # 振荡器
    rsi: Optional[float] = None
    rsi_state: Optional[str] = None
    macd: Optional[float] = None
    macd_signal: Optional[float] = None
    macd_hist: Optional[float] = None
    stoch_k: Optional[float] = None
    stoch_d: Optional[float] = None
    adx: Optional[float] = None
    cci: Optional[float] = None
    williams_r: Optional[float] = None

    # 布林带
    bollinger_upper: Optional[float] = None
    bollinger_middle: Optional[float] = None
    bollinger_lower: Optional[float] = None

    # 支撑阻力
    support_levels: List[float] = Field(default_factory=list)
    resistance_levels: List[float] = Field(default_factory=list)

    avg_volume: Optional[float] = None


class PeerMetrics(BaseModel):
    """同行单项指标"""
    symbol: str
    name: str = ""
    trailing_pe: Optional[float] = None
    forward_pe: Optional[float] = None
    price_to_book: Optional[float] = None
    ev_to_ebitda: Optional[float] = None
    net_margin: Optional[float] = None
    roe: Optional[float] = None
    revenue_growth: Optional[float] = None
    dividend_yield: Optional[float] = None
    market_cap: Optional[float] = None
    score: Optional[float] = None


class PeerComparisonData(BaseModel):
    """同行对比 (v2 新增)"""
    subject_symbol: str
    peers: List[PeerMetrics] = Field(default_factory=list)


class DashboardData(BaseModel):
    """
    Dashboard 聚合数据 (v2)

    v1 字段: snapshot, charts, news
    v2 新增: valuation, financials, technicals, peers (可空 + fallback_reason)
    """
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    charts: Dict[str, Any] = Field(default_factory=dict)
    news: Dict[str, Any] = Field(default_factory=dict)

    # v2 新增 (HC-1: 可空 + fallback_reason)
    valuation: Optional[ValuationData] = None
    valuation_fallback_reason: Optional[str] = None
    financials: Optional[FinancialStatement] = None
    financials_fallback_reason: Optional[str] = None
    technicals: Optional[TechnicalData] = None
    technicals_fallback_reason: Optional[str] = None
    peers: Optional[PeerComparisonData] = None
    peers_fallback_reason: Optional[str] = None


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

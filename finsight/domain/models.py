"""
核心领域模型 - 所有业务实体和值对象的定义

设计原则：
1. 不可变性：使用 frozen=True 确保模型不可变
2. 类型安全：严格类型注解
3. 自描述：每个字段都有明确的含义
4. 可序列化：支持 JSON 序列化
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from decimal import Decimal


# ==================== 枚举类型 ====================

class Intent(str, Enum):
    """用户意图分类"""
    STOCK_ANALYSIS = "stock_analysis"       # 深度股票分析
    STOCK_PRICE = "stock_price"             # 股票价格查询
    STOCK_NEWS = "stock_news"               # 股票新闻查询
    COMPANY_INFO = "company_info"           # 公司信息查询
    COMPARE_ASSETS = "compare_assets"       # 资产对比
    MARKET_SENTIMENT = "market_sentiment"   # 市场情绪
    MACRO_EVENTS = "macro_events"           # 宏观经济事件
    HISTORICAL_ANALYSIS = "historical_analysis"  # 历史回撤分析
    GENERAL_SEARCH = "general_search"       # 通用搜索
    UNCLEAR = "unclear"                     # 意图不明确，需追问


class ResponseMode(str, Enum):
    """响应模式"""
    SUMMARY = "summary"   # 简要分析（300-500字）
    DEEP = "deep"         # 深度报告（800+字）


class Recommendation(str, Enum):
    """投资建议"""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


class ErrorCode(str, Enum):
    """错误码"""
    SUCCESS = "success"
    INVALID_INPUT = "invalid_input"
    TICKER_NOT_FOUND = "ticker_not_found"
    DATA_UNAVAILABLE = "data_unavailable"
    RATE_LIMITED = "rate_limited"
    LLM_ERROR = "llm_error"
    TIMEOUT = "timeout"
    INTERNAL_ERROR = "internal_error"


# ==================== 值对象 ====================

@dataclass(frozen=True)
class Evidence:
    """证据/数据来源"""
    source: str                    # 数据来源（如 "Yahoo Finance", "CNN"）
    timestamp: datetime            # 数据获取时间
    raw_data: Optional[str] = None # 原始数据（可选）


@dataclass(frozen=True)
class DataPoint:
    """通用数据点"""
    name: str
    value: Any
    unit: Optional[str] = None
    evidence: Optional[Evidence] = None


@dataclass(frozen=True)
class StockPrice:
    """股票价格数据"""
    ticker: str
    current_price: Decimal
    change: Decimal
    change_percent: Decimal
    currency: str = "USD"
    high_52w: Optional[Decimal] = None
    low_52w: Optional[Decimal] = None
    volume: Optional[int] = None
    market_cap: Optional[Decimal] = None
    pe_ratio: Optional[Decimal] = None
    dividend_yield: Optional[Decimal] = None
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "Yahoo Finance"


@dataclass(frozen=True)
class CompanyInfo:
    """公司基本信息"""
    ticker: str
    name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None
    employees: Optional[int] = None
    headquarters: Optional[str] = None
    ceo: Optional[str] = None
    founded: Optional[str] = None
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "Yahoo Finance"


@dataclass(frozen=True)
class NewsItem:
    """新闻条目"""
    title: str
    summary: Optional[str] = None
    url: Optional[str] = None
    publisher: Optional[str] = None
    published_at: Optional[datetime] = None
    sentiment: Optional[str] = None  # positive, negative, neutral
    relevance_score: Optional[float] = None


@dataclass(frozen=True)
class MarketSentiment:
    """市场情绪数据"""
    fear_greed_index: int          # 0-100
    label: str                     # Extreme Fear, Fear, Neutral, Greed, Extreme Greed
    previous_close: Optional[int] = None
    week_ago: Optional[int] = None
    month_ago: Optional[int] = None
    year_ago: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)
    source: str = "CNN Fear & Greed Index"


@dataclass(frozen=True)
class EconomicEvent:
    """经济事件"""
    date: str
    event: str
    time: Optional[str] = None
    country: str = "US"
    impact: str = "medium"  # low, medium, high
    actual: Optional[str] = None
    forecast: Optional[str] = None
    previous: Optional[str] = None


@dataclass(frozen=True)
class PerformanceMetric:
    """绩效指标"""
    ticker: str
    name: str
    period_return: Decimal
    period: str  # 1d, 1w, 1m, 3m, 6m, 1y, ytd
    volatility: Optional[Decimal] = None
    sharpe_ratio: Optional[Decimal] = None
    max_drawdown: Optional[Decimal] = None


@dataclass(frozen=True)
class PerformanceComparison:
    """资产对比结果"""
    assets: List[PerformanceMetric]
    benchmark: Optional[PerformanceMetric] = None
    period: str = "1y"
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass(frozen=True)
class DrawdownAnalysis:
    """历史回撤分析"""
    ticker: str
    max_drawdown: Decimal
    max_drawdown_date: str
    recovery_days: Optional[int] = None
    current_drawdown: Optional[Decimal] = None
    drawdown_periods: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)


# ==================== 请求/响应模型 ====================

@dataclass(frozen=True)
class ClarifyQuestion:
    """追问问题"""
    question: str
    options: Optional[List[str]] = None
    field_name: str = "unknown"      # 需要补充的字段
    reason: str = "需要更多信息"      # 追问原因


@dataclass(frozen=True)
class RouteDecision:
    """路由决策结果"""
    intent: Intent
    confidence: float               # 0.0 - 1.0
    extracted_params: Dict[str, Any] = field(default_factory=dict)
    missing_fields: List[str] = field(default_factory=list)
    needs_clarification: bool = False
    clarify_question: Optional[ClarifyQuestion] = None


@dataclass(frozen=True)
class AnalysisRequest:
    """分析请求"""
    query: str                          # 用户原始查询
    mode: ResponseMode = ResponseMode.DEEP
    request_id: Optional[str] = None    # 请求追踪 ID
    timestamp: datetime = field(default_factory=datetime.now)

    # 可选的预解析参数
    ticker: Optional[str] = None
    tickers: Optional[List[str]] = None
    intent_hint: Optional[Intent] = None


@dataclass
class AnalysisResult:
    """分析结果（可变，用于逐步填充）"""
    request_id: str
    intent: Intent
    mode: ResponseMode

    # 状态
    success: bool = True
    error_code: ErrorCode = ErrorCode.SUCCESS
    error_message: Optional[str] = None

    # 需要追问
    needs_clarification: bool = False
    clarify_question: Optional[ClarifyQuestion] = None

    # 数据结果
    stock_price: Optional[StockPrice] = None
    company_info: Optional[CompanyInfo] = None
    news_items: List[NewsItem] = field(default_factory=list)
    market_sentiment: Optional[MarketSentiment] = None
    economic_events: List[EconomicEvent] = field(default_factory=list)
    performance_comparison: Optional[PerformanceComparison] = None
    drawdown_analysis: Optional[DrawdownAnalysis] = None

    # 搜索结果
    search_results: List[Dict[str, Any]] = field(default_factory=list)

    # 生成的报告
    report: Optional[str] = None
    report_format: str = "markdown"

    # 元数据
    data_points: List[DataPoint] = field(default_factory=list)
    evidences: List[Evidence] = field(default_factory=list)
    tools_called: List[str] = field(default_factory=list)
    latency_ms: Optional[int] = None
    token_usage: Optional[Dict[str, int]] = None
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 序列化）"""
        return {
            "request_id": self.request_id,
            "intent": self.intent.value,
            "mode": self.mode.value,
            "success": self.success,
            "error_code": self.error_code.value,
            "error_message": self.error_message,
            "needs_clarification": self.needs_clarification,
            "clarify_question": {
                "question": self.clarify_question.question,
                "options": self.clarify_question.options,
                "field_name": self.clarify_question.field_name,
                "reason": self.clarify_question.reason,
            } if self.clarify_question else None,
            "report": self.report,
            "report_format": self.report_format,
            "tools_called": self.tools_called,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp.isoformat(),
        }

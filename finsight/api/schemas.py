"""
API 请求/响应模型 - Pydantic Schema 定义

所有 API 的输入输出都通过这些模型定义，
确保类型安全和自动文档生成。
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


# ==================== 枚举类型 ====================

class ResponseModeEnum(str, Enum):
    """响应模式"""
    SUMMARY = "summary"
    DEEP = "deep"


class ReportFormatEnum(str, Enum):
    """报告格式"""
    MARKDOWN = "markdown"
    HTML = "html"
    TEXT = "text"


# ==================== 请求模型 ====================

class AnalyzeRequest(BaseModel):
    """分析请求"""
    query: str = Field(
        ...,
        min_length=2,
        max_length=1000,
        description="用户查询，如 '分析苹果股票' 或 'AAPL的最新新闻'"
    )
    mode: ResponseModeEnum = Field(
        default=ResponseModeEnum.DEEP,
        description="响应模式：summary(简要) 或 deep(深度)"
    )
    format: ReportFormatEnum = Field(
        default=ReportFormatEnum.MARKDOWN,
        description="报告格式：markdown, html, 或 text"
    )
    ticker: Optional[str] = Field(
        default=None,
        description="可选的股票代码，如提供则跳过意图识别"
    )

    @field_validator('query')
    @classmethod
    def validate_query(cls, v: str) -> str:
        """验证查询内容"""
        v = v.strip()
        if not v:
            raise ValueError('查询内容不能为空')
        return v


class CompareRequest(BaseModel):
    """资产对比请求"""
    tickers: List[str] = Field(
        ...,
        min_length=2,
        max_length=10,
        description="要对比的股票代码列表，至少 2 个"
    )
    period: str = Field(
        default="1y",
        description="对比周期：1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max"
    )
    mode: ResponseModeEnum = Field(
        default=ResponseModeEnum.SUMMARY,
        description="响应模式"
    )


class StockQueryRequest(BaseModel):
    """股票查询请求"""
    ticker: str = Field(
        ...,
        min_length=1,
        max_length=10,
        description="股票代码，如 AAPL, TSLA, BABA"
    )
    mode: ResponseModeEnum = Field(
        default=ResponseModeEnum.SUMMARY,
        description="响应模式"
    )


class ClarifyResponse(BaseModel):
    """用户追问响应"""
    request_id: str = Field(..., description="原始请求 ID")
    answer: str = Field(..., description="用户的回答")
    selected_option: Optional[int] = Field(default=None, description="选择的选项索引（0-based）")


# ==================== 响应模型 ====================

class ClarifyQuestion(BaseModel):
    """追问问题"""
    question: str = Field(..., description="需要向用户追问的问题")
    options: Optional[List[str]] = Field(default=None, description="可选的选项列表")
    field_name: str = Field(..., description="需要补充的字段名")
    reason: str = Field(..., description="追问的原因")


class Evidence(BaseModel):
    """数据来源证据"""
    source: str = Field(..., description="数据来源")
    timestamp: datetime = Field(..., description="数据获取时间")


class StockPriceData(BaseModel):
    """股票价格数据"""
    ticker: str
    current_price: float
    change: float
    change_percent: float
    currency: str = "USD"
    high_52w: Optional[float] = None
    low_52w: Optional[float] = None
    volume: Optional[int] = None
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None


class CompanyInfoData(BaseModel):
    """公司信息"""
    ticker: str
    name: str
    sector: Optional[str] = None
    industry: Optional[str] = None
    description: Optional[str] = None
    website: Optional[str] = None


class NewsItemData(BaseModel):
    """新闻条目"""
    title: str
    summary: Optional[str] = None
    url: Optional[str] = None
    publisher: Optional[str] = None
    published_at: Optional[datetime] = None


class MarketSentimentData(BaseModel):
    """市场情绪数据"""
    fear_greed_index: int
    label: str
    previous_close: Optional[int] = None
    week_ago: Optional[int] = None
    month_ago: Optional[int] = None
    year_ago: Optional[int] = None


class AnalysisResponse(BaseModel):
    """分析响应"""
    success: bool = Field(..., description="请求是否成功")
    request_id: str = Field(..., description="请求追踪 ID")
    intent: str = Field(..., description="识别到的用户意图")
    mode: str = Field(..., description="响应模式")

    # 需要追问
    needs_clarification: bool = Field(default=False, description="是否需要追问")
    clarify_question: Optional[ClarifyQuestion] = Field(default=None, description="追问问题")

    # 报告
    report: Optional[str] = Field(default=None, description="生成的分析报告")
    report_format: str = Field(default="markdown", description="报告格式")

    # 结构化数据（可选）
    stock_price: Optional[StockPriceData] = Field(default=None, description="股票价格数据")
    company_info: Optional[CompanyInfoData] = Field(default=None, description="公司信息")
    news_items: Optional[List[NewsItemData]] = Field(default=None, description="新闻列表")
    market_sentiment: Optional[MarketSentimentData] = Field(default=None, description="市场情绪")

    # 元数据
    tools_called: List[str] = Field(default_factory=list, description="调用的工具列表")
    evidences: List[Evidence] = Field(default_factory=list, description="数据来源")
    latency_ms: Optional[int] = Field(default=None, description="处理延迟（毫秒）")
    timestamp: datetime = Field(default_factory=datetime.now, description="响应时间戳")

    # 错误信息
    error_code: Optional[str] = Field(default=None, description="错误码")
    error_message: Optional[str] = Field(default=None, description="错误信息")


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = Field(..., description="服务状态")
    timestamp: datetime = Field(..., description="检查时间")
    version: str = Field(..., description="API 版本")
    components: Dict[str, str] = Field(default_factory=dict, description="组件状态")


class ErrorResponse(BaseModel):
    """错误响应"""
    success: bool = Field(default=False)
    error_code: str = Field(..., description="错误码")
    error_message: str = Field(..., description="错误信息")
    request_id: Optional[str] = Field(default=None, description="请求 ID")
    timestamp: datetime = Field(default_factory=datetime.now)


# ==================== 转换函数 ====================

def analysis_result_to_response(result, format: str = "markdown") -> AnalysisResponse:
    """
    将 AnalysisResult 转换为 API 响应

    Args:
        result: AnalysisResult 对象
        format: 报告格式

    Returns:
        AnalysisResponse: API 响应对象
    """
    from finsight.domain.models import AnalysisResult as DomainResult

    # 转换股票价格
    stock_price_data = None
    if result.stock_price:
        stock_price_data = StockPriceData(
            ticker=result.stock_price.ticker,
            current_price=float(result.stock_price.current_price),
            change=float(result.stock_price.change),
            change_percent=float(result.stock_price.change_percent),
            currency=result.stock_price.currency,
            high_52w=float(result.stock_price.high_52w) if result.stock_price.high_52w else None,
            low_52w=float(result.stock_price.low_52w) if result.stock_price.low_52w else None,
            volume=result.stock_price.volume,
            market_cap=float(result.stock_price.market_cap) if result.stock_price.market_cap else None,
            pe_ratio=float(result.stock_price.pe_ratio) if result.stock_price.pe_ratio else None,
        )

    # 转换公司信息
    company_info_data = None
    if result.company_info:
        company_info_data = CompanyInfoData(
            ticker=result.company_info.ticker,
            name=result.company_info.name,
            sector=result.company_info.sector,
            industry=result.company_info.industry,
            description=result.company_info.description,
            website=result.company_info.website,
        )

    # 转换新闻
    news_items_data = None
    if result.news_items:
        news_items_data = [
            NewsItemData(
                title=n.title,
                summary=n.summary,
                url=n.url,
                publisher=n.publisher,
                published_at=n.published_at,
            )
            for n in result.news_items
        ]

    # 转换市场情绪
    sentiment_data = None
    if result.market_sentiment:
        sentiment_data = MarketSentimentData(
            fear_greed_index=result.market_sentiment.fear_greed_index,
            label=result.market_sentiment.label,
            previous_close=result.market_sentiment.previous_close,
            week_ago=result.market_sentiment.week_ago,
            month_ago=result.market_sentiment.month_ago,
            year_ago=result.market_sentiment.year_ago,
        )

    # 转换追问
    clarify_question_data = None
    if result.clarify_question:
        clarify_question_data = ClarifyQuestion(
            question=result.clarify_question.question,
            options=result.clarify_question.options,
            field_name=result.clarify_question.field_name,
            reason=result.clarify_question.reason,
        )

    # 转换证据
    evidences_data = [
        Evidence(source=e.source, timestamp=e.timestamp)
        for e in result.evidences
    ]

    return AnalysisResponse(
        success=result.success,
        request_id=result.request_id,
        intent=result.intent.value,
        mode=result.mode.value,
        needs_clarification=result.needs_clarification,
        clarify_question=clarify_question_data,
        report=result.report,
        report_format=format,
        stock_price=stock_price_data,
        company_info=company_info_data,
        news_items=news_items_data,
        market_sentiment=sentiment_data,
        tools_called=result.tools_called,
        evidences=evidences_data,
        latency_ms=result.latency_ms,
        timestamp=result.timestamp,
        error_code=result.error_code.value if result.error_code else None,
        error_message=result.error_message,
    )

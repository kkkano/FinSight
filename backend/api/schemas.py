"""
FinSight API Pydantic Schemas
Pydantic V2 models for request validation and response documentation.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Any, Optional
from datetime import datetime


# ============== Request Models ==============

class ChatMessage(BaseModel):
    """对话消息"""
    role: str = Field(..., description="消息角色: user/assistant")
    content: str = Field(..., description="消息内容")


class ChatRequest(BaseModel):
    """聊天请求"""
    query: str = Field(..., min_length=1, description="用户查询内容")
    session_id: Optional[str] = Field(None, description="会话ID")
    history: Optional[list[ChatMessage]] = Field(None, description="对话历史(最近N轮)")

    model_config = {"extra": "ignore"}


class AnalysisRequest(BaseModel):
    """分析请求"""
    query: str = Field(..., description="分析查询")
    user_id: str = Field("default_user", description="用户ID")


class SubscriptionRequest(BaseModel):
    """订阅请求"""
    email: str = Field(..., min_length=3, description="用户邮箱")
    ticker: str = Field(..., min_length=1, description="股票代码")
    alert_types: Optional[list[str]] = Field(None, description="提醒类型")
    price_threshold: Optional[float] = Field(None, description="价格阈值(%)")

    @field_validator("alert_types", mode="before")
    @classmethod
    def default_alert_types(cls, v):
        return v or ["price_change", "news"]

    @field_validator("alert_types")
    @classmethod
    def validate_alert_types(cls, v):
        allowed = {"price_change", "news", "report"}
        invalid = [x for x in v if x not in allowed]
        if invalid:
            raise ValueError(f"unsupported alert_types: {invalid}")
        return v

    @field_validator("price_threshold")
    @classmethod
    def validate_price_threshold(cls, v):
        if v is not None and v <= 0:
            raise ValueError("price_threshold must be positive")
        return v


class UnsubscribeRequest(BaseModel):
    """取消订阅请求"""
    email: str = Field(..., min_length=3, description="用户邮箱")
    ticker: Optional[str] = Field(None, min_length=1, description="股票代码")


class UserProfileUpdateRequest(BaseModel):
    """用户画像更新请求"""
    user_id: str = Field("default_user", description="用户ID")
    profile: dict[str, Any] = Field(default_factory=dict, description="画像数据")


class WatchlistRequest(BaseModel):
    """关注列表请求"""
    user_id: str = Field("default_user", description="用户ID")
    ticker: str = Field(..., description="股票代码")


class ChartDetectRequest(BaseModel):
    """图表检测请求"""
    query: str = Field(..., description="用户查询")
    ticker: Optional[str] = Field(None, description="股票代码")


class ChartDataRequest(BaseModel):
    """图表数据请求"""
    ticker: str = Field(..., description="股票代码")
    summary: str = Field(..., description="图表数据摘要")


class ConfigRequest(BaseModel):
    """配置保存请求"""
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_api_base: Optional[str] = None
    layout_mode: str = Field("centered", description="布局模式")

    model_config = {"extra": "allow"}


class ExportPdfRequest(BaseModel):
    """PDF导出请求"""
    messages: list[dict[str, Any]] = Field(..., description="对话消息列表")
    charts: list[dict[str, Any]] = Field(default_factory=list, description="图表列表")
    title: str = Field("FinSight 对话记录", description="PDF标题")


# ============== Response Models ==============

class BaseResponse(BaseModel):
    """基础响应"""
    success: bool = Field(..., description="是否成功")


class ErrorResponse(BaseResponse):
    """错误响应"""
    success: bool = False
    error: str = Field(..., description="错误信息")


class ClassificationInfo(BaseModel):
    """意图分类信息"""
    method: Optional[str] = Field(None, description="分类方法")
    confidence: Optional[float] = Field(None, description="置信度")


class ThinkingStep(BaseModel):
    """思考步骤"""
    stage: str = Field(..., description="阶段名称")
    message: str = Field(..., description="阶段描述")
    timestamp: str = Field(..., description="时间戳")
    result: Optional[dict[str, Any]] = Field(None, description="阶段结果")


class ChatResponse(BaseResponse):
    """聊天响应"""
    response: str = Field(..., description="AI回复内容")
    intent: Optional[str] = Field(None, description="识别的意图")
    current_focus: Optional[str] = Field(None, description="当前关注股票")
    response_time_ms: int = Field(0, description="响应时间(ms)")
    session_id: str = Field(..., description="会话ID")
    thinking: list[dict[str, Any]] = Field(default_factory=list, description="思考过程")
    report: Optional[dict[str, Any]] = Field(None, description="报告数据")
    data: Optional[dict[str, Any]] = Field(None, description="附加数据")
    metadata: Optional[dict[str, Any]] = Field(None, description="元数据")
    method: Optional[str] = Field(None, description="处理方法")


class SupervisorResponse(BaseResponse):
    """Supervisor模式响应"""
    response: str = Field(..., description="AI回复内容")
    intent: Optional[str] = Field(None, description="识别的意图")
    classification: Optional[ClassificationInfo] = Field(None, description="分类信息")
    session_id: str = Field(..., description="会话ID")


class ComponentStatus(BaseModel):
    """组件状态"""
    status: str = Field(..., description="状态")
    available: Optional[bool] = None
    reason: Optional[str] = None


class HealthResponse(BaseModel):
    """健康检查响应"""
    status: str = Field(..., description="整体状态")
    components: dict[str, ComponentStatus] = Field(..., description="组件状态")
    timestamp: str = Field(..., description="时间戳")


class RootResponse(BaseModel):
    """根路径响应"""
    status: str = Field(..., description="服务状态")
    message: str = Field(..., description="服务信息")
    timestamp: str = Field(..., description="时间戳")


class DiagnosticsResponse(BaseModel):
    """诊断响应"""
    status: str = Field(..., description="状态")
    data: dict[str, Any] = Field(..., description="诊断数据")
    timestamp: str = Field(..., description="时间戳")


class UserProfileResponse(BaseResponse):
    """用户画像响应"""
    profile: Optional[dict[str, Any]] = Field(None, description="用户画像")


class SubscriptionResponse(BaseResponse):
    """订阅响应"""
    message: str = Field(..., description="操作结果")
    email: str = Field(..., description="邮箱")
    ticker: str = Field(..., description="股票代码")


class SubscriptionListResponse(BaseResponse):
    """订阅列表响应"""
    subscriptions: list[dict[str, Any]] = Field(..., description="订阅列表")
    count: int = Field(..., description="订阅数量")


class StockDataResponse(BaseModel):
    """股票数据响应"""
    ticker: str = Field(..., description="股票代码")
    data: Optional[dict[str, Any]] = Field(None, description="数据")
    cached: bool = Field(False, description="是否来自缓存")
    error: Optional[str] = Field(None, description="错误信息")


class KlineResponse(BaseModel):
    """K线数据响应"""
    ticker: str = Field(..., description="股票代码")
    data: dict[str, Any] = Field(..., description="K线数据")
    cached: bool = Field(False, description="是否来自缓存")


class ConfigResponse(BaseResponse):
    """配置响应"""
    config: dict[str, Any] = Field(..., description="配置数据")


class ChartDetectResponse(BaseResponse):
    """图表检测响应"""
    should_generate: bool = Field(False, description="是否生成图表")
    chart_type: str = Field("none", description="图表类型")
    data_dimension: str = Field("none", description="数据维度")
    confidence: float = Field(0.0, description="置信度")
    reason: str = Field("", description="原因")


class ChartDataResponse(BaseResponse):
    """图表数据响应"""
    message: str = Field(..., description="操作结果")

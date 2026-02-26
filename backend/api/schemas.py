"""
FinSight API Pydantic Schemas
"""

from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from backend.contracts import CHAT_REQUEST_SCHEMA_VERSION, CHAT_RESPONSE_SCHEMA_VERSION


# ==================== Request Models ====================


class ChatMessage(BaseModel):
    role: str = Field(..., description="message role")
    content: str = Field(..., description="message content")


class SelectionContext(BaseModel):
    type: Literal["news", "filing", "doc", "report", "risk", "insight"] = Field(
        ...,
        description="selection type",
    )
    id: str = Field(..., description="selection id")
    title: str = Field(..., description="selection title")
    url: Optional[str] = Field(None, description="selection url")
    source: Optional[str] = Field(None, description="selection source")
    ts: Optional[str] = Field(None, description="selection timestamp")
    snippet: Optional[str] = Field(None, description="selection snippet")

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, v):
        if not isinstance(v, str):
            return v
        lowered = v.strip().lower()
        if lowered == "report":
            return "doc"
        return lowered


class ChatContext(BaseModel):
    active_symbol: Optional[str] = Field(None, description="active symbol")
    view: Optional[str] = Field(None, description="ui view")
    selection: Optional[SelectionContext] = Field(None, description="single selection")
    selections: Optional[list[SelectionContext]] = Field(None, description="multi selection")


class ChatOptions(BaseModel):
    output_mode: Optional[Literal["chat", "brief", "investment_report"]] = Field(
        None,
        description="output mode",
    )
    strict_selection: Optional[bool] = Field(
        None,
        description="strict selection mode",
    )
    confirmation_mode: Optional[Literal["auto", "required", "skip"]] = Field(
        None,
        description="confirmation strategy",
    )
    locale: Optional[str] = Field(None, description="locale")
    trace_raw_override: Optional[Literal["on", "off", "inherit"]] = Field(
        None,
        description="raw trace visibility override",
    )


class ChatRequest(BaseModel):
    schema_version: str = Field(
        default=CHAT_REQUEST_SCHEMA_VERSION,
        description="request schema version",
    )
    query: str = Field(..., min_length=1, description="user query")
    session_id: Optional[str] = Field(None, description="session id")
    history: Optional[list[ChatMessage]] = Field(None, description="conversation history")
    context: Optional[ChatContext] = Field(None, description="ephemeral context")
    options: Optional[ChatOptions] = Field(None, description="request options")

    model_config = {"extra": "ignore"}

    @field_validator("schema_version", mode="before")
    @classmethod
    def normalize_schema_version(cls, v):
        if not isinstance(v, str) or not v.strip():
            return CHAT_REQUEST_SCHEMA_VERSION
        return v.strip()


class AnalysisRequest(BaseModel):
    query: str = Field(..., description="analysis query")
    user_id: str = Field("default_user", description="user id")


class SubscriptionRequest(BaseModel):
    email: str = Field(..., min_length=3, description="email")
    ticker: str = Field(..., min_length=1, description="ticker")
    alert_types: Optional[list[str]] = Field(None, description="alert types")
    price_threshold: Optional[float] = Field(None, description="price threshold")
    risk_threshold: Optional[str] = Field("high", description="risk threshold")

    @field_validator("alert_types", mode="before")
    @classmethod
    def default_alert_types(cls, v):
        return v or ["price_change", "news"]

    @field_validator("alert_types")
    @classmethod
    def validate_alert_types(cls, v):
        allowed = {"price_change", "news", "report", "risk"}
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

    @field_validator("risk_threshold")
    @classmethod
    def validate_risk_threshold(cls, v):
        if v is None:
            return "high"
        normalized = str(v).strip().lower()
        allowed = {"low", "medium", "high", "critical"}
        if normalized not in allowed:
            raise ValueError(f"unsupported risk_threshold: {v}")
        return normalized


class UnsubscribeRequest(BaseModel):
    email: str = Field(..., min_length=3, description="email")
    ticker: Optional[str] = Field(None, min_length=1, description="ticker")


class ToggleSubscriptionRequest(BaseModel):
    email: str = Field(..., min_length=3, description="email")
    ticker: str = Field(..., min_length=1, description="ticker")
    enabled: bool = Field(..., description="enable flag")


class UserProfileUpdateRequest(BaseModel):
    user_id: str = Field("default_user", description="user id")
    profile: dict[str, Any] = Field(default_factory=dict, description="profile payload")


class WatchlistRequest(BaseModel):
    user_id: str = Field("default_user", description="user id")
    ticker: str = Field(..., description="ticker")


class ChartDetectRequest(BaseModel):
    query: str = Field(..., description="query")
    ticker: Optional[str] = Field(None, description="ticker")


class ChartDataRequest(BaseModel):
    ticker: str = Field(..., description="ticker")
    summary: str = Field(..., description="chart summary")


class ConfigRequest(BaseModel):
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_api_base: Optional[str] = None
    llm_endpoints: Optional[list[dict[str, Any]]] = None
    layout_mode: str = Field("centered", description="layout mode")

    model_config = {"extra": "allow"}


class ExportPdfRequest(BaseModel):
    messages: list[dict[str, Any]] = Field(..., description="messages")
    charts: list[dict[str, Any]] = Field(default_factory=list, description="charts")
    title: str = Field("FinSight 对话记录", description="pdf title")


# ==================== Response Models ====================


class BaseResponse(BaseModel):
    success: bool = Field(..., description="success flag")


class ErrorResponse(BaseResponse):
    success: bool = False
    error: str = Field(..., description="error message")


class ClassificationInfo(BaseModel):
    method: Optional[str] = Field(None, description="classification method")
    confidence: Optional[float] = Field(None, description="classification confidence")


class ThinkingStep(BaseModel):
    stage: str = Field(..., description="stage name")
    message: str = Field(..., description="stage message")
    timestamp: str = Field(..., description="timestamp")
    result: Optional[dict[str, Any]] = Field(None, description="stage result")


class ChatResponse(BaseResponse):
    schema_version: str = Field(CHAT_RESPONSE_SCHEMA_VERSION, description="response schema version")
    response: str = Field(..., description="assistant response")
    intent: Optional[str] = Field(None, description="intent")
    current_focus: Optional[str] = Field(None, description="current focus")
    response_time_ms: int = Field(0, description="response time ms")
    session_id: str = Field(..., description="session id")
    thinking: list[dict[str, Any]] = Field(default_factory=list, description="thinking trace")
    report: Optional[dict[str, Any]] = Field(None, description="report payload")
    data: Optional[dict[str, Any]] = Field(None, description="extra data")
    metadata: Optional[dict[str, Any]] = Field(None, description="metadata")
    method: Optional[str] = Field(None, description="execution method")


class SupervisorResponse(BaseResponse):
    schema_version: str = Field(CHAT_RESPONSE_SCHEMA_VERSION, description="response schema version")
    response: str = Field(..., description="assistant response")
    intent: Optional[str] = Field(None, description="intent")
    classification: Optional[ClassificationInfo] = Field(None, description="classification")
    session_id: str = Field(..., description="session id")


class ComponentStatus(BaseModel):
    status: str = Field(..., description="component status")
    available: Optional[bool] = None
    reason: Optional[str] = None


class HealthResponse(BaseModel):
    status: str = Field(..., description="overall status")
    components: dict[str, ComponentStatus] = Field(..., description="components")
    timestamp: str = Field(..., description="timestamp")


class RootResponse(BaseModel):
    status: str = Field(..., description="service status")
    message: str = Field(..., description="service message")
    timestamp: str = Field(..., description="timestamp")


class DiagnosticsResponse(BaseModel):
    status: str = Field(..., description="diagnostics status")
    data: dict[str, Any] = Field(..., description="diagnostics payload")
    timestamp: str = Field(..., description="timestamp")


class UserProfileResponse(BaseResponse):
    profile: Optional[dict[str, Any]] = Field(None, description="user profile")


class SubscriptionResponse(BaseResponse):
    message: str = Field(..., description="operation message")
    email: str = Field(..., description="email")
    ticker: str = Field(..., description="ticker")


class SubscriptionListResponse(BaseResponse):
    subscriptions: list[dict[str, Any]] = Field(..., description="subscriptions")
    count: int = Field(..., description="count")


class StockDataResponse(BaseModel):
    ticker: str = Field(..., description="ticker")
    data: Optional[dict[str, Any]] = Field(None, description="stock data")
    cached: bool = Field(False, description="cached flag")
    error: Optional[str] = Field(None, description="error")


class KlineResponse(BaseModel):
    ticker: str = Field(..., description="ticker")
    data: dict[str, Any] = Field(..., description="kline data")
    cached: bool = Field(False, description="cached flag")


class ConfigResponse(BaseResponse):
    config: dict[str, Any] = Field(..., description="config")


class ChartDetectResponse(BaseResponse):
    should_generate: bool = Field(False, description="should generate chart")
    chart_type: str = Field("none", description="chart type")
    data_dimension: str = Field("none", description="data dimension")
    confidence: float = Field(0.0, description="confidence")
    reason: str = Field("", description="reason")


class ChartDataResponse(BaseResponse):
    message: str = Field(..., description="operation message")

"""Pydantic contracts used by the converged public API."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from backend.contracts import CHAT_REQUEST_SCHEMA_VERSION


class ChatMessage(BaseModel):
    role: str = Field(..., description="message role")
    content: str = Field(..., description="message content")


class SelectionContext(BaseModel):
    type: Literal["news", "filing", "doc", "report", "risk", "insight", "url", "web", "article"]
    id: str
    title: str
    url: str | None = None
    source: str | None = None
    ts: str | None = None
    snippet: str | None = None

    @field_validator("type", mode="before")
    @classmethod
    def normalize_type(cls, value):
        if not isinstance(value, str):
            return value
        normalized = value.strip().lower()
        return "doc" if normalized == "report" else normalized


class ChatContext(BaseModel):
    active_symbol: str | None = None
    view: str | None = None
    source_view: Literal["dashboard", "command_palette"] | None = None
    source_tab: str | None = Field(
        None,
        min_length=1,
        max_length=64,
        pattern=r"^[^\x00-\x1F\x7F]+$",
    )
    selection: SelectionContext | None = None
    selections: list[SelectionContext] | None = None


class ChatOptions(BaseModel):
    output_mode: Literal["chat", "brief", "investment_report"] | None = None
    strict_selection: bool | None = None
    locale: str | None = None
    trace_raw_override: Literal["on", "off", "inherit"] | None = None


class ChatRequest(BaseModel):
    schema_version: str = CHAT_REQUEST_SCHEMA_VERSION
    query: str = Field(..., min_length=1)
    session_id: str | None = None
    history: list[ChatMessage] | None = None
    context: ChatContext | None = None
    options: ChatOptions | None = None

    model_config = {"extra": "ignore"}

    @field_validator("schema_version", mode="before")
    @classmethod
    def normalize_schema_version(cls, value):
        if not isinstance(value, str) or not value.strip():
            return CHAT_REQUEST_SCHEMA_VERSION
        return value.strip()


class StockDataResponse(BaseModel):
    ticker: str
    data: dict | None = None
    cached: bool = False
    error: str | None = None


class KlineResponse(BaseModel):
    ticker: str
    data: dict
    cached: bool = False

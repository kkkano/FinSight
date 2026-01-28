# -*- coding: utf-8 -*-
"""
SchemaToolRouter
Schema-driven tool routing with one LLM call + Pydantic validation.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field

from backend.config.ticker_mapping import (
    COMPANY_MAP,
    CN_TO_TICKER,
    extract_tickers,
)

logger = logging.getLogger(__name__)

try:  # pragma: no cover - import guard
    from langchain_core.messages import SystemMessage, HumanMessage
    LANGCHAIN_AVAILABLE = True
except ImportError:  # pragma: no cover
    LANGCHAIN_AVAILABLE = False


class AnalyzeStock(BaseModel):
    """Deep stock analysis report."""

    ticker: str = Field(..., description="Stock ticker, e.g., AAPL, TSLA")
    timeframe: Optional[str] = Field("1y", description="Time range, e.g., 1d/1w/1m/1y/5y")


class GetPrice(BaseModel):
    """Real-time stock price."""

    ticker: str = Field(..., description="Stock ticker, e.g., AAPL")


class CompareStocks(BaseModel):
    """Compare multiple stocks."""

    tickers: List[str] = Field(..., min_length=2, description="At least 2 stock tickers")


class GetNews(BaseModel):
    """Latest company news."""

    ticker: str = Field(..., description="Stock ticker, e.g., AAPL")
    limit: Optional[int] = Field(5, description="Number of news items")


class GetMarketSentiment(BaseModel):
    """Market sentiment (Fear & Greed)."""

    pass


class GetEconomicEvents(BaseModel):
    """Macro economic calendar."""

    pass


class GetNewsSentiment(BaseModel):
    """News sentiment for a ticker."""

    ticker: str = Field(..., description="Stock ticker, e.g., AAPL")
    limit: Optional[int] = Field(5, description="Number of news items")


class SearchWeb(BaseModel):
    """General search."""

    query: str = Field(..., description="Search query")


class Greeting(BaseModel):
    """Greeting or small talk."""

    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    schema: Type[BaseModel]
    intent: str
    description: str


@dataclass
class SchemaRouteResult:
    intent: str
    metadata: Dict[str, Any]


DEFAULT_TOOL_SPECS: Dict[str, ToolSpec] = {
    "analyze_stock": ToolSpec(
        name="analyze_stock",
        schema=AnalyzeStock,
        intent="report",
        description="Generate a deep stock analysis report",
    ),
    "get_price": ToolSpec(
        name="get_price",
        schema=GetPrice,
        intent="chat",
        description="Fetch real-time stock price",
    ),
    "compare_stocks": ToolSpec(
        name="compare_stocks",
        schema=CompareStocks,
        intent="chat",
        description="Compare multiple stocks",
    ),
    "get_news": ToolSpec(
        name="get_news",
        schema=GetNews,
        intent="chat",
        description="Fetch latest company news",
    ),
    "get_market_sentiment": ToolSpec(
        name="get_market_sentiment",
        schema=GetMarketSentiment,
        intent="chat",
        description="Get market sentiment (Fear & Greed)",
    ),
    "get_economic_events": ToolSpec(
        name="get_economic_events",
        schema=GetEconomicEvents,
        intent="economic_events",
        description="Get macro economic events calendar",
    ),
    "get_news_sentiment": ToolSpec(
        name="get_news_sentiment",
        schema=GetNewsSentiment,
        intent="news_sentiment",
        description="Analyze news sentiment for a ticker",
    ),
    "search": ToolSpec(
        name="search",
        schema=SearchWeb,
        intent="chat",
        description="General web search for queries",
    ),
    "greeting": ToolSpec(
        name="greeting",
        schema=Greeting,
        intent="greeting",
        description="Greeting or small talk",
    ),
}

TOOL_ALIASES = {
    "get_stock_price": "get_price",
    "get_company_news": "get_news",
    "compare": "compare_stocks",
    "market_sentiment": "get_market_sentiment",
    "economic_events": "get_economic_events",
    "news_sentiment": "get_news_sentiment",
}

CLARIFY_TEMPLATES = {
    "ticker": "请提供股票代码，如 AAPL、TSLA（或公司名）。",
    "tickers": "请提供至少两个股票代码，如 AAPL, MSFT。",
    "timeframe": "请提供时间范围，如 1d/1w/1m/1y/5y。",
    "limit": "请提供新闻条数（例如 5）。",
    "query": "请提供你要搜索的内容。",
}


class SchemaToolRouter:
    """Schema-driven routing with one LLM call and deterministic validation."""

    def __init__(
        self,
        llm: Any,
        tool_specs: Optional[Dict[str, ToolSpec]] = None,
        pending_ttl_seconds: int = 600,
    ):
        self.llm = llm
        self.tool_specs = tool_specs or DEFAULT_TOOL_SPECS
        self.tool_names = list(self.tool_specs.keys())
        self.pending_ttl_seconds = pending_ttl_seconds

    def route_query(self, query: str, context: Any) -> Optional[SchemaRouteResult]:
        if not self.llm or not LANGCHAIN_AVAILABLE:
            return None

        pending = getattr(context, "pending_tool_call", None)
        if pending:
            if self._pending_expired(pending, self.pending_ttl_seconds):
                self._clear_pending(context)
            else:
                return self._handle_pending(query, context, pending)

        tool_call = self._call_llm_for_tool(query, context)
        if not tool_call:
            return None

        tool_name = self._normalize_tool_name(tool_call.get("tool_name"))
        args = tool_call.get("args") or {}
        if not isinstance(args, dict):
            args = {}

        if tool_name not in self.tool_specs:
            logger.info(f"[SchemaRouter] Unknown tool from LLM: {tool_name}")
            return None

        spec = self.tool_specs[tool_name]
        missing = self._get_missing_required_fields(spec.schema, args)
        if missing:
            question = self._generate_question(missing)
            pending_payload = {
                "tool_name": tool_name,
                "args": args,
                "missing_fields": missing,
                "created_at": datetime.now(),
            }
            self._set_pending(context, pending_payload)
            metadata = {
                "schema_action": "clarify",
                "schema_tool_name": tool_name,
                "schema_args": args,
                "schema_missing": missing,
                "schema_question": question,
                "raw_query": query,
            }
            return SchemaRouteResult(intent="clarify", metadata=metadata)

        self._clear_pending(context)
        metadata = self._build_execute_metadata(tool_name, args, query)
        return SchemaRouteResult(intent=spec.intent, metadata=metadata)

    def _handle_pending(self, query: str, context: Any, pending: Dict[str, Any]) -> SchemaRouteResult:
        tool_name = pending.get("tool_name")
        args = pending.get("args") or {}
        missing = pending.get("missing_fields") or []
        args = self._fill_missing_args(query, args, missing)
        spec = self.tool_specs.get(tool_name)
        if not spec:
            self._clear_pending(context)
            return SchemaRouteResult(
                intent="clarify",
                metadata={
                    "schema_action": "clarify",
                    "schema_question": "请提供更具体的信息。",
                    "raw_query": query,
                },
            )

        still_missing = self._get_missing_required_fields(spec.schema, args)
        if still_missing:
            question = self._generate_question(still_missing)
            pending_payload = {
                "tool_name": tool_name,
                "args": args,
                "missing_fields": still_missing,
                "created_at": datetime.now(),
            }
            self._set_pending(context, pending_payload)
            metadata = {
                "schema_action": "clarify",
                "schema_tool_name": tool_name,
                "schema_args": args,
                "schema_missing": still_missing,
                "schema_question": question,
                "raw_query": query,
            }
            return SchemaRouteResult(intent="clarify", metadata=metadata)

        self._clear_pending(context)
        metadata = self._build_execute_metadata(tool_name, args, query)
        return SchemaRouteResult(intent=spec.intent, metadata=metadata)

    def _call_llm_for_tool(self, query: str, context: Any) -> Optional[Dict[str, Any]]:
        context_summary = ""
        if context and hasattr(context, "get_summary"):
            context_summary = context.get_summary()

        tool_lines = []
        for spec in self.tool_specs.values():
            schema = spec.schema.model_json_schema()
            required = schema.get("required", [])
            props = schema.get("properties", {})
            arg_desc = []
            for key in props:
                desc = props[key].get("description", "")
                arg_desc.append(f"{key}{' (required)' if key in required else ''}: {desc}".strip())
            args_summary = "; ".join(arg_desc) if arg_desc else "no args"
            tool_lines.append(f"- {spec.name}: {spec.description}. Args: {args_summary}")

        system_prompt = (
            "You are a tool router for a financial assistant.\n"
            "Choose the single best tool from the list below and return JSON ONLY.\n"
            "Output format: {\"tool_name\": \"...\", \"args\": {...}}.\n"
            "If required args are unknown, set them to null.\n"
            "If it is a greeting/small talk, use tool_name=greeting.\n"
            "If user asks to analyze a stock, use analyze_stock.\n"
            "If user asks for price, use get_price.\n"
            "If user asks for news, use get_news.\n"
            "If user asks for sentiment, use get_market_sentiment or get_news_sentiment when ticker-specific.\n"
            "If user asks for economic calendar/events, use get_economic_events.\n"
            "If user asks to compare multiple assets, use compare_stocks.\n"
            "If none fits, use search.\n\n"
            "Available tools:\n"
            + "\n".join(tool_lines)
        )

        user_prompt = (
            f"User Query: {query}\n"
            f"Context Summary: {context_summary}\n"
            "Return JSON only."
        )

        try:
            response = self.llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ])
            content = getattr(response, "content", "")
            payload = self._extract_json_payload(content)
            if not payload:
                return None
            payload["tool_name"] = self._normalize_tool_name(payload.get("tool_name"))
            return payload
        except Exception as exc:
            logger.info(f"[SchemaRouter] LLM tool routing failed: {exc}")
            return None

    @staticmethod
    def _extract_json_payload(text: str) -> Optional[Dict[str, Any]]:
        if not text:
            return None
        cleaned = text.strip()
        cleaned = re.sub(r"^```json", "", cleaned, flags=re.IGNORECASE).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return None
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    @staticmethod
    def _get_missing_required_fields(schema: Type[BaseModel], args: Dict[str, Any]) -> List[Dict[str, str]]:
        missing: List[Dict[str, str]] = []
        for name, field in schema.model_fields.items():
            if not field.is_required():
                continue
            value = args.get(name)
            if value is None or value == "":
                missing.append({"field": name, "description": field.description or name})
                continue
            if isinstance(value, list) and name == "tickers" and len(value) < 2:
                missing.append({"field": name, "description": field.description or name})
        return missing

    def _generate_question(self, missing: List[Dict[str, str]]) -> str:
        field = missing[0]
        name = field.get("field")
        if name in CLARIFY_TEMPLATES:
            return CLARIFY_TEMPLATES[name]
        description = field.get("description") or name
        return f"请提供{description}。"

    @staticmethod
    def _normalize_tool_name(name: Optional[str]) -> str:
        if not name:
            return ""
        cleaned = name.strip()
        if cleaned in TOOL_ALIASES:
            return TOOL_ALIASES[cleaned]
        return cleaned

    @staticmethod
    def _pending_expired(pending: Dict[str, Any], ttl_seconds: int = 600) -> bool:
        created_at = pending.get("created_at")
        if not isinstance(created_at, datetime):
            return False
        return (datetime.now() - created_at) > timedelta(seconds=ttl_seconds)

    @staticmethod
    def _set_pending(context: Any, payload: Dict[str, Any]) -> None:
        if hasattr(context, "set_pending_tool_call"):
            context.set_pending_tool_call(payload)
        else:
            setattr(context, "pending_tool_call", payload)

    @staticmethod
    def _clear_pending(context: Any) -> None:
        if hasattr(context, "clear_pending_tool_call"):
            context.clear_pending_tool_call()
        else:
            setattr(context, "pending_tool_call", None)

    def _build_execute_metadata(self, tool_name: str, args: Dict[str, Any], query: str) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {
            "schema_action": "execute",
            "schema_tool_name": tool_name,
            "schema_args": args,
            "raw_query": query,
        }
        tickers: List[str] = []
        if "ticker" in args and args.get("ticker"):
            tickers = [args["ticker"]]
        elif "tickers" in args and isinstance(args.get("tickers"), list):
            tickers = args["tickers"]
        if tickers:
            metadata["tickers"] = tickers
        return metadata

    def _fill_missing_args(self, query: str, args: Dict[str, Any], missing: List[Dict[str, str]]) -> Dict[str, Any]:
        if not missing:
            return args

        extracted = extract_tickers(query)
        resolved_ticker = self._resolve_ticker_from_metadata(extracted)

        for item in missing:
            name = item.get("field")
            if name == "ticker" and resolved_ticker:
                args["ticker"] = resolved_ticker
            elif name == "tickers":
                tickers = extracted.get("tickers") or []
                if len(tickers) >= 2:
                    args["tickers"] = tickers
            elif name == "timeframe":
                timeframe = self._extract_timeframe(query)
                if timeframe:
                    args["timeframe"] = timeframe
            elif name == "limit":
                limit = self._extract_int(query, min_value=1, max_value=20)
                if limit:
                    args["limit"] = limit
            elif name == "query":
                args["query"] = query.strip()
        return args

    @staticmethod
    def _resolve_ticker_from_metadata(metadata: Dict[str, Any]) -> Optional[str]:
        tickers = metadata.get("tickers") or []
        if tickers:
            return tickers[0]
        for name in metadata.get("company_names") or []:
            if name in CN_TO_TICKER:
                return CN_TO_TICKER[name]
            lower = name.lower()
            if lower in COMPANY_MAP and isinstance(COMPANY_MAP[lower], str):
                return COMPANY_MAP[lower]
        for name in metadata.get("company_mentions") or []:
            if name in CN_TO_TICKER:
                return CN_TO_TICKER[name]
            lower = name.lower()
            if lower in COMPANY_MAP and isinstance(COMPANY_MAP[lower], str):
                return COMPANY_MAP[lower]
        return None

    @staticmethod
    def _extract_timeframe(query: str) -> Optional[str]:
        match = re.search(r"(\d+)\s*(d|w|m|y)", query.lower())
        if match:
            return f"{match.group(1)}{match.group(2)}"
        cn_map = {
            "天": "d",
            "周": "w",
            "星期": "w",
            "月": "m",
            "年": "y",
        }
        for key, suffix in cn_map.items():
            if key in query:
                return f"1{suffix}"
        return None

    @staticmethod
    def _extract_int(query: str, min_value: int = 1, max_value: int = 20) -> Optional[int]:
        match = re.search(r"(\d{1,3})", query)
        if not match:
            return None
        try:
            value = int(match.group(1))
        except Exception:
            return None
        if value < min_value or value > max_value:
            return None
        return value

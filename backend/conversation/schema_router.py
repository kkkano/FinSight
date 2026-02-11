# -*- coding: utf-8 -*-
"""
SchemaToolRouter
Schema-driven tool routing with one LLM call + Pydantic validation.

Flow:
1) LLM returns {tool_name, args, confidence}
2) Clarify if LLM requests or confidence is low
3) Business rules (slot completeness gate)
4) Schema required fields validation
5) Apply defaults and execute
"""

from __future__ import annotations

import json
import logging
import re
import warnings
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, Field, ValidationError

from backend.config.ticker_mapping import (
    COMPANY_MAP,
    CN_TO_TICKER,
    extract_tickers,
)

logger = logging.getLogger(__name__)

_DEPRECATION_WARNED = False


def _warn_deprecated_once() -> None:
    global _DEPRECATION_WARNED
    if _DEPRECATION_WARNED:
        return
    _DEPRECATION_WARNED = True
    warnings.warn(
        "SchemaToolRouter is deprecated; use the LangGraph entry point (backend.graph) instead.",
        DeprecationWarning,
        stacklevel=2,
    )
    logger.warning("[DEPRECATED] SchemaToolRouter is legacy; prefer LangGraph (backend.graph).")

try:  # pragma: no cover - import guard
    from langchain_core.messages import SystemMessage, HumanMessage
    LANGCHAIN_AVAILABLE = True
except ImportError:  # pragma: no cover
    LANGCHAIN_AVAILABLE = False


# ========== Tool Schemas ==========

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


class Clarify(BaseModel):
    """Request clarification from user."""

    reason: Optional[str] = Field(None, description="Why clarification is needed")


# ========== Tool Specifications ==========

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
        description=(
            "Get market sentiment (Fear & Greed Index). "
            "Only use when user explicitly asks about market sentiment, fear & greed, or overall market mood."
        ),
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
    "clarify": ToolSpec(
        name="clarify",
        schema=Clarify,
        intent="clarify",
        description="Request clarification when query is ambiguous or missing key info",
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
    "default": "请提供更具体的信息，以便我更好地帮助您。",
    "low_confidence": "您的问题比较模糊，请提供更多细节。",
}


# ========== Business Rules (Slot Completeness Gate) ==========

class SlotCompletenessGate:
    """
    Business rules for tool selection beyond schema-required fields.
    Return a clarify payload when the tool choice is not appropriate.
    """

    # Action verbs that indicate clear intent
    ACTION_VERBS = [
        # Chinese
        "分析", "研究", "报告", "价格", "股价", "多少钱", "新闻", "消息",
        "比较", "对比", "走势", "行情", "技术", "基本面", "财报", "估值",
        "推荐", "建议", "买", "卖", "持有", "风险", "预测", "趋势",
        "情绪", "恐慌", "贪婪", "宏观", "经济", "事件", "日历",
        # English
        "analyze", "analysis", "report", "price", "news", "compare",
        "technical", "fundamental", "valuation", "recommend", "buy", "sell",
        "hold", "risk", "forecast", "trend", "sentiment", "macro",
    ]

    @staticmethod
    def _is_company_name_only(query: str) -> bool:
        """
        Check if query is just a company name without action verb.
        E.g., "特斯拉", "苹果", "AAPL" should return True.
        """
        query_lower = query.lower().strip()

        # Short query threshold
        if len(query_lower) > 15:
            return False

        # Check for action verbs
        has_action = any(verb in query_lower for verb in SlotCompletenessGate.ACTION_VERBS)
        if has_action:
            return False

        # Check if contains company name or ticker
        extracted = extract_tickers(query)
        if isinstance(extracted, dict):
            has_entity = bool(
                extracted.get("tickers")
                or extracted.get("company_names")
                or extracted.get("company_mentions")
            )
        else:
            has_entity = bool(extracted)

        return has_entity

    @staticmethod
    def validate(tool_name: str, args: Dict[str, Any], query: str) -> Optional[Dict[str, Any]]:
        query_lower = query.lower()

        # Rule 0: Company name only without action → clarify intent
        if SlotCompletenessGate._is_company_name_only(query):
            extracted = extract_tickers(query)
            company = None
            if isinstance(extracted, dict):
                if extracted.get("company_names"):
                    company = extracted["company_names"][0]
                elif extracted.get("tickers"):
                    company = extracted["tickers"][0]
                elif extracted.get("company_mentions"):
                    company = extracted["company_mentions"][0]
            return {
                "should_clarify": True,
                "reason": "company_name_only",
                "question": f"您想对 {company or '这只股票'} 做什么？查价格、看新闻还是深度分析？",
                "missing_fields": [{"field": "intent", "description": "action to perform"}],
            }

        if tool_name == "get_market_sentiment":
            sentiment_indicators = [
                "恐慌", "贪婪", "fear", "greed", "market sentiment", "市场情绪",
                "恐慌指数", "情绪指数", "fear & greed", "fear and greed",
            ]
            has_sentiment_context = any(ind in query_lower for ind in sentiment_indicators)

            analysis_indicators = ["分析", "研究", "报告", "analyze", "analysis", "report"]
            has_analysis_intent = any(ind in query_lower for ind in analysis_indicators)

            if has_analysis_intent and not has_sentiment_context:
                return {
                    "should_clarify": True,
                    "suggested_tool": "analyze_stock",
                    "reason": "analysis_intent_detected",
                    "question": CLARIFY_TEMPLATES["ticker"],
                    "missing_fields": [{"field": "ticker", "description": "Stock ticker"}],
                }

            if not has_sentiment_context:
                return {
                    "should_clarify": True,
                    "reason": "no_sentiment_context",
                    "question": "您是想查询市场恐慌贪婪指数，还是分析某只股票？请明确一下。",
                    "missing_fields": [{"field": "intent", "description": "market sentiment or specific stock"}],
                }

        if tool_name == "analyze_stock":
            ticker = args.get("ticker")
            if not ticker:
                extracted = extract_tickers(query)
                if isinstance(extracted, dict):
                    tickers = extracted.get("tickers", [])
                    company_names = extracted.get("company_names", [])
                else:
                    tickers = extracted
                    company_names = []

                if not tickers and not company_names:
                    return {
                        "should_clarify": True,
                        "reason": "missing_ticker_for_analysis",
                        "question": CLARIFY_TEMPLATES["ticker"],
                        "missing_fields": [{"field": "ticker", "description": "Stock ticker"}],
                    }

        if tool_name == "get_news":
            ticker = args.get("ticker")
            if not ticker:
                extracted = extract_tickers(query)
                tickers = extracted.get("tickers", []) if isinstance(extracted, dict) else extracted
                if not tickers:
                    return {
                        "should_clarify": True,
                        "reason": "missing_ticker_for_news",
                        "question": "请提供您想查看新闻的股票代码或公司名。",
                        "missing_fields": [{"field": "ticker", "description": "Stock ticker"}],
                    }

        if tool_name == "compare_stocks":
            tickers = args.get("tickers", [])
            if not tickers or len(tickers) < 2:
                extracted = extract_tickers(query)
                extracted_tickers = extracted.get("tickers", []) if isinstance(extracted, dict) else extracted
                if len(extracted_tickers) < 2:
                    return {
                        "should_clarify": True,
                        "reason": "insufficient_tickers_for_comparison",
                        "question": CLARIFY_TEMPLATES["tickers"],
                        "missing_fields": [{"field": "tickers", "description": "At least 2 stock tickers"}],
                    }

        return None


# ========== Main Router Class ==========

class SchemaToolRouter:
    """
    Schema-driven routing with confidence scoring and business rules.
    """

    def __init__(
        self,
        llm: Any,
        tool_specs: Optional[Dict[str, ToolSpec]] = None,
        pending_ttl_seconds: int = 600,
        confidence_threshold: float = 0.7,
    ):
        _warn_deprecated_once()
        self.llm = llm
        self.tool_specs = tool_specs or DEFAULT_TOOL_SPECS
        self.pending_ttl_seconds = pending_ttl_seconds
        self.confidence_threshold = confidence_threshold

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
            return self._make_clarify_result(
                query,
                "clarify",
                {},
                [],
                CLARIFY_TEMPLATES["default"],
                "invalid_tool_response",
            )

        tool_name = self._normalize_tool_name(tool_call.get("tool_name"))
        args = tool_call.get("args") or {}
        confidence = tool_call.get("confidence", 0.5)

        if not isinstance(args, dict):
            args = {}

        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.5

        logger.info(f"[SchemaRouter] LLM response: tool={tool_name}, confidence={confidence:.2f}, args={args}")

        if tool_name == "clarify":
            reason = args.get("reason", "llm_uncertain")
            # Use LLM-generated message if available, otherwise fallback to template
            question = args.get("message") or CLARIFY_TEMPLATES["default"]
            return self._make_clarify_result(
                query,
                tool_name,
                args,
                [],
                question,
                reason,
            )

        if confidence < self.confidence_threshold:
            return self._make_clarify_result(
                query,
                tool_name,
                args,
                [],
                CLARIFY_TEMPLATES["low_confidence"],
                "low_confidence",
            )

        if tool_name not in self.tool_specs:
            logger.info(f"[SchemaRouter] Unknown tool from LLM: {tool_name}")
            return self._make_clarify_result(
                query,
                tool_name,
                args,
                [],
                CLARIFY_TEMPLATES["default"],
                "unknown_tool",
            )

        spec = self.tool_specs[tool_name]

        gate_result = SlotCompletenessGate.validate(tool_name, args, query)
        if gate_result and gate_result.get("should_clarify"):
            suggested_tool = gate_result.get("suggested_tool", tool_name)
            question = gate_result.get("question", CLARIFY_TEMPLATES["default"])
            reason = gate_result.get("reason", "business_rule_violation")
            missing_fields = gate_result.get("missing_fields", [])

            pending_payload = {
                "tool_name": suggested_tool,
                "args": args,
                "missing_fields": missing_fields,
                "created_at": datetime.now(),
            }
            self._set_pending(context, pending_payload)

            return self._make_clarify_result(
                query,
                suggested_tool,
                args,
                missing_fields,
                question,
                reason,
            )

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
            return self._make_clarify_result(
                query,
                tool_name,
                args,
                missing,
                question,
                "missing_required_fields",
            )

        self._clear_pending(context)
        args = self._apply_schema_defaults(spec.schema, args)
        metadata = self._build_execute_metadata(tool_name, args, query)
        metadata["confidence"] = confidence
        return SchemaRouteResult(intent=spec.intent, metadata=metadata)

    def _make_clarify_result(
        self,
        query: str,
        tool_name: str,
        args: Dict[str, Any],
        missing: List[Dict[str, str]],
        question: str,
        reason: str,
    ) -> SchemaRouteResult:
        metadata = {
            "schema_action": "clarify",
            "schema_tool_name": tool_name,
            "schema_args": args,
            "schema_missing": missing,
            "schema_question": question,
            "clarify_reason": reason,
            "raw_query": query,
            "source": "schema_router",
        }
        return SchemaRouteResult(intent="clarify", metadata=metadata)

    def _handle_pending(self, query: str, context: Any, pending: Dict[str, Any]) -> SchemaRouteResult:
        tool_name = pending.get("tool_name")
        args = pending.get("args") or {}
        missing = pending.get("missing_fields") or []
        args = self._fill_missing_args(query, args, missing)
        spec = self.tool_specs.get(tool_name)
        if not spec:
            self._clear_pending(context)
            return self._make_clarify_result(
                query,
                "clarify",
                args,
                [],
                CLARIFY_TEMPLATES["default"],
                "unknown_tool",
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
            return self._make_clarify_result(
                query,
                tool_name,
                args,
                still_missing,
                question,
                "still_missing_fields",
            )

        self._clear_pending(context)
        args = self._apply_schema_defaults(spec.schema, args)
        metadata = self._build_execute_metadata(tool_name, args, query)
        return SchemaRouteResult(intent=spec.intent, metadata=metadata)

    def _call_llm_for_tool(self, query: str, context: Any) -> Optional[Dict[str, Any]]:
        context_summary = ""
        if context and hasattr(context, "get_summary"):
            context_summary = context.get_summary()

        tool_lines = "\n".join(
            f"- {s.name}: {s.description}" for s in self.tool_specs.values()
        )

        system_prompt = (
            "你是金融助手工具路由器。仅返回 JSON，禁止任何其他内容。\n"
            '格式: {"tool_name": "...", "args": {...}, "confidence": 0.0-1.0}\n\n'
            "路由规则:\n"
            '- 查询不确定/模糊 → tool_name="clarify", confidence<0.5\n'
            "- 必需参数未知 → 对应值设为 null\n"
            '- "分析股票"但无股票代码 → "clarify"\n'
            '- get_market_sentiment 仅用于明确的"市场情绪/恐慌贪婪/fear & greed"查询\n'
            '- 分析类请求 → 优先路由到 "analyze_stock"\n'
            '- 优先匹配最具体的工具，避免泛化\n\n'
            f"可用工具:\n{tool_lines}"
        )

        user_prompt = (
            f"用户查询: {query}\n"
            f"对话上下文: {context_summary or '无'}\n"
            "仅返回 JSON。"
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

    @staticmethod
    def _apply_schema_defaults(schema: Type[BaseModel], args: Dict[str, Any]) -> Dict[str, Any]:
        try:
            validated = schema(**args)
        except ValidationError:
            return args
        return validated.model_dump()

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
        except ValueError:
            return None
        if value < min_value or value > max_value:
            return None
        return value

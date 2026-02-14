from typing import Any, List, Optional
import os
from datetime import datetime
from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker

class AllSourcesFailedError(Exception):
    pass

class PriceAgent(BaseFinancialAgent):
    AGENT_NAME = "PriceAgent"
    CACHE_TTL = 30  # 30 seconds for real-time price
    MAX_REFLECTIONS = 1  # Enable one reflection round for gap-filling

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        if circuit_breaker is None:
            circuit_breaker = CircuitBreaker(
                failure_threshold=int(os.getenv("PRICE_CB_FAILURE_THRESHOLD", "5")),
                recovery_timeout=float(os.getenv("PRICE_CB_RECOVERY_TIMEOUT", "60")),
                half_open_success_threshold=int(os.getenv("PRICE_CB_HALF_OPEN_SUCCESS", "1")),
            )
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module

    def _get_tool_registry(self) -> dict:
        """PriceAgent tool registry: search only (price data via _initial_search)."""
        registry = {}
        tools = self.tools
        if not tools:
            return registry
        search_fn = getattr(tools, "search", None)
        if search_fn:
            registry["search"] = {
                "func": search_fn,
                "description": "搜索价格相关补充信息（日内/历史对比）",
                "call_with": "query",
            }
        return registry

    async def _initial_search(self, query: str, ticker: str) -> Any:
        cache_key = f"{ticker}:price:realtime"

        # Check cache via the cache service passed in __init__
        # Note: self.cache expected to be the ToolCache or DataCache instance
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        # Multi-source fallback strategy
        # Priority: yfinance -> finnhub -> alpha_vantage -> tavily (via search fallback)
        sources = ["yfinance", "finnhub", "alpha_vantage", "tavily"]

        last_error = None

        for source in sources:
            if self.circuit_breaker.can_call(source):
                try:
                    result = await self._fetch_from_source(source, ticker)
                    if result:
                        self.circuit_breaker.record_success(source)
                        # Cache the result
                        self.cache.set(cache_key, result, self.CACHE_TTL)
                        return result
                except Exception as e:
                    last_error = e
                    self.circuit_breaker.record_failure(source)

        # Fallback to broad search if all APIs fail
        try:
             # Assuming tools module has a search fallback
            # Note: backend.tools usually has _search_for_price but it might be synchronous.
             # In a real async agent, we'd want this to be async or run in executor.
             # For now, we assume _fetch_from_source handles the specific tool call logic.
             fallback_result = await self._fetch_from_source("search", ticker)
             if fallback_result:
                 return fallback_result
        except Exception:
            pass

        raise AllSourcesFailedError(f"All sources failed for {ticker}. Last error: {last_error}")

    async def _fetch_from_source(self, source: str, ticker: str) -> Any:
        # Map source strings to actual tool functions
        tool_func = None
        if source == "yfinance":
            tool_func = getattr(self.tools, "_fetch_with_yfinance", None)
        elif source == "finnhub":
            tool_func = getattr(self.tools, "_fetch_with_finnhub", None)
        elif source == "alpha_vantage":
            tool_func = getattr(self.tools, "_fetch_with_alpha_vantage", None)
        elif source == "tavily" or source == "search":
            tool_func = getattr(self.tools, "_search_for_price", None)

        if tool_func:
            return tool_func(ticker)

        return None

    async def _first_summary(self, data: Any) -> str:
        deterministic = self._deterministic_summary(data)
        analysis = await self._llm_analyze(
            deterministic,
            role="资深量化交易分析师",
            focus="解读当前价格水平和日内变动：波动幅度是否异常、可能反映的市场情绪、与近期趋势的关系，并给出短期方向判断和需要关注的价位。",
        )
        return analysis if analysis else deterministic

    def _deterministic_summary(self, data: Any) -> str:
        """Build a human-readable price snapshot from raw data (fallback)."""
        if isinstance(data, dict):
            ticker = data.get("ticker", "N/A")
            price = data.get("price", "N/A")
            currency = data.get("currency", "USD")
            change_pct = data.get("change_percent") or data.get("change_pct")
            text = f"{ticker} 当前价格: {currency} {price}"
            if change_pct is not None:
                try:
                    pct = float(change_pct)
                    direction = "上涨" if pct >= 0 else "下跌"
                    text += f"，日内{direction} {pct:+.2f}%"
                except (TypeError, ValueError):
                    pass
            return text + "。"
        elif isinstance(data, str) and data:
            return data
        return str(data)

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        # PriceAgent output: raw_data can be dict OR string (from backend.tools)
        # Handle both cases for compatibility

        if isinstance(raw_data, dict):
            # Dict format (structured data)
            price = raw_data.get("price", "N/A")
            currency = raw_data.get("currency", "USD")
            ticker = raw_data.get("ticker", "UNKNOWN")
            source = raw_data.get("source", "yfinance")
            as_of = raw_data.get("as_of", datetime.now().isoformat())
            fallback_used = raw_data.get("fallback_used", False)
            change = raw_data.get("change")
            change_percent = raw_data.get("change_percent")
            if change is None:
                change = raw_data.get("change_abs")
            if change_percent is None:
                change_percent = raw_data.get("change_pct")
            if change_percent is not None:
                try:
                    change_percent = float(change_percent)
                except Exception:
                    change_percent = None
            summary_text = f"{ticker} 当前价格: {currency} {price}。"
            if change_percent is not None:
                direction = "上涨" if change_percent >= 0 else "下跌"
                summary_text += f" 日内变动 {change_percent:+.2f}%（{direction}）。"
            evidence_text = str(raw_data)
            # If upstream _first_summary produced LLM analysis, prefer it
            if isinstance(summary, str) and len(summary) > 150:
                summary_text = summary
        elif isinstance(raw_data, str) and raw_data:
            # String format from backend.tools (e.g., "AAPL Current Price: $150.00 | Change: +$2.00 (+1.5%)")
            summary_text = raw_data
            source = "yfinance"
            as_of = datetime.now().isoformat()
            fallback_used = False
            evidence_text = raw_data
            # Try to extract % change for a richer summary
            try:
                import re
                match = re.search(r"Change:\s*\$[+-]?[0-9.]+\s*\(\s*([+-]?[0-9.]+)%\s*\)", raw_data)
                if match:
                    pct = float(match.group(1))
                    direction = "上涨" if pct >= 0 else "下跌"
                    summary_text = f"{raw_data}。日内变动 {pct:+.2f}%（{direction}）。"
            except Exception:
                pass
        else:
            # Fallback for empty or None
            summary_text = summary or "价格数据获取失败"
            source = "unknown"
            as_of = datetime.now().isoformat()
            fallback_used = True
            evidence_text = str(raw_data) if raw_data else "暂无数据"

        evidence = [
            EvidenceItem(
                text=evidence_text,
                source=source,
                timestamp=as_of
            )
        ]

        # Determine fallback reason for observability
        fallback_reason = None
        if fallback_used:
            if isinstance(raw_data, dict):
                fallback_reason = str(raw_data.get("fallback_detail") or raw_data.get("error") or "primary_source_unavailable")
            else:
                fallback_reason = "no_structured_data"

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary_text,
            evidence=evidence,
            # Price is a direct lookup; treat primary-source success as full confidence.
            confidence=1.0 if not fallback_used else 0.5,
            data_sources=[source],
            as_of=as_of,
            fallback_used=fallback_used,
            fallback_reason=fallback_reason,
            retryable=True,
        )

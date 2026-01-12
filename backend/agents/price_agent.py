from typing import Any, List, Optional
from datetime import datetime
from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker

class AllSourcesFailedError(Exception):
    pass

class PriceAgent(BaseFinancialAgent):
    AGENT_NAME = "PriceAgent"
    CACHE_TTL = 30  # 30 seconds for real-time price
    MAX_REFLECTIONS = 0  # No reflection needed for price

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module

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
             # Note: tools.py usually has _search_for_price but it might be synchronous.
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
        # This is a simplified mapping. In production, this might use the ToolOrchestrator directly.
        # But per design, PriceAgent logic encapsulates this.

        # Note: Since the tools in tools.py are synchronous, we might need to wrap them
        # if this method is strictly async. For this phase, we'll assume direct calls are okay
        # or we wrap them in simple awaits if we had an async executor.

        # Emulating async behavior for the agent structure

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
            # Assuming tool functions take ticker as first arg
            # In a real async loop we might use run_in_executor
            return tool_func(ticker)

        return None

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        # PriceAgent output: raw_data can be dict OR string (from tools.py)
        # Handle both cases for compatibility

        if isinstance(raw_data, dict):
            # Dict format (structured data)
            price = raw_data.get("price", "N/A")
            currency = raw_data.get("currency", "USD")
            ticker = raw_data.get("ticker", "UNKNOWN")
            source = raw_data.get("source", "yfinance")
            as_of = raw_data.get("as_of", datetime.now().isoformat())
            fallback_used = raw_data.get("fallback_used", False)
            summary_text = f"The current price of {ticker} is {currency} {price}."
            evidence_text = str(raw_data)
        elif isinstance(raw_data, str) and raw_data:
            # String format from tools.py (e.g., "AAPL Current Price: $150.00 | Change: +$2.00 (+1.5%)")
            summary_text = raw_data
            source = "yfinance"
            as_of = datetime.now().isoformat()
            fallback_used = False
            evidence_text = raw_data
        else:
            # Fallback for empty or None
            summary_text = summary or "价格数据获取失败"
            source = "unknown"
            as_of = datetime.now().isoformat()
            fallback_used = True
            evidence_text = str(raw_data) if raw_data else "No data"

        evidence = [
            EvidenceItem(
                text=evidence_text,
                source=source,
                timestamp=as_of
            )
        ]

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary_text,
            evidence=evidence,
            confidence=0.9 if not fallback_used else 0.5,
            data_sources=[source],
            as_of=as_of,
            fallback_used=fallback_used
        )

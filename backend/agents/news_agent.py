from typing import Any, List, Optional
from datetime import datetime
from backend.agents.base_agent import BaseFinancialAgent, AgentOutput, EvidenceItem
from backend.services.circuit_breaker import CircuitBreaker

class NewsAgent(BaseFinancialAgent):
    AGENT_NAME = "NewsAgent"
    CACHE_TTL = 600  # 10 minutes

    def __init__(self, llm, cache, tools_module, circuit_breaker: Optional[CircuitBreaker] = None):
        super().__init__(llm, cache, circuit_breaker)
        self.tools = tools_module

    async def _initial_search(self, query: str, ticker: str) -> List[Any]:
        cache_key = f"{ticker}:news:24h"
        cached = self.cache.get(cache_key)
        if cached:
            return cached

        results = []

        # 1. Try Finnhub News
        if self.circuit_breaker.can_call("finnhub"):
            try:
                # Assuming tools module has this method
                finnhub_news = getattr(self.tools, "_fetch_with_finnhub_news", None)
                if finnhub_news:
                    news_items = finnhub_news(ticker)
                    if news_items:
                        results.extend(news_items)
                        self.circuit_breaker.record_success("finnhub")
            except Exception:
                self.circuit_breaker.record_failure("finnhub")

        # 2. Try Tavily Search (Fallback or Supplement)
        if not results or len(results) < 3:
             if self.circuit_breaker.can_call("tavily"):
                try:
                    tavily_news = getattr(self.tools, "_search_company_news", None)
                    if tavily_news:
                         # Tavily search for news
                         t_results = tavily_news(f"{ticker} stock news")
                         if t_results:
                             results.extend(t_results)
                             self.circuit_breaker.record_success("tavily")
                except Exception:
                    self.circuit_breaker.record_failure("tavily")

        # Deduplicate
        seen_urls = set()
        unique_results = []
        for item in results:
            url = item.get("url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                unique_results.append(item)

        self.cache.set(cache_key, unique_results, self.CACHE_TTL)
        return unique_results

    async def _first_summary(self, data: List[Any]) -> str:
        if not data:
            return "No recent news found."

        # Simple concatenation for MVP, real impl would use LLM
        titles = [item.get("headline", item.get("title", "")) for item in data[:5]]
        return f"Recent news includes: {'; '.join(titles)}"

    async def _identify_gaps(self, summary: str) -> List[str]:
        # MVP: If summary is too short, maybe look for more?
        # Real implementation: LLM check
        return []

    async def _targeted_search(self, gaps: List[str], ticker: str) -> Any:
        return []

    async def _update_summary(self, summary: str, new_data: Any) -> str:
        return summary

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        evidence = []
        sources = set()

        for item in raw_data:
            source = item.get("source", "unknown")
            sources.add(source)
            evidence.append(EvidenceItem(
                text=item.get("headline", item.get("title", "")),
                source=source,
                url=item.get("url"),
                timestamp=item.get("datetime", item.get("published_at"))
            ))

        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=evidence,
            confidence=0.8 if raw_data else 0.1,
            data_sources=list(sources),
            as_of=datetime.now().isoformat(),
            fallback_used=False
        )

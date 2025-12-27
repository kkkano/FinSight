from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
import asyncio
from backend.services.circuit_breaker import CircuitBreaker

@dataclass
class EvidenceItem:
    text: str
    source: str
    url: Optional[str] = None
    timestamp: Optional[str] = None
    confidence: float = 1.0  # 0-1

@dataclass
class AgentOutput:
    agent_name: str
    summary: str
    evidence: List[EvidenceItem]
    confidence: float
    data_sources: List[str]
    as_of: str
    fallback_used: bool = False
    risks: List[str] = field(default_factory=list)

class BaseFinancialAgent:
    AGENT_NAME = "base"
    MAX_REFLECTIONS = 2

    def __init__(self, llm, cache, circuit_breaker: Optional[CircuitBreaker] = None):
        self.llm = llm
        self.cache = cache
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

    async def research(self, query: str, ticker: str) -> AgentOutput:
        """
        Standard research flow:
        1. Initial search
        2. First summary
        3. Reflection loop (optional, implemented by subclasses)
        4. Format output
        """
        # 1. 初始搜索
        results = await self._initial_search(query, ticker)
        summary = await self._first_summary(results)

        # 2. 反思循环 (默认空实现，由子类覆盖)
        for i in range(self.MAX_REFLECTIONS):
            gaps = await self._identify_gaps(summary)
            if not gaps:
                break
            new_data = await self._targeted_search(gaps, ticker)
            summary = await self._update_summary(summary, new_data)

        return self._format_output(summary, results)

    async def _initial_search(self, query: str, ticker: str) -> Any:
        raise NotImplementedError

    async def _first_summary(self, data: Any) -> str:
        # Default simple summary, subclasses should implement LLM summary
        return str(data)

    async def _identify_gaps(self, summary: str) -> List[str]:
        # Default no gaps
        return []

    async def _targeted_search(self, gaps: List[str], ticker: str) -> Any:
        # Default no new data
        return None

    async def _update_summary(self, summary: str, new_data: Any) -> str:
        return summary

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        # Basic implementation, override for more specific formatting
        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=[],
            confidence=0.5,
            data_sources=[],
            as_of=datetime.now().isoformat(),
            fallback_used=False,
            risks=[]
        )

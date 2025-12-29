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

    async def analyze_stream(self, query: str, ticker: str):
        """
        流式分析接口，实时返回搜索结果和 LLM tokens
        
        Yields:
            dict: 包含 type 和相关数据的字典
            - type='agent_start': Agent 开始工作
            - type='search_start': 开始搜索
            - type='search_result': 搜索结果计数
            - type='summary_start': 开始生成摘要
            - type='token': LLM token
            - type='done': 完成，包含最终输出
        """
        import json
        
        # 1. 通知 Agent 开始
        yield json.dumps({
            "type": "agent_start", 
            "agent": self.AGENT_NAME,
            "message": f"{self.AGENT_NAME} 开始分析..."
        }, ensure_ascii=False)
        
        # 2. 执行搜索
        yield json.dumps({
            "type": "search_start",
            "agent": self.AGENT_NAME
        }, ensure_ascii=False)
        
        try:
            results = await self._initial_search(query, ticker)
            result_count = len(results) if isinstance(results, list) else 1
            
            yield json.dumps({
                "type": "search_result",
                "agent": self.AGENT_NAME,
                "count": result_count
            }, ensure_ascii=False)
        except Exception as e:
            yield json.dumps({
                "type": "error",
                "agent": self.AGENT_NAME,
                "message": f"搜索失败: {str(e)}"
            }, ensure_ascii=False)
            return
        
        # 3. 流式生成摘要
        yield json.dumps({
            "type": "summary_start",
            "agent": self.AGENT_NAME
        }, ensure_ascii=False)
        
        summary_buffer = ""
        async for token in self._stream_summary(results):
            summary_buffer += token
            yield json.dumps({
                "type": "token",
                "content": token
            }, ensure_ascii=False)
        
        # 如果没有流式输出，使用同步方法
        if not summary_buffer:
            summary_buffer = await self._first_summary(results)
            yield json.dumps({
                "type": "token",
                "content": summary_buffer
            }, ensure_ascii=False)
        
        # 4. 格式化最终输出
        output = self._format_output(summary_buffer, results)
        
        yield json.dumps({
            "type": "done",
            "agent": self.AGENT_NAME,
            "output": {
                "agent_name": output.agent_name,
                "summary": output.summary,
                "confidence": output.confidence,
                "data_sources": output.data_sources,
                "as_of": output.as_of
            }
        }, ensure_ascii=False)

    async def _stream_summary(self, data: Any):
        """
        流式生成摘要的辅助方法
        子类应重写此方法以实现真正的流式 LLM 输出
        
        默认实现：使用同步摘要方法，一次性返回
        
        Yields:
            str: 摘要 token
        """
        # 默认实现：非流式，直接返回完整摘要
        summary = await self._first_summary(data)
        yield summary

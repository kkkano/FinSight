from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable
from datetime import datetime
import asyncio
from backend.services.circuit_breaker import CircuitBreaker
from backend.orchestration.trace_schema import create_trace_event

@dataclass
class EvidenceItem:
    text: str
    source: str
    url: Optional[str] = None
    timestamp: Optional[str] = None
    confidence: float = 1.0  # 0-1
    title: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)

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
    trace: List[Dict[str, Any]] = field(default_factory=list)

class BaseFinancialAgent:
    AGENT_NAME = "base"
    MAX_REFLECTIONS = 2

    def __init__(self, llm, cache, circuit_breaker: Optional[CircuitBreaker] = None):
        self.llm = llm
        self.cache = cache
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self._current_query: Optional[str] = None
        self._current_ticker: Optional[str] = None

    async def research(self, query: str, ticker: str, on_event: Optional[Callable[[Dict[str, Any]], None]] = None) -> AgentOutput:
        """
        Standard research flow:
        1. Initial search
        2. First summary
        3. Reflection loop (optional, implemented by subclasses)
        4. Format output
        """
        self._current_query = query
        self._current_ticker = ticker
        trace: List[Dict[str, Any]] = []
        
        def _log_event(event_type: str, details: Dict[str, Any]):
            trace.append(create_trace_event(event_type, agent=self.AGENT_NAME, **details))
            if on_event:
                # Bridge internal trace events to external listener
                try:
                    on_event({
                        "event": "agent_execution",
                        "agent": self.AGENT_NAME,
                        "details": {"type": event_type, **details},
                        "timestamp": datetime.now().isoformat()
                    })
                except Exception:
                    pass

        _log_event("agent_start", {"query": query, "ticker": ticker})

        # 1. 初始搜索
        if on_event:
            try:
                on_event({
                    "event": "agent_action", 
                    "agent": self.AGENT_NAME, 
                    "details": {"message": f"正在搜索: {query[:30]}..."}
                })
            except: pass
            
        results = await self._initial_search(query, ticker)
        result_count = None
        try:
            result_count = len(results)  # type: ignore[arg-type]
        except Exception:
            result_count = None
            
        _log_event("search_result", {"result_count": result_count, "result_type": type(results).__name__})

        summary = await self._first_summary(results)
        if summary:
            _log_event("summary_init", {
                "summary_preview": str(summary)[:200],
                "summary_length": len(str(summary)),
            })

        # 2. 反思循环 (默认空实现，由子类覆盖)
        for i in range(self.MAX_REFLECTIONS):
            gaps = await self._identify_gaps(summary)
            if not gaps:
                break
            
            if on_event:
                try: on_event({"event": "agent_action", "agent": self.AGENT_NAME, "details": {"message": f"发现信息缺口，进行第 {i+1} 轮补充搜索..."}})
                except: pass

            _log_event("reflection_gap", {"round": i + 1, "gaps": gaps})
            new_data = await self._targeted_search(gaps, ticker)
            
            _log_event("reflection_search", {
                "round": i + 1,
                "new_data_preview": str(new_data)[:300] if new_data is not None else "",
            })
            summary = await self._update_summary(summary, new_data)
            if summary:
                _log_event("summary_update", {
                    "round": i + 1,
                    "summary_preview": str(summary)[:200],
                    "summary_length": len(str(summary)),
                })

        output = self._format_output(summary, results)
        _log_event("agent_end", {
            "confidence": getattr(output, "confidence", None),
            "evidence_count": len(getattr(output, "evidence", []) or []),
        })
        existing_trace = getattr(output, "trace", None) or []
        output.trace = trace + existing_trace
        return output

    async def _initial_search(self, query: str, ticker: str) -> Any:
        raise NotImplementedError

    async def _first_summary(self, data: Any) -> str:
        # Default simple summary, subclasses should implement LLM summary
        return str(data)

    async def _identify_gaps(self, summary: str) -> List[str]:
        """Use LLM to identify missing information for the current query."""
        if not self.llm:
            return []
        query = self._current_query or ""
        ticker = self._current_ticker or ""
        prompt = f"""<role>金融分析师-信息缺口检测器</role>

<task>识别摘要中缺失的关键信息，输出可搜索的查询短语</task>

<input>
<query>{query}</query>
<ticker>{ticker}</ticker>
<summary>{summary}</summary>
</input>

<rules>
- 仅输出1-4条搜索短语，每行一条
- 短语需具体、可搜索，包含股票代码或公司名
- 聚焦：财务数据、风险因素、行业对比、近期事件
- 若信息完整，输出：无缺口
</rules>

<constraints>
- 禁止：开场白、解释、编号、标点符号
- 禁止：重复摘要已有信息
- 直接输出短语，无需任何前缀
</constraints>"""
        try:
            from langchain_core.messages import HumanMessage
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            text = response.content if hasattr(response, "content") else str(response)
        except Exception:
            return []

        gaps: List[str] = []
        for line in str(text).splitlines():
            cleaned = line.strip().lstrip("-*0123456789. ").strip()
            if cleaned:
                gaps.append(cleaned)
        return gaps[:4]

    async def _targeted_search(self, gaps: List[str], ticker: str) -> Any:
        import logging
        logger = logging.getLogger(__name__)

        tools = getattr(self, "tools", None)
        search_func = getattr(tools, "search", None) if tools else None
        if not gaps or not search_func:
            return None
        results = []
        for gap in gaps[:3]:
            try:
                query = f"{ticker} {gap}".strip()
                result = search_func(query)
                if result and isinstance(result, str) and len(result) > 50:
                    results.append(result)
                    logger.info(f"[BaseAgent] Targeted search success: {query[:50]}... ({len(result)} chars)")
                else:
                    logger.warning(f"[BaseAgent] Targeted search returned empty/invalid result for: {query}")
            except Exception as e:
                logger.error(f"[BaseAgent] Targeted search failed for '{query}': {e}")
                continue
        return "\n\n---\n\n".join(results) if results else None

    async def _update_summary(self, summary: str, new_data: Any) -> str:
        if not new_data or not self.llm:
            return summary
        prompt = f"""<role>金融分析师-信息整合专家</role>

<task>将新信息整合到现有摘要中</task>

<current_summary>
{summary}
</current_summary>

<new_information>
{new_data}
</new_information>

<requirements>
- 直接输出整合后的摘要内容，禁止任何标题、前缀、开场白
- 保持简洁，不超过原摘要1.5倍长度
- 仅整合有价值的新信息，无价值则返回原摘要
- 禁止编造数据
- 禁止输出"更新后的摘要"、"整合后的内容"等元信息
</requirements>

<output_format>
直接输出摘要正文，无需任何格式标记
</output_format>"""
        try:
            from langchain_core.messages import HumanMessage
            response = await self.llm.ainvoke([HumanMessage(content=prompt)])
            updated = response.content if hasattr(response, "content") else str(response)
            return updated.strip() or summary
        except Exception:
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

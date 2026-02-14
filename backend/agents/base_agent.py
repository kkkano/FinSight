from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any, Callable
from datetime import datetime
import asyncio
import json
import logging
import os
import time
from backend.services.circuit_breaker import CircuitBreaker
from backend.orchestration.trace_schema import create_trace_event
from backend.orchestration.trace_emitter import get_trace_emitter

logger = logging.getLogger(__name__)

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
class ConflictClaim:
    """A single conflict between two data sources."""
    claim: str                          # What is in conflict (e.g. "CPI inflation rate")
    source_a: str                       # First source name
    value_a: str                        # Value from source A
    source_b: str                       # Second source name
    value_b: str                        # Value from source B
    severity: str = "medium"            # low / medium / high
    resolved: bool = False              # Whether this conflict was adjudicated
    resolution: Optional[str] = None    # How it was resolved (if resolved)
    timestamp_a: Optional[str] = None   # When source A provided data
    timestamp_b: Optional[str] = None   # When source B provided data

@dataclass
class AgentOutput:
    agent_name: str
    summary: str
    evidence: List[EvidenceItem]
    confidence: float
    data_sources: List[str]
    as_of: str
    evidence_quality: Dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False
    risks: List[str] = field(default_factory=list)
    trace: List[Dict[str, Any]] = field(default_factory=list)
    # --- Conflict tracking (new) ---
    conflict_flags: List[str] = field(default_factory=list)
    conflicting_claims: List[ConflictClaim] = field(default_factory=list)
    # --- Fallback observability (new) ---
    fallback_reason: Optional[str] = None
    retryable: bool = True
    error_stage: Optional[str] = None

class BaseFinancialAgent:
    AGENT_NAME = "base"
    MAX_REFLECTIONS = 0

    def __init__(self, llm, cache, circuit_breaker: Optional[CircuitBreaker] = None):
        self.llm = llm
        self.cache = cache
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self._current_query: Optional[str] = None
        self._current_ticker: Optional[str] = None
        try:
            self.max_reflections = max(
                0,
                int(os.getenv("BASE_AGENT_MAX_REFLECTIONS", str(self.MAX_REFLECTIONS))),
            )
        except Exception:
            self.max_reflections = max(0, self.MAX_REFLECTIONS)

    def _reflection_token_timeout(self) -> float:
        try:
            return max(3.0, float(os.getenv("BASE_AGENT_REFLECTION_TOKEN_TIMEOUT_SECONDS", "12")))
        except Exception:
            return 12.0

    def _llm_analyze_timeout(self) -> float:
        """Timeout (seconds) for the LLM analysis call in _llm_analyze."""
        env_key = f"{self.AGENT_NAME.upper()}_LLM_ANALYZE_TIMEOUT_SECONDS"
        try:
            return max(5.0, float(os.getenv(env_key, os.getenv("AGENT_LLM_ANALYZE_TIMEOUT_SECONDS", "30"))))
        except Exception:
            return 30.0

    def _get_tool_registry(self) -> dict:
        """Return available tools for this agent's reflection loop.

        Subclasses override to expose domain-specific tools (e.g. get_company_news,
        get_financial_statements).  The base class provides only ``search``.

        Format::

            {
                "tool_name": {
                    "func": callable,
                    "description": "Human-readable tool description",
                    "call_with": "query" | "ticker" | "none",
                },
            }
        """
        tools = getattr(self, "tools", None)
        search_fn = getattr(tools, "search", None) if tools else None
        if not search_fn:
            return {}
        return {
            "search": {
                "func": search_fn,
                "description": "通用网络搜索，可查询任意信息",
                "call_with": "query",
            },
        }

    async def _llm_analyze(
        self,
        raw_data_summary: str,
        *,
        role: str,
        focus: str,
    ) -> Optional[str]:
        """
        Use LLM to produce analytical insights from a deterministic data summary.

        Returns the analysis text on success, or *None* if the LLM is
        unavailable / the call fails — callers should fall back to the
        deterministic summary.
        """
        if not self.llm:
            return None

        enabled = os.getenv("AGENT_LLM_ANALYZE_ENABLED", "true").lower() in (
            "true", "1", "yes", "on",
        )
        if not enabled:
            return None

        ticker = self._current_ticker or ""
        query = self._current_query or ""

        prompt = f"""<role>{role}</role>

<task>
基于以下数据摘要，撰写一段专业的分析评论。不要重复罗列原始数据，而是解读数据背后的含义、趋势与风险。
</task>

<context>
<query>{query}</query>
<ticker>{ticker}</ticker>
</context>

<data_summary>
{raw_data_summary[:3000]}
</data_summary>

<analysis_focus>{focus}</analysis_focus>

<output_rules>
- 输出 200-500 字中文分析段落
- 必须包含：数据解读 + 趋势/方向判断 + 关键风险提示
- 引用具体数值支撑论点（不可编造数字）
- 区分事实与推断，推断标注"预计"/"可能"
- 禁止：标题、列表符号、分隔线、开场白
- 直接输出分析正文
</output_rules>"""

        try:
            from langchain_core.messages import HumanMessage
            from backend.services.rate_limiter import acquire_llm_token
            from backend.services.llm_retry import ainvoke_with_rate_limit_retry

            token_timeout = self._llm_analyze_timeout()
            if not await acquire_llm_token(timeout=token_timeout, agent_name=self.AGENT_NAME):
                logger.warning("[%s] Rate limit timeout in _llm_analyze", self.AGENT_NAME)
                return None

            trace_emitter = get_trace_emitter()
            trace_emitter.emit_llm_start(
                model=getattr(self.llm, "model_name", None),
                prompt_preview=f"[_llm_analyze:{self.AGENT_NAME}] {focus[:80]}",
                agent=self.AGENT_NAME,
            )
            start_time = time.perf_counter()

            response = await ainvoke_with_rate_limit_retry(
                self.llm,
                [HumanMessage(content=prompt)],
                acquire_token=False,
            )

            content = getattr(response, "content", None)
            duration_ms = int((time.perf_counter() - start_time) * 1000)

            # Validate: content must be a real string (not a Mock) with enough substance
            if not isinstance(content, str) or len(content.strip()) < 80:
                trace_emitter.emit_llm_end(
                    model=getattr(self.llm, "model_name", None),
                    duration_ms=duration_ms,
                    success=False,
                    error="response content too short or invalid type",
                    agent=self.AGENT_NAME,
                )
                return None

            trace_emitter.emit_llm_end(
                model=getattr(self.llm, "model_name", None),
                duration_ms=duration_ms,
                success=True,
                agent=self.AGENT_NAME,
            )
            return content.strip()
        except Exception as exc:
            logger.info("[%s] _llm_analyze failed: %s", self.AGENT_NAME, exc)
            try:
                get_trace_emitter().emit_llm_end(
                    model=getattr(self.llm, "model_name", None) if self.llm else None,
                    success=False,
                    error=str(exc),
                    agent=self.AGENT_NAME,
                )
            except Exception:
                pass
            return None

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
        global_emitter = get_trace_emitter()
        start_time = time.perf_counter()

        def _log_event(event_type: str, details: Dict[str, Any]):
            trace.append(create_trace_event(event_type, agent=self.AGENT_NAME, **details))
            # 发射到全局 TraceEmitter
            if event_type == "agent_start":
                global_emitter.emit_agent_start(self.AGENT_NAME, query=details.get("query"), ticker=details.get("ticker"))
            elif event_type == "agent_end":
                duration_ms = int((time.perf_counter() - start_time) * 1000)
                global_emitter.emit_agent_done(
                    self.AGENT_NAME,
                    success=True,
                    duration_ms=duration_ms,
                    summary=f"confidence={details.get('confidence')}, evidence={details.get('evidence_count')}"
                )
            else:
                global_emitter.emit_agent_step(self.AGENT_NAME, event_type, details)

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
                    logger.debug("[%s] on_event callback failed", self.AGENT_NAME, exc_info=True)

        _log_event("agent_start", {"query": query, "ticker": ticker})

        # 1. 初始搜索
        if on_event:
            try:
                on_event({
                    "event": "agent_action", 
                    "agent": self.AGENT_NAME, 
                    "details": {"message": f"正在搜索: {query[:30]}..."}
                })
            except: logger.debug("[%s] on_event callback error in search notification", self.AGENT_NAME, exc_info=True)
            
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
        for i in range(self.max_reflections):
            gaps = await self._identify_gaps(summary)
            if not gaps:
                break
            
            if on_event:
                try: on_event({"event": "agent_action", "agent": self.AGENT_NAME, "details": {"message": f"发现信息缺口，进行第 {i+1} 轮补充搜索..."}})
                except: logger.debug("[%s] on_event callback error in search notification", self.AGENT_NAME, exc_info=True)

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

    async def _identify_gaps(self, summary: str) -> List:
        """Use LLM to identify missing information, with tool-aware suggestions.

        Returns a list of gap items.  Each item is either:
        - ``dict`` with keys ``gap``, ``tool``, ``query`` (new structured format)
        - ``str`` (legacy plain-text search phrase, used as fallback)

        The downstream ``_targeted_search`` handles both formats transparently.
        """
        if not self.llm:
            return []
        query = self._current_query or ""
        ticker = self._current_ticker or ""

        # Build tool catalogue for the prompt
        registry = self._get_tool_registry()
        tool_catalogue = "\n".join(
            f"- {name}: {entry.get('description', '')}"
            for name, entry in registry.items()
        ) or "- search: 通用网络搜索"

        prompt = f"""<role>金融分析师 — 信息缺口检测器</role>

<task>
评估以下摘要相对于用户查询的信息完整性，识别关键缺失信息并建议使用哪个工具补充。
</task>

<input>
<query>{query}</query>
<ticker>{ticker}</ticker>
<summary>{summary}</summary>
</input>

<available_tools>
{tool_catalogue}
</available_tools>

<evaluation_dimensions>
逐一检查以下维度是否已覆盖：
- 关键财务数据（营收、利润、估值指标如 PE/PB）
- 风险因素（公司特有风险 + 行业/系统性风险）
- 行业对比（竞争格局、市场份额）
- 时效性信息（最新财报、近期公告、重大事件）
- 用户查询的核心关注点是否已回答
</evaluation_dimensions>

<output_format>
每行一条 JSON，格式: {{"gap": "缺失信息描述", "tool": "建议工具名", "query": "搜索/调用参数"}}
- tool 必须是 available_tools 中列出的工具名之一
- 若工具类型为 ticker 类（非 search），query 填写股票代码即可
- 输出 1-3 条，优先补充与用户查询最相关的缺失信息
- 若信息已充分覆盖用户查询，输出: {{"complete": true}}
</output_format>

<constraints>
- 禁止：开场白、解释、编号前缀
- 禁止：重复摘要已有信息的搜索词
- 直接输出 JSON，每行一条
</constraints>"""
        try:
            from langchain_core.messages import HumanMessage
            from backend.services.rate_limiter import acquire_llm_token

            token_timeout = self._reflection_token_timeout()
            if not await acquire_llm_token(timeout=token_timeout, agent_name=self.AGENT_NAME):
                logger.warning("[%s] Rate limit timeout after %.1fs in _identify_gaps", self.AGENT_NAME, token_timeout)
                return []

            trace_emitter = get_trace_emitter()
            trace_emitter.emit_llm_start(
                model=getattr(self.llm, "model_name", None),
                prompt_preview=prompt[:100] + "...",
                agent=self.AGENT_NAME
            )
            start_time = time.perf_counter()

            from backend.services.llm_retry import ainvoke_with_rate_limit_retry

            response = await ainvoke_with_rate_limit_retry(
                self.llm,
                [HumanMessage(content=prompt)],
                acquire_token=False,
            )
            text = response.content if hasattr(response, "content") else str(response)

            duration_ms = int((time.perf_counter() - start_time) * 1000)
            trace_emitter.emit_llm_end(
                model=getattr(self.llm, "model_name", None),
                duration_ms=duration_ms,
                success=True,
                agent=self.AGENT_NAME
            )
        except Exception as e:
            trace_emitter = get_trace_emitter()
            trace_emitter.emit_llm_end(
                model=getattr(self.llm, "model_name", None) if self.llm else None,
                success=False,
                error=str(e),
                agent=self.AGENT_NAME
            )
            return []

        # Parse response: try JSON per line, fall back to plain text
        gaps: List = []
        for line in str(text).splitlines():
            cleaned = line.strip()
            if not cleaned:
                continue
            # Try JSON parse first (new structured format)
            try:
                obj = json.loads(cleaned)
                if isinstance(obj, dict):
                    if obj.get("complete"):
                        return []  # LLM says info is sufficient
                    if obj.get("gap") or obj.get("query"):
                        gaps.append(obj)
                    continue
            except (json.JSONDecodeError, ValueError):
                pass
            # Fallback: treat as plain text search phrase (backward compat)
            cleaned = cleaned.lstrip("-*0123456789. ").strip()
            if cleaned and "无缺口" not in cleaned and "complete" not in cleaned.lower():
                gaps.append(cleaned)
        return gaps[:4]

    async def _targeted_search(self, gaps: List, ticker: str) -> Any:
        """Execute targeted tool calls based on gap analysis.

        Each gap can be:
        - ``dict`` with ``tool`` + ``query`` (tool-aware mode)
        - ``str`` (legacy mode — always uses ``search``)

        Falls back to ``search`` if the suggested tool is unavailable.
        """
        registry = self._get_tool_registry()
        if not gaps or not registry:
            return None

        trace_emitter = get_trace_emitter()
        results = []
        for gap_item in gaps[:3]:
            # Resolve tool name and query from gap item
            if isinstance(gap_item, dict):
                tool_name = str(gap_item.get("tool", "search")).strip()
                gap_query = str(gap_item.get("query", gap_item.get("gap", ""))).strip()
                gap_desc = str(gap_item.get("gap", tool_name)).strip()
            else:
                tool_name = "search"
                gap_query = str(gap_item).strip()
                gap_desc = gap_query

            # Look up tool; fall back to search if not found
            tool_entry = registry.get(tool_name)
            if not tool_entry:
                tool_entry = registry.get("search")
                tool_name = "search"
            if not tool_entry:
                continue

            func = tool_entry["func"]
            call_with = tool_entry.get("call_with", "query")

            # Emit trace: tool dispatch start
            trace_emitter.emit_tool_start(tool_name, {"query": gap_desc}, agent=self.AGENT_NAME)

            try:
                if call_with == "query":
                    # Search-style: combine ticker + query
                    search_query = f"{ticker} {gap_query}".strip() if gap_query else ticker
                    result = func(search_query)
                elif call_with == "ticker":
                    result = func(ticker)
                else:
                    # No-args tools (e.g. get_fred_data)
                    result = func()

                # Validate result — only accept str/list/dict (reject mock objects in tests)
                if result is not None and isinstance(result, (str, list, dict)):
                    result_str = str(result) if not isinstance(result, str) else result
                    if len(result_str) > 50:
                        results.append(result_str)
                        trace_emitter.emit_tool_end(tool_name, success=True, agent=self.AGENT_NAME)
                        logger.info(
                            "[%s] Tool-aware search success: %s(%s) → %d chars",
                            self.AGENT_NAME, tool_name, gap_desc[:40], len(result_str),
                        )
                    else:
                        trace_emitter.emit_tool_end(tool_name, success=False, agent=self.AGENT_NAME)
                else:
                    trace_emitter.emit_tool_end(tool_name, success=False, agent=self.AGENT_NAME)
            except Exception as e:
                logger.warning("[%s] Tool %s failed for '%s': %s", self.AGENT_NAME, tool_name, gap_desc[:40], e)
                trace_emitter.emit_tool_end(tool_name, success=False, error=str(e), agent=self.AGENT_NAME)
                # Fallback to search if a specialized tool fails
                if tool_name != "search":
                    search_entry = registry.get("search")
                    if search_entry:
                        try:
                            fallback_query = f"{ticker} {gap_query}".strip()
                            fb_result = search_entry["func"](fallback_query)
                            if fb_result and isinstance(fb_result, str) and len(fb_result) > 30:
                                results.append(fb_result)
                                logger.info("[%s] Fallback search success for: %s", self.AGENT_NAME, gap_desc[:40])
                        except Exception:
                            pass
                continue
        return "\n\n---\n\n".join(results) if results else None

    async def _update_summary(self, summary: str, new_data: Any) -> str:
        if not new_data or not self.llm:
            return summary
        prompt = f"""<role>金融分析师 — 信息整合专家</role>

<task>将新检索到的信息有机整合到现有摘要中，提升摘要的完整性和分析深度。</task>

<current_summary>
{summary}
</current_summary>

<new_information>
{new_data}
</new_information>

<integration_rules>
- 仅整合有实质价值的新信息（新数据点、新视角、新风险）
- 新旧信息冲突时，优先采用更新、更权威的数据，并标注更新
- 保持原摘要的结构和逻辑框架
- 整合后总长度不超过原摘要的 1.5 倍
- 无有价值的新信息时，原样返回现有摘要
</integration_rules>

<constraints>
- 直接输出整合后的摘要正文
- 禁止任何标题、前缀、开场白
- 禁止"更新后的摘要"、"整合后的内容"等元信息
- 禁止编造数据
- 禁止任何格式标记
</constraints>"""
        try:
            from langchain_core.messages import HumanMessage
            from backend.services.rate_limiter import acquire_llm_token

            # 获取速率限制令牌（并发 agent 场景需要较长等待）
            token_timeout = self._reflection_token_timeout()
            if not await acquire_llm_token(timeout=token_timeout, agent_name=self.AGENT_NAME):
                logger.warning("[%s] Rate limit timeout after %.1fs in _update_summary", self.AGENT_NAME, token_timeout)
                return summary  # 限流超时，返回原摘要

            # 发射 LLM 调用开始事件
            trace_emitter = get_trace_emitter()
            trace_emitter.emit_llm_start(
                model=getattr(self.llm, "model_name", None),
                prompt_preview="[update_summary] " + prompt[:80] + "...",
                agent=self.AGENT_NAME
            )
            start_time = time.perf_counter()

            from backend.services.llm_retry import ainvoke_with_rate_limit_retry

            response = await ainvoke_with_rate_limit_retry(
                self.llm,
                [HumanMessage(content=prompt)],
                acquire_token=False,
            )
            updated = response.content if hasattr(response, "content") else str(response)

            # 发射 LLM 调用结束事件
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            trace_emitter.emit_llm_end(
                model=getattr(self.llm, "model_name", None),
                duration_ms=duration_ms,
                success=True,
                agent=self.AGENT_NAME
            )
            return updated.strip() or summary
        except Exception as e:
            # 发射 LLM 调用失败事件
            trace_emitter = get_trace_emitter()
            trace_emitter.emit_llm_end(
                model=getattr(self.llm, "model_name", None) if self.llm else None,
                success=False,
                error=str(e),
                agent=self.AGENT_NAME
            )
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

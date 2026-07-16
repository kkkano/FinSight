from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from backend.orchestration.trace_emitter import get_trace_emitter
from backend.orchestration.trace_schema import create_trace_event
from backend.services.circuit_breaker import CircuitBreaker


logger = logging.getLogger(__name__)


@dataclass
class EvidenceItem:
    text: str
    source: str
    url: Optional[str] = None
    timestamp: Optional[str] = None
    confidence: float = 1.0
    title: Optional[str] = None
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ConflictClaim:
    """两个数据源之间的一项冲突。"""

    claim: str
    source_a: str
    value_a: str
    source_b: str
    value_b: str
    severity: str = "medium"
    resolved: bool = False
    resolution: Optional[str] = None
    timestamp_a: Optional[str] = None
    timestamp_b: Optional[str] = None


@dataclass
class AgentOutput:
    agent_name: str
    summary: str
    evidence: List[EvidenceItem]
    confidence: float
    data_sources: List[str]
    as_of: str
    claims: list[dict[str, Any]] = field(default_factory=list)
    chart_specs: list[dict[str, Any]] = field(default_factory=list)
    ledger: dict[str, Any] | None = None
    evidence_quality: Dict[str, Any] = field(default_factory=dict)
    fallback_used: bool = False
    risks: List[str] = field(default_factory=list)
    trace: List[Dict[str, Any]] = field(default_factory=list)
    conflict_flags: List[str] = field(default_factory=list)
    conflicting_claims: List[ConflictClaim] = field(default_factory=list)
    fallback_reason: Optional[str] = None
    retryable: bool = True
    error_stage: Optional[str] = None


class BaseFinancialAgent:
    """确定性 evidence collector 的公共执行骨架。

    `llm` 参数仅用于兼容既有 collector 构造签名，实例不会保存或调用它。业务分析统一由
    Graph synthesis 的 ResearchAnalyst 完成。
    """

    AGENT_NAME = "base"

    def __init__(
        self,
        llm: Any,
        cache: Any,
        tools_module: Any = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
    ) -> None:
        del llm
        self.cache = cache
        self.tools = tools_module
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.__current_query: ContextVar[Optional[str]] = ContextVar(
            f"{type(self).__name__}._current_query",
            default=None,
        )
        self.__current_ticker: ContextVar[Optional[str]] = ContextVar(
            f"{type(self).__name__}._current_ticker",
            default=None,
        )

    @property
    def _current_query(self) -> Optional[str]:
        return self.__current_query.get()

    @_current_query.setter
    def _current_query(self, value: Optional[str]) -> None:
        self.__current_query.set(value)

    @property
    def _current_ticker(self) -> Optional[str]:
        return self.__current_ticker.get()

    @_current_ticker.setter
    def _current_ticker(self, value: Optional[str]) -> None:
        self.__current_ticker.set(value)

    async def research(
        self,
        query: str,
        ticker: str,
        on_event: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> AgentOutput:
        """执行一次采集、确定性摘要和质量合同，不启动内部 LLM 或补充搜索循环。"""

        self._current_query = query
        self._current_ticker = ticker
        trace: List[Dict[str, Any]] = []
        global_emitter = get_trace_emitter()
        start_time = time.perf_counter()

        def log_event(event_type: str, details: Dict[str, Any]) -> None:
            trace.append(create_trace_event(event_type, agent=self.AGENT_NAME, **details))
            if event_type == "agent_start":
                global_emitter.emit_agent_start(
                    self.AGENT_NAME,
                    query=details.get("query"),
                    ticker=details.get("ticker"),
                )
            elif event_type == "agent_end":
                global_emitter.emit_agent_done(
                    self.AGENT_NAME,
                    success=True,
                    duration_ms=int((time.perf_counter() - start_time) * 1000),
                    summary=(
                        f"confidence={details.get('confidence')}, "
                        f"evidence={details.get('evidence_count')}"
                    ),
                )
            else:
                global_emitter.emit_agent_step(self.AGENT_NAME, event_type, details)

            if on_event:
                try:
                    on_event(
                        {
                            "event": "agent_execution",
                            "agent": self.AGENT_NAME,
                            "details": {"type": event_type, **details},
                            "timestamp": datetime.now().isoformat(),
                        }
                    )
                except Exception:
                    logger.debug(
                        "[%s] on_event callback failed",
                        self.AGENT_NAME,
                        exc_info=True,
                    )

        log_event("agent_start", {"query": query, "ticker": ticker})
        if on_event:
            try:
                on_event(
                    {
                        "event": "agent_action",
                        "agent": self.AGENT_NAME,
                        "details": {"message": f"正在采集: {query[:30]}..."},
                    }
                )
            except Exception:
                logger.debug(
                    "[%s] on_event callback failed",
                    self.AGENT_NAME,
                    exc_info=True,
                )

        results = await self._initial_search(query, ticker)
        try:
            result_count: int | None = len(results)
        except Exception:
            result_count = None
        log_event(
            "search_result",
            {"result_count": result_count, "result_type": type(results).__name__},
        )

        summary = await self._first_summary(results)
        if summary:
            log_event(
                "summary_init",
                {
                    "summary_preview": str(summary)[:200],
                    "summary_length": len(str(summary)),
                },
            )

        output = self._format_output(summary, results)
        try:
            from backend.research.agent_quality_contract import apply_agent_quality_contract
            from backend.research.agent_research_loop import apply_agent_self_check

            output = apply_agent_quality_contract(output, query=query, ticker=ticker)
            output = apply_agent_self_check(output, query=query, ticker=ticker)
        except Exception as exc:
            logger.debug("[%s] agent quality contract failed: %s", self.AGENT_NAME, exc)

        log_event(
            "agent_end",
            {
                "confidence": getattr(output, "confidence", None),
                "evidence_count": len(getattr(output, "evidence", []) or []),
            },
        )
        output.trace = trace + (getattr(output, "trace", None) or [])
        return output

    async def _initial_search(self, query: str, ticker: str) -> Any:
        raise NotImplementedError

    async def _first_summary(self, data: Any) -> str:
        return str(data)

    def _format_output(self, summary: str, raw_data: Any) -> AgentOutput:
        del raw_data
        return AgentOutput(
            agent_name=self.AGENT_NAME,
            summary=summary,
            evidence=[],
            confidence=0.5,
            data_sources=[],
            as_of=datetime.now().isoformat(),
            fallback_used=False,
            risks=[],
        )

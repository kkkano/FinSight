#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
[MIXED] LangGraph-based Financial Agent
========================================

⚠️ 历史代码说明 (2026-01-24):
- 此模块包含 LangGraph 实现的金融 Agent，仍在使用中
- 主要被 ConversationAgent 调用 (conversation/agent.py:986)
- 与 SupervisorAgent 的关系：
  - SupervisorAgent (supervisor_agent.py): 完整的意图分类 + 多 Agent 协调
  - LangChainFinancialAgent (本文件): LangGraph 工具调用 Agent
- 两者可以共存，服务不同场景

功能说明:
- Uses MessagesState + ToolNode from langgraph
- Binds typed LangChain tools for reliable tool-calling
- Keeps a lightweight in-memory checkpoint so threads can be resumed
"""
from __future__ import annotations

import logging
import hashlib
import json
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from backend.langchain_tools import FINANCIAL_TOOLS, get_tools_description

logger = logging.getLogger(__name__)




load_dotenv()


MAX_TOOL_CALLS = 8  # 硬性限制工具调用总次数

CIO_SYSTEM_PROMPT = """
You are the Chief Investment Officer for a global macro fund. Produce comprehensive,
actionable research using the available tools.

CURRENT DATE: {current_date}

TOOLS AVAILABLE:
{tools}

WORKFLOW (follow in order):
1) Call get_current_datetime to anchor the timeline.
2) Use search for market context and recent developments.
3) Fetch price/info/news for the specific ticker or index.
4) Add market sentiment and macro events if relevant.
5) Use drawdown/performance tools for risk framing.
6) When you have 4-6 concrete observations, write the final report.

CRITICAL RULES - MUST FOLLOW:
- DO NOT call the same tool more than ONCE with the same parameters.
- If a tool returns an error (e.g., "Rate limited", "Too Many Requests"), DO NOT retry it.
- If you already have price/news/sentiment data, DO NOT call those tools again.
- After collecting data from 4-6 tool calls, STOP and write the report.
- Maximum {max_tools} tool calls total per query. After that, use whatever data you have.
- Do NOT assume a benchmark; only compare to S&P 500 if a benchmark is explicitly provided.

REPORT TEMPLATE (800+ words):
# [Investment Name] - Professional Analysis Report
*Report Date: [use actual date from tools]*

## EXECUTIVE SUMMARY
Clear BUY/HOLD/SELL call and rationale.

## CURRENT MARKET POSITION
Price, YTD/1Y returns, key levels.

## MACRO ENVIRONMENT & CATALYSTS
Inflation/rates, upcoming events, geopolitical factors, recent news.

## RISK ASSESSMENT
Key risks, volatility/drawdowns, correlations.

## INVESTMENT STRATEGY & RECOMMENDATIONS
Primary call, confidence, time horizon, entry/stop/targets, sizing guidance.

## KEY TAKEAWAYS
3-5 concise bullet points.

RULES:
- Always start with get_current_datetime.
- Reference dates, numbers, and sources explicitly.
- Do not give generic advice; every claim must be supported by tool outputs.
- If data is unavailable due to rate limits, acknowledge it and proceed with available data.
"""


class FinancialAnalysisCallback(BaseCallbackHandler):
    """Lightweight callback to log tool usage and steps."""

    def __init__(self, verbose: bool = True, capture_events: bool = True) -> None:
        self.verbose = verbose
        self.capture_events = capture_events
        self.reset()

    def reset(self) -> None:
        """Clear counters and buffered trace events."""
        self.step_count = 0
        self.events: List[Dict[str, Any]] = []
        self._tool_start: Dict[str, float] = {}
        self._tool_names: Dict[str, str] = {}
        self._run_start: Optional[float] = None

    # LangChain callback hooks -------------------------------------------------
    def on_chain_start(self, serialized: Dict[str, Any], inputs: Dict[str, Any], **kwargs: Any) -> None:  # type: ignore[override]
        self._run_start = time.time()
        # 防止 serialized 为 None
        name = "chain"
        if serialized and isinstance(serialized, dict):
            name = serialized.get("name", "chain")
        self._record(
            {
                "event": "chain_start",
                "name": name,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )

    def on_chain_end(self, outputs: Dict[str, Any], **kwargs: Any) -> None:  # type: ignore[override]
        duration = None
        if self._run_start is not None:
            duration = (time.time() - self._run_start) * 1000
        self._record(
            {
                "event": "chain_end",
                "duration_ms": duration,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }
        )

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, run_id: Optional[str] = None, **_: Any) -> None:  # type: ignore[override]
        self.step_count += 1
        # 防止 serialized 为 None
        tool_name = "tool"
        if serialized and isinstance(serialized, dict):
            tool_name = serialized.get("name", "tool")
        key = str(run_id or self.step_count)
        self._tool_names[key] = tool_name
        self._tool_start[key] = time.time()
        preview = self._preview(input_str)
        if self.verbose:
            logger.info(f"[Tool {self.step_count}] {tool_name} | input={preview}")
        self._record(
            {
                "event": "tool_start",
                "name": tool_name,
                "input_preview": preview,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "run_id": key,
            }
        )

    def on_tool_end(self, output: Any, run_id: Optional[str] = None, **_: Any) -> None:  # type: ignore[override]
        key = str(run_id or self.step_count)
        tool_name = self._tool_names.pop(key, "tool")
        started_at = self._tool_start.pop(key, None)
        duration = (time.time() - started_at) * 1000 if started_at else None
        preview = self._preview(str(output))
        if self.verbose:
            logger.info(f"[Tool {self.step_count}] result={preview}")
        self._record(
            {
                "event": "tool_end",
                "name": tool_name,
                "duration_ms": duration,
                "output_preview": preview,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "run_id": key,
            }
        )

    def on_tool_error(self, error: BaseException, run_id: Optional[str] = None, **kwargs: Any) -> None:  # type: ignore[override]
        key = str(run_id or self.step_count)
        tool_name = self._tool_names.get(key, "tool")
        self._record(
            {
                "event": "tool_error",
                "name": tool_name,
                "error": str(error),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "run_id": key,
            }
        )

    # Helpers -----------------------------------------------------------------
    def _record(self, event: Dict[str, Any]) -> None:
        if self.capture_events:
            self.events.append(event)

    def _preview(self, text: str, limit: int = 200) -> str:
        return text if len(text) <= limit else text[: limit - 3] + "..."


class LangChainFinancialAgent:
    """LangGraph-powered financial agent with typed tool binding."""

    def __init__(
        self,
        provider: str = "gemini_proxy",
        model: Optional[str] = None,
        verbose: bool = True,
        max_iterations: int = 10,  # 降低迭代次数防止死循环
        llm: Optional[Any] = None,
        checkpointer: Optional[MemorySaver] = None,
        orchestrator: Optional[Any] = None,
    ) -> None:
        self.provider = provider
        self.model = model or self._resolve_model()
        self.verbose = verbose
        self.max_iterations = max_iterations
        self.checkpointer = checkpointer or MemorySaver()
        self.callback = FinancialAnalysisCallback(verbose=verbose)
        self.last_trace: List[Dict[str, Any]] = []
        self.llm = llm or self._create_llm()
        self.orchestrator = orchestrator
        self.tools = self._wrap_tools(FINANCIAL_TOOLS) if orchestrator else FINANCIAL_TOOLS
        self.system_prompt = self._build_system_prompt()
        self.graph = self._build_graph()

    def _wrap_tools(self, tools: List[Any]) -> List[Any]:
        """Wrap tools to use orchestrator for stats and caching where possible."""
        if not self.orchestrator:
            return tools
            
        wrapped = []
        # Mapping from tool name to orchestrator data type
        type_map = {
            "get_stock_price": "price",
            "get_company_news": "news",
            "get_company_info": "company_info",
        }
        
        for tool in tools:
            if tool.name in type_map:
                data_type = type_map[tool.name]
                
                # Create a wrapper function that keeps the same signature
                # Note: We rely on the fact that these tools take a 'ticker' string arg
                def create_wrapper(original_tool, dtype):
                    def wrapper(ticker: str) -> str:
                        try:
                            # Use orchestrator fetch (handles validation, fallback, CACHING, STATS)
                            result = self.orchestrator.fetch(dtype, ticker)
                            if result.success and result.data:
                                # Return data as string, similar to original tool
                                return str(result.data)
                            else:
                                return f"Error fetching {dtype}: {result.error}"
                        except Exception as e:
                            return f"Orchestrator error: {str(e)}"
                    return wrapper

                # Create new tool based on original
                # We use the Tool constructor from langchain_core.tools if available, 
                # or just modify the runnable if it's a StructuredTool
                from langchain_core.tools import StructuredTool
                
                new_func = create_wrapper(tool, data_type)
                
                # Create a copy of the tool with the new function
                # This preserves args_schema and description
                wrapped_tool = StructuredTool.from_function(
                    func=new_func,
                    name=tool.name,
                    description=tool.description,
                    args_schema=tool.args_schema,
                    return_direct=tool.return_direct
                )
                wrapped.append(wrapped_tool)
            else:
                wrapped.append(tool)
        return wrapped

    def _resolve_model(self) -> str:
        try:
            from backend.llm_config import get_llm_config  # type: ignore

            cfg = get_llm_config(provider=self.provider)
            return cfg.get("model", "gemini-2.5-flash")
        except Exception:
            return "gemini-2.5-flash"

    def _create_llm(self) -> ChatOpenAI:
        # 使用统一的 LLM 工厂函数（历史遗留代码已提取到 llm_config.py）
        from backend.llm_config import create_llm
        return create_llm(
            provider=self.provider,
            model=self.model,
            temperature=0.0,
            max_tokens=4000,
            request_timeout=300,
        )

    def _build_system_prompt(self) -> str:
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tools_desc = get_tools_description()
        return CIO_SYSTEM_PROMPT.format(
            current_date=current_date,
            tools=tools_desc,
            max_tools=MAX_TOOL_CALLS
        )

    def _build_graph(self):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
                ("placeholder", "{messages}"),
            ]
        )

        agent_node = (
            prompt
            | self.llm.bind_tools(self.tools)
            | RunnableLambda(
                lambda msg: {"messages": [msg]} if not isinstance(msg, dict) else msg
            )
        )

        # 工具调用追踪器
        call_tracker: Dict[str, Any] = {
            "count": 0,
            "called": set(),  # 已调用的 tool+args 哈希
            "failed": set(),  # 返回错误的工具名
        }

        def _hash_tool_call(name: str, args: dict) -> str:
            """生成工具调用的唯一哈希"""
            args_str = json.dumps(args, sort_keys=True, default=str)
            return hashlib.md5(f"{name}:{args_str}".encode()).hexdigest()

        def _check_tool_error(content: str) -> bool:
            """检查工具返回是否包含错误"""
            error_patterns = ["rate limit", "too many requests", "failed:", "error:", "exceeded", "timeout"]
            content_lower = content.lower()
            return any(p in content_lower for p in error_patterns)

        def guarded_tools_condition(state: MessagesState) -> str:
            """带限制的工具调用条件判断"""
            messages = state.get("messages", [])
            if not messages:
                return END

            last_msg = messages[-1]

            # 检查上一条 ToolMessage 是否有错误，记录失败的工具
            for msg in reversed(messages):
                if isinstance(msg, ToolMessage):
                    if _check_tool_error(msg.content):
                        call_tracker["failed"].add(msg.name)
                    break

            # 检查是否有工具调用请求
            if not isinstance(last_msg, AIMessage) or not last_msg.tool_calls:
                return END

            # 检查总调用次数
            if call_tracker["count"] >= MAX_TOOL_CALLS:
                if self.verbose:
                    logger.info(f"[Guard] 已达到最大工具调用次数 ({MAX_TOOL_CALLS})，强制结束")
                return END

            # 过滤重复和失败的工具调用
            valid_calls = []
            for tc in last_msg.tool_calls:
                tool_name = tc.get("name", "")
                tool_args = tc.get("args", {})
                call_hash = _hash_tool_call(tool_name, tool_args)

                # 跳过已失败的工具
                if tool_name in call_tracker["failed"]:
                    if self.verbose:
                        logger.info(f"[Guard] 跳过已失败的工具: {tool_name}")
                    continue

                # 跳过重复调用
                if call_hash in call_tracker["called"]:
                    if self.verbose:
                        logger.info(f"[Guard] 跳过重复调用: {tool_name}")
                    continue

                call_tracker["called"].add(call_hash)
                call_tracker["count"] += 1
                valid_calls.append(tc)

                if call_tracker["count"] >= MAX_TOOL_CALLS:
                    break

            # 如果没有有效的工具调用，结束
            if not valid_calls:
                return END

            # 更新 last_msg 的 tool_calls 为过滤后的列表
            last_msg.tool_calls = valid_calls
            return "tools"

        def reset_tracker(state: MessagesState) -> MessagesState:
            """在每次新查询时重置追踪器"""
            call_tracker["count"] = 0
            call_tracker["called"] = set()
            call_tracker["failed"] = set()
            return state

        workflow = StateGraph(MessagesState)
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", ToolNode(self.tools))
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges(
            "agent",
            guarded_tools_condition,
            {"tools": "tools", END: END},
        )
        workflow.add_edge("tools", "agent")
        workflow.set_entry_point("agent")

        # 保存 reset 函数供 analyze 调用
        self._reset_tracker = lambda: (
            call_tracker.update({"count": 0, "called": set(), "failed": set()})
        )

        return workflow.compile(checkpointer=self.checkpointer)

    def analyze(
        self,
        query: str,
        thread_id: Optional[str] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """Run the LangGraph agent on a single query."""

        overall_start = time.time()
        self.callback.reset()
        # 重置工具调用追踪器
        if hasattr(self, '_reset_tracker'):
            self._reset_tracker()
        run_id = thread_id or f"analysis-{uuid4()}"
        config = {
            "configurable": {"thread_id": run_id},
            "callbacks": [self.callback],
            "recursion_limit": self.max_iterations,
        }

        initial_state = {"messages": [HumanMessage(content=query)]}

        try:
            final_state: Dict[str, Any]
            if stream:
                final_state = {}
                for update in self.graph.stream(
                    initial_state, config=config, stream_mode="values"
                ):
                    final_state = update
                    if self.verbose:
                        messages = update.get("messages", [])
                        if messages:
                            last = messages[-1]
                            logger.info(f"[Stream] {getattr(last, 'type', 'msg')}: {getattr(last, 'content', '')[:160]}")
            else:
                final_state = self.graph.invoke(initial_state, config=config)

            messages: List[BaseMessage] = final_state.get("messages", [])
            output = messages[-1].content if messages else "No output generated"
            self.last_trace = list(self.callback.events)

            return {
                "success": True,
                "output": output,
                "messages": messages,
                "step_count": self.callback.step_count,
                "thread_id": run_id,
                "duration_ms": (time.time() - overall_start) * 1000,
                "trace": self.last_trace,
            }
        except Exception as exc:
            self.last_trace = list(self.callback.events)
            return {
                "success": False,
                "error": str(exc),
                "step_count": self.callback.step_count,
                "thread_id": run_id,
                "duration_ms": (time.time() - overall_start) * 1000,
                "trace": self.last_trace,
            }

    async def analyze_stream(self, query: str, thread_id: Optional[str] = None):
        """Stream LLM output token by token."""
        from uuid import uuid4
        import json

        # 重置工具调用追踪器
        if hasattr(self, '_reset_tracker'):
            self._reset_tracker()
        run_id = thread_id or f"analysis-{uuid4()}"
        config = {
            "configurable": {"thread_id": run_id},
            "callbacks": [self.callback],
            "recursion_limit": self.max_iterations,
        }
        initial_state = {"messages": [HumanMessage(content=query)]}

        try:
            async for event in self.graph.astream_events(
                initial_state, config=config, version="v2"
            ):
                kind = event.get("event", "")
                # LLM token streaming
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk and hasattr(chunk, "content") and chunk.content:
                        yield json.dumps({"type": "token", "content": chunk.content}, ensure_ascii=False) + "\n"
                # Tool call events
                elif kind == "on_tool_start":
                    name = event.get("name", "tool")
                    yield json.dumps({"type": "tool_start", "name": name}, ensure_ascii=False) + "\n"
                elif kind == "on_tool_end":
                    yield json.dumps({"type": "tool_end"}, ensure_ascii=False) + "\n"

            yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"
        except Exception as e:
            yield json.dumps({"type": "error", "message": str(e)}, ensure_ascii=False) + "\n"

    def describe_graph(self) -> Dict[str, Any]:
        """Provide a lightweight DAG description for observability/UX without hitting LLM."""
        return {
            "nodes": ["agent", "tools"],
            "edges": [
                {"from": "START", "to": "agent"},
                {"from": "agent", "to": "tools_or_end"},
                {"from": "tools", "to": "agent"},
                {"from": "agent", "to": "END"},
            ],
            "max_iterations": self.max_iterations,
            "tools": [tool.name for tool in FINANCIAL_TOOLS],
        }

    def self_check(self) -> Dict[str, Any]:
        """
        Cheap self-check that does not call external LLMs.
        Verifies graph compilation, exposes model/provider, and returns DAG metadata.
        """
        status = {"ready": True, "errors": []}
        try:
            _ = self.describe_graph()
        except Exception as exc:
            status["ready"] = False
            status["errors"].append(str(exc))

        return {
            "ready": status["ready"],
            "provider": self.provider,
            "model": self.model,
            "graph": self.describe_graph(),
            "errors": status["errors"],
            "recent_trace": self.get_recent_trace(10),
        }

    def get_agent_info(self) -> Dict[str, Any]:
        """Expose runtime config for dashboards and tests."""

        return {
            "framework": "LangGraph (MessagesState + ToolNode)",
            "provider": self.provider,
            "model": self.model,
            "max_iterations": self.max_iterations,
            "tools_count": len(FINANCIAL_TOOLS),
            "tools": [tool.name for tool in FINANCIAL_TOOLS],
            "supports_tracing": True,
        }

    def get_recent_trace(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the latest tool/chain events for diagnostics."""
        trace = self.callback.events or self.last_trace
        return trace[-limit:] if trace else []


def create_financial_agent(
    provider: str = "gemini_proxy",
    model: Optional[str] = None,
    verbose: bool = True,
    max_iterations: int = 20,
    llm: Optional[Any] = None,
    orchestrator: Optional[Any] = None,
) -> LangChainFinancialAgent:
    """Factory wrapper to match previous interface."""

    return LangChainFinancialAgent(
        provider=provider,
        model=model,
        verbose=verbose,
        max_iterations=max_iterations,
        llm=llm,
        orchestrator=orchestrator,
    )


__all__ = [
    "LangChainFinancialAgent",
    "create_financial_agent",
    "FinancialAnalysisCallback",
]
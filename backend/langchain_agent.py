#!/usr/bin/env python3
"""
Modern LangGraph-based financial agent for FinSight.

- Uses MessagesState + ToolNode from langgraph
- Binds typed LangChain tools for reliable tool-calling
- Keeps a lightweight in-memory checkpoint so threads can be resumed
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from dotenv import load_dotenv
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage, HumanMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableLambda
from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, MessagesState, StateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from langchain_tools import FINANCIAL_TOOLS, get_tools_description

load_dotenv()


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
"""


class FinancialAnalysisCallback(BaseCallbackHandler):
    """Lightweight callback to log tool usage and steps."""

    def __init__(self, verbose: bool = True) -> None:
        self.verbose = verbose
        self.step_count = 0

    def on_tool_start(self, serialized: Dict[str, Any], input_str: str, **_: Any) -> None:
        self.step_count += 1
        if self.verbose:
            name = serialized.get("name", "tool")
            preview = input_str if len(input_str) < 160 else input_str[:157] + "..."
            print(f"[Tool {self.step_count}] {name} | input={preview}")

    def on_tool_end(self, output: Any, **_: Any) -> None:
        if self.verbose:
            output_str = str(output)
            preview = output_str if len(output_str) < 200 else output_str[:197] + "..."
            print(f"[Tool {self.step_count}] result={preview}")


class LangChainFinancialAgent:
    """LangGraph-powered financial agent with typed tool binding."""

    def __init__(
        self,
        provider: str = "gemini_proxy",
        model: Optional[str] = None,
        verbose: bool = True,
        max_iterations: int = 20,
        llm: Optional[Any] = None,
        checkpointer: Optional[MemorySaver] = None,
    ) -> None:
        self.provider = provider
        self.model = model or self._resolve_model()
        self.verbose = verbose
        self.max_iterations = max_iterations
        self.checkpointer = checkpointer or MemorySaver()
        self.callback = FinancialAnalysisCallback(verbose=verbose)
        self.llm = llm or self._create_llm()
        self.system_prompt = self._build_system_prompt()
        self.graph = self._build_graph()

    def _resolve_model(self) -> str:
        try:
            from backend.config import get_llm_config  # type: ignore

            cfg = get_llm_config(provider=self.provider)
            return cfg.get("model", "gemini-2.5-flash")
        except Exception:
            return "gemini-2.5-flash"

    def _create_llm(self) -> ChatOpenAI:
        api_key = os.getenv("GEMINI_PROXY_API_KEY")
        api_base = os.getenv("GEMINI_PROXY_API_BASE", "https://x666.me/v1")

        if not api_key:
            raise ValueError("GEMINI_PROXY_API_KEY is missing; set it in .env")

        return ChatOpenAI(
            model=self.model,
            openai_api_key=api_key,
            openai_api_base=api_base,
            temperature=0.0,
            max_tokens=4000,
            request_timeout=120,
        )

    def _build_system_prompt(self) -> str:
        current_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        tools_desc = get_tools_description()
        return CIO_SYSTEM_PROMPT.format(current_date=current_date, tools=tools_desc)

    def _build_graph(self):
        prompt = ChatPromptTemplate.from_messages(
            [
                ("system", self.system_prompt),
                ("placeholder", "{messages}"),
            ]
        )

        agent_node = (
            prompt
            | self.llm.bind_tools(FINANCIAL_TOOLS)
            | RunnableLambda(
                lambda msg: {"messages": [msg]} if not isinstance(msg, dict) else msg
            )
        )
        workflow = StateGraph(MessagesState)
        workflow.add_node("agent", agent_node)
        workflow.add_node("tools", ToolNode(FINANCIAL_TOOLS))
        workflow.add_edge(START, "agent")
        workflow.add_conditional_edges(
            "agent",
            tools_condition,
            {"tools": "tools", "__end__": END},
        )
        workflow.add_edge("tools", "agent")
        workflow.set_entry_point("agent")

        return workflow.compile(checkpointer=self.checkpointer)

    def analyze(
        self,
        query: str,
        thread_id: Optional[str] = None,
        stream: bool = False,
    ) -> Dict[str, Any]:
        """Run the LangGraph agent on a single query."""

        self.callback.step_count = 0
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
                            print(f"[Stream] {getattr(last, 'type', 'msg')}: {getattr(last, 'content', '')[:160]}")
            else:
                final_state = self.graph.invoke(initial_state, config=config)

            messages: List[BaseMessage] = final_state.get("messages", [])
            output = messages[-1].content if messages else "No output generated"

            return {
                "success": True,
                "output": output,
                "messages": messages,
                "step_count": self.callback.step_count,
                "thread_id": run_id,
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "step_count": self.callback.step_count,
                "thread_id": run_id,
            }

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
        }


def create_financial_agent(
    provider: str = "gemini_proxy",
    model: Optional[str] = None,
    verbose: bool = True,
    max_iterations: int = 20,
    llm: Optional[Any] = None,
) -> LangChainFinancialAgent:
    """Factory wrapper to match previous interface."""

    return LangChainFinancialAgent(
        provider=provider,
        model=model,
        verbose=verbose,
        max_iterations=max_iterations,
        llm=llm,
    )


__all__ = [
    "LangChainFinancialAgent",
    "create_financial_agent",
    "FinancialAnalysisCallback",
]

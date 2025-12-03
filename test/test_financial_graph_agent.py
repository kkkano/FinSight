"""Smoke tests for the LangGraph-based financial agent.

These tests avoid real network/LLM calls by injecting a dummy chat model.
"""

import os
import sys

from langchain_core.messages import AIMessage

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.langchain_agent import LangChainFinancialAgent


class DummyChatModel:
    """Minimal chat model stub that satisfies the Runnable interface."""

    def __init__(self, content: str = "ok") -> None:
        self.content = content

    def bind_tools(self, tools):
        # In tests we ignore tool schemas; returning self keeps the interface compatible.
        return self

    def __call__(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke(self, _input, config=None, **kwargs):
        # LangGraph expects a BaseMessage from the model.
        return AIMessage(content=self.content)


def test_agent_invokes_graph_without_real_llm():
    agent = LangChainFinancialAgent(llm=DummyChatModel("analysis-complete"), verbose=False)
    result = agent.analyze("test query", thread_id="test-thread")

    assert result["success"] is True
    assert "analysis-complete" in result["output"]
    assert result["step_count"] == 0
    assert result["thread_id"] == "test-thread"

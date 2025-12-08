"""
Self-check tests for LangGraph agent wiring without real LLM calls.
"""

import os
import sys

from langchain_core.messages import AIMessage

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from backend.langchain_agent import LangChainFinancialAgent


class DummyChatModel:
    """Minimal chat model stub that satisfies the Runnable interface."""

    def __init__(self, content: str = "ok") -> None:
        self.content = content

    def bind_tools(self, tools):
        # Returning self keeps pipeline compatible with prompt | llm.bind_tools
        return self

    def __call__(self, *args, **kwargs):
        return self.invoke(*args, **kwargs)

    def invoke(self, _input, config=None, **kwargs):
        return AIMessage(content=self.content)


def test_langgraph_self_check_and_describe():
    agent = LangChainFinancialAgent(llm=DummyChatModel("ok"), verbose=False)

    desc = agent.describe_graph()
    assert desc["nodes"] == ["agent", "tools"]
    assert any(edge["from"] == "agent" for edge in desc["edges"])
    assert desc["max_iterations"] == agent.max_iterations

    status = agent.self_check()
    assert status["ready"] is True
    assert status["graph"]["nodes"] == ["agent", "tools"]
    assert status["provider"] == agent.provider

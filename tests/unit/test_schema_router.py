import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.conversation import schema_router


class DummyLLM:
    def __init__(self, content: str):
        self._content = content

    def invoke(self, messages):
        return type("Resp", (), {"content": self._content})()


class DummyContext:
    def __init__(self):
        self.pending_tool_call = None

    def get_summary(self):
        return ""


@pytest.mark.skipif(
    not schema_router.LANGCHAIN_AVAILABLE,
    reason="langchain_core not available",
)
def test_missing_required_fields_detected():
    missing = schema_router.SchemaToolRouter._get_missing_required_fields(
        schema_router.AnalyzeStock, {"ticker": None}
    )
    assert missing
    assert missing[0]["field"] == "ticker"


@pytest.mark.skipif(
    not schema_router.LANGCHAIN_AVAILABLE,
    reason="langchain_core not available",
)
def test_route_clarify_then_execute():
    llm = DummyLLM('{"tool_name":"get_price","args":{"ticker":null}}')
    router = schema_router.SchemaToolRouter(llm)
    context = DummyContext()

    result = router.route_query("help me check the price", context)
    assert result is not None
    assert result.intent == "clarify"
    assert context.pending_tool_call is not None

    result = router.route_query("TSLA", context)
    assert result is not None
    assert result.metadata.get("schema_action") == "execute"
    assert "TSLA" in result.metadata.get("tickers", [])


@pytest.mark.skipif(
    not schema_router.LANGCHAIN_AVAILABLE,
    reason="langchain_core not available",
)
def test_unknown_tool_falls_back():
    llm = DummyLLM('{"tool_name":"unknown_tool","args":{}}')
    router = schema_router.SchemaToolRouter(llm)
    context = DummyContext()

    result = router.route_query("test", context)
    assert result is None

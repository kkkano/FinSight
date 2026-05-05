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
    llm = DummyLLM('{"tool_name":"get_price","args":{"ticker":null},"confidence":0.9}')
    router = schema_router.SchemaToolRouter(llm)
    context = DummyContext()

    result = router.route_query("help me check the price", context)
    assert result is not None
    assert result.intent == "clarify"
    assert result.metadata.get("schema_action") == "clarify"
    assert result.metadata.get("schema_missing")[0]["field"] == "ticker"
    assert result.metadata.get("source") == "schema_router"
    assert context.pending_tool_call is not None

    result = router.route_query("TSLA", context)
    assert result is not None
    assert result.metadata.get("schema_action") == "execute"
    assert result.metadata.get("schema_args", {}).get("ticker") == "TSLA"
    assert "TSLA" in result.metadata.get("tickers", [])


@pytest.mark.skipif(
    not schema_router.LANGCHAIN_AVAILABLE,
    reason="langchain_core not available",
)
def test_company_name_needs_intent_action():
    llm = DummyLLM('{"tool_name":"get_market_sentiment","args":{},"confidence":0.9}')
    router = schema_router.SchemaToolRouter(llm)
    context = DummyContext()

    result = router.route_query("特斯拉", context)
    assert result is not None
    assert result.metadata.get("schema_action") == "clarify"
    missing = result.metadata.get("schema_missing") or []
    assert any(item.get("field") == "intent" for item in missing)


@pytest.mark.skipif(
    not schema_router.LANGCHAIN_AVAILABLE,
    reason="langchain_core not available",
)
def test_complete_query_executes_without_clarify():
    llm = DummyLLM('{"tool_name":"get_price","args":{"ticker":"TSLA"},"confidence":0.95}')
    router = schema_router.SchemaToolRouter(llm)
    context = DummyContext()

    result = router.route_query("查一下特斯拉的股价", context)
    assert result is not None
    assert result.metadata.get("schema_action") == "execute"
    assert "TSLA" in result.metadata.get("tickers", [])


@pytest.mark.skipif(
    not schema_router.LANGCHAIN_AVAILABLE,
    reason="langchain_core not available",
)
def test_unknown_tool_falls_back():
    llm = DummyLLM('{"tool_name":"unknown_tool","args":{},"confidence":0.9}')
    router = schema_router.SchemaToolRouter(llm)
    context = DummyContext()

    result = router.route_query("test", context)
    assert result is not None
    assert result.intent == "clarify"
    assert result.metadata.get("clarify_reason") == "unknown_tool"

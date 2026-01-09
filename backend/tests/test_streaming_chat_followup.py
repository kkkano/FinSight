import asyncio

from backend.conversation.context import ContextManager
from backend.handlers.chat_handler import ChatHandler
from backend.handlers.followup_handler import FollowupHandler


class StubChunk:
    def __init__(self, content: str):
        self.content = content


class StubLLM:
    def __init__(self, tokens):
        self.tokens = tokens
        self.invoked = False

    async def astream(self, messages):
        for token in self.tokens:
            yield StubChunk(token)

    def invoke(self, messages):
        self.invoked = True

        class Response:
            def __init__(self, content: str):
                self.content = content

        return Response("fallback")


async def _collect_tokens(generator):
    tokens = []
    async for token in generator:
        tokens.append(token)
    return tokens


def test_chat_handler_stream_with_llm(monkeypatch):
    handler = ChatHandler(llm=StubLLM(["A", "B"]), orchestrator=None)
    monkeypatch.setattr(
        handler,
        "handle",
        lambda q, m, c: {"success": True, "response": "base", "intent": "chat"},
    )

    result_container = {}
    tokens = asyncio.run(
        _collect_tokens(handler.stream_with_llm("hello", {}, None, result_container))
    )

    assert "".join(tokens) == "AB"
    assert result_container["response"] == "AB"
    assert result_container["enhanced_by_llm"] is True


def test_followup_handler_stream_with_llm():
    context = ContextManager()
    context.add_turn(query="Q1", intent="chat", response="previous", metadata={})
    context.get_last_long_response = lambda: None

    handler = FollowupHandler(llm=StubLLM(["x", "y"]), orchestrator=None)
    result_container = {}
    tokens = asyncio.run(
        _collect_tokens(handler.stream_with_llm("why", {}, context, result_container))
    )

    assert "".join(tokens) == "xy"
    assert result_container["response"] == "xy"
    assert result_container["intent"] == "followup"

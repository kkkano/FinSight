from fastapi.testclient import TestClient

from backend.conversation.router import Intent


class StubContext:
    def __init__(self):
        self.current_focus = "AAPL"
        self.resolved_calls = []

    def resolve_reference(self, query: str) -> str:
        self.resolved_calls.append(query)
        return query.replace("它", "AAPL")

    def add_turn(self, **_kwargs):
        return None


class StubRouter:
    def __init__(self):
        self.last_query = None

    def route(self, query, _context):
        self.last_query = query

        def handler(resolved_query, _metadata):
            return {"success": True, "response": f"ok:{resolved_query}", "intent": "chat"}

        return Intent.CHAT, {"tickers": ["AAPL"]}, handler


class StubAgent:
    def __init__(self):
        self.context = StubContext()
        self.router = StubRouter()
        self.chat_handler = object()
        self.followup_handler = object()
        self.stats = {"total_queries": 0, "intents": {}, "errors": 0}

    def _add_chart_marker(self, result, *_args, **_kwargs):
        return result

    def _default_handler(self, *_args, **_kwargs):
        return {"success": True, "response": "default", "intent": "chat"}


def test_chat_stream_resolves_reference(monkeypatch):
    import backend.api.main as main

    stub_agent = StubAgent()
    monkeypatch.setattr(main, "agent", stub_agent)

    client = TestClient(main.app)
    with client.stream("POST", "/chat/stream", json={"query": "它的行情"}) as response:
        assert response.status_code == 200
        _ = [line for line in response.iter_lines() if line]

    assert stub_agent.router.last_query == "AAPL的行情"

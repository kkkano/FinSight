# -*- coding: utf-8 -*-
"""
Router greeting fast-path should bypass SchemaToolRouter.
"""

from backend.conversation.router import ConversationRouter, Intent


class DummyContext:
    def get_summary(self) -> str:
        return ""

    def get_last_long_response(self):
        return None


class SpySchemaRouter:
    def __init__(self):
        self.calls = 0

    def route_query(self, query, context):
        self.calls += 1
        return None


def test_greeting_bypasses_schema_router():
    router = ConversationRouter(llm=None)
    spy = SpySchemaRouter()
    router._schema_router = spy

    intent, _metadata, _handler = router.route("你好", DummyContext())

    assert intent == Intent.GREETING
    assert spy.calls == 0


def test_schema_router_called_for_ambiguous_query():
    """
    When _quick_match() returns None (ambiguous query),
    SchemaRouter should be called.
    """
    router = ConversationRouter(llm=None)
    spy = SpySchemaRouter()
    router._schema_router = spy

    # "苹果公司怎么样" returns None from _quick_match (ambiguous intent)
    router.route("苹果公司怎么样", DummyContext())

    assert spy.calls == 1


def test_quick_match_bypasses_schema_router():
    """
    When _quick_match() returns a high-confidence intent (not CLARIFY),
    SchemaRouter should NOT be called - this is the fast-path optimization.
    """
    router = ConversationRouter(llm=None)
    spy = SpySchemaRouter()
    router._schema_router = spy

    # "AAPL 股价" is recognized as CHAT by _quick_match (has ticker + price context)
    intent, _metadata, _handler = router.route("AAPL 股价", DummyContext())

    assert intent == Intent.CHAT
    assert spy.calls == 0  # Fast-path bypassed SchemaRouter


def test_repeated_query_routes_consistently():
    router = ConversationRouter(llm=None)
    router._schema_router = SpySchemaRouter()

    intents = [router.route("苹果公司怎么样", DummyContext())[0] for _ in range(3)]
    assert len(set(intents)) == 1

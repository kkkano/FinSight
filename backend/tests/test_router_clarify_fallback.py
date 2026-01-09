from backend.conversation.router import ConversationRouter, Intent


class _StubResponse:
    def __init__(self, content: str):
        self.content = content


class _StubLLM:
    def __init__(self, content: str):
        self._content = content

    def invoke(self, _messages):
        return _StubResponse(self._content)


def test_followup_without_context_sets_clarify_reason():
    router = ConversationRouter(llm=None)
    intent, metadata = router.classify_intent("\u4e3a\u4ec0\u4e48")
    assert intent == Intent.CLARIFY
    assert metadata.get("clarify_reason") == "followup_without_context"


def test_llm_fallback_runs_for_financial_clarify():
    router = ConversationRouter(llm=_StubLLM("CHAT"))
    intent, _metadata = router.classify_intent("\u4e3a\u4ec0\u4e48\u5e02\u573a\u4e0b\u8dcc")
    assert intent == Intent.CHAT

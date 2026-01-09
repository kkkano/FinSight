from backend.conversation.router import ConversationRouter, Intent


def test_market_news_queries_route_to_chat():
    router = ConversationRouter(llm=None)

    queries = [
        "\u6700\u8fd1\u5e02\u573a\u70ed\u70b9\u662f\u4ec0\u4e48",
        "\u5e02\u573a\u70ed\u70b9 \u65b0\u95fb",
        "\u80a1\u5e02\u5feb\u8baf",
        "market news today",
    ]

    for query in queries:
        intent, _metadata = router.classify_intent(query)
        assert intent == Intent.CHAT, f"Expected CHAT for query: {query}"

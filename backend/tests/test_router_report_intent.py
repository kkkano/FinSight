from backend.conversation.router import ConversationRouter, Intent


def test_report_intent_keywords_stable():
    router = ConversationRouter()

    queries = [
        "写一份研报",
        "做一份投研报告",
        "基本面分析一下特斯拉",
        "估值分析苹果",
        "公司研究：英伟达",
    ]

    for query in queries:
        intent, _metadata = router.classify_intent(query)
        assert intent == Intent.REPORT, f"Expected REPORT for query: {query}"

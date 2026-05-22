# -*- coding: utf-8 -*-
from backend.graph.investment_intent import query_requests_investment_opinion


def test_investment_opinion_intent_matches_semantic_patterns():
    positive_queries = [
        "INTC 最近走势如何 看好么",
        "NVDA 走势怎么看",
        "AAPL 值得买吗",
        "TSLA 后市怎么操作",
        "MSFT 短中期风险机会怎么看",
        "Should I buy AMD shares here?",
        "What is your bullish or bearish view on NVDA?",
    ]

    for query in positive_queries:
        assert query_requests_investment_opinion(query), query


def test_investment_opinion_intent_avoids_plain_news_and_price_queries():
    negative_queries = [
        "AAPL 最新新闻有哪些",
        "NVDA 当前价格是多少",
        "INTC 财报发布日期",
        "帮我总结这个链接",
        "美联储利率路径对科技股估值有什么影响",
    ]

    for query in negative_queries:
        assert not query_requests_investment_opinion(query), query

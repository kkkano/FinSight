# -*- coding: utf-8 -*-
from backend.graph.earnings_intent import (
    query_requests_earnings_performance,
    query_requests_earnings_price_impact,
)


def test_earnings_performance_intent_matches_report_result_questions() -> None:
    positive = [
        "英伟达最新季度财报表现如何",
        "AAPL 最新财报怎么样",
        "MSFT revenue EPS margin 这个季度如何",
        "NVDA latest quarterly earnings performance",
        "Did AMD earnings beat or miss expectations?",
    ]

    for query in positive:
        assert query_requests_earnings_performance(query), query


def test_earnings_performance_intent_avoids_calendar_news_and_price_queries() -> None:
    negative = [
        "INTC 财报发布日期",
        "AAPL earnings calendar",
        "NVDA 当前价格是多少",
        "AAPL 最新新闻有哪些",
        "TSLA 走势怎么看",
    ]

    for query in negative:
        assert not query_requests_earnings_performance(query), query


def test_earnings_price_impact_intent_matches_event_to_price_questions() -> None:
    positive = [
        "英伟达这个季度财报对股价的影响",
        "请问英伟达这个季度财报对股价的影响",
        "NVDA earnings impact on stock price",
        "How did Nvidia quarterly results affect shares?",
        "AAPL 财报出来后对走势是利好还是利空",
    ]

    for query in positive:
        assert query_requests_earnings_price_impact(query), query


def test_earnings_price_impact_intent_avoids_plain_price_or_earnings_questions() -> None:
    negative = [
        "NVDA 当前价格是多少",
        "英伟达最新季度财报表现如何",
        "AAPL earnings calendar",
        "TSLA 走势怎么看",
    ]

    for query in negative:
        assert not query_requests_earnings_price_impact(query), query

# -*- coding: utf-8 -*-
from backend.graph.nodes.parse_operation import parse_operation


def test_parse_operation_compare():
    result = parse_operation({"query": "AAPL vs MSFT 哪个更好", "subject": {"subject_type": "company"}})
    op = result.get("operation") or {}
    assert op.get("name") == "compare"


def test_parse_operation_summarize():
    result = parse_operation({"query": "总结这条新闻要点", "subject": {"subject_type": "news_item"}})
    op = result.get("operation") or {}
    assert op.get("name") == "summarize"


def test_parse_operation_analyze_impact():
    result = parse_operation({"query": "分析对股价影响", "subject": {"subject_type": "news_item"}})
    op = result.get("operation") or {}
    assert op.get("name") == "analyze_impact"


def test_parse_operation_extract_metrics_for_filing():
    result = parse_operation({"query": "从财报抽取营收和利润", "subject": {"subject_type": "filing"}})
    op = result.get("operation") or {}
    assert op.get("name") == "extract_metrics"


def test_parse_operation_fetch():
    result = parse_operation({"query": "今天有什么新闻", "subject": {"subject_type": "company"}})
    op = result.get("operation") or {}
    assert op.get("name") == "fetch"


def test_parse_operation_price_over_latest_news():
    # "最新" should not override explicit price intent.
    result = parse_operation({"query": "NVDA 最新股价是多少", "subject": {"subject_type": "company"}})
    op = result.get("operation") or {}
    assert op.get("name") == "price"


def test_parse_operation_technical_over_latest_news():
    # "最新" should not override explicit technical intent.
    result = parse_operation({"query": "NVDA 最新股价和技术面分析", "subject": {"subject_type": "company"}})
    op = result.get("operation") or {}
    assert op.get("name") == "technical"

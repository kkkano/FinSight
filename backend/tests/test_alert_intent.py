# -*- coding: utf-8 -*-
from backend.graph.nodes.parse_operation import parse_operation


def test_parse_operation_detects_alert_set_cn_target():
    result = parse_operation(
        {
            "query": "平安银行涨到12元提醒我",
            "subject": {"subject_type": "company", "tickers": ["000001.SZ"]},
        }
    )
    assert result["operation"]["name"] == "alert_set"
    decision = (result.get("trace") or {}).get("operation_decision") or {}
    assert decision.get("guardrail_a_hit") == "alert_set"


def test_parse_operation_detects_alert_set_en_phrase():
    result = parse_operation(
        {
            "query": "notify me when it reaches 220",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        }
    )
    assert result["operation"]["name"] == "alert_set"


def test_parse_operation_alert_priority_over_price_keyword():
    result = parse_operation(
        {
            "query": "AAPL 涨到 220 的时候提醒我，并告诉我当前 price",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        }
    )
    assert result["operation"]["name"] == "alert_set"

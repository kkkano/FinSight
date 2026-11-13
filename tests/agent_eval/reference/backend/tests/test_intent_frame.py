# -*- coding: utf-8 -*-
"""WP2-T1：IntentFrame 单一意图源模型与 legacy 无损适配器。"""
from backend.graph.intent.frame import (
    IntentFrame,
    IntentTask,
    intent_frame_from_legacy,
    legacy_understanding_from_frame,
)


def test_roundtrip_legacy_understanding():
    legacy = {
        "route": "research",
        "original_query": "对比 AAPL 和 MSFT",
        "language": "zh",
        "tasks": [{
            "id": "t1", "subject_type": "company", "subject_label": "AAPL, MSFT",
            "tickers": ["AAPL", "MSFT"],
            "operation": {"name": "compare", "confidence": 0.86, "params": {}},
            "priority": 20, "reason": "multi_ticker_compare",
        }],
        "blocked_tasks": [], "context_refs": [], "fallback_assumptions": [],
    }
    frame = intent_frame_from_legacy(legacy)
    assert frame.route == "research"
    assert frame.tasks[0].operation == "compare"
    assert frame.tasks[0].operation_confidence == 0.86

    back = legacy_understanding_from_frame(frame)
    assert back["route"] == "research"
    assert back["tasks"][0]["operation"]["name"] == "compare"
    assert back["tasks"][0]["tickers"] == ["AAPL", "MSFT"]
    # user_visible_summary 规则与 understand_request 现状一致
    assert back["user_visible_summary"] == "AAPL, MSFT:compare"


def test_required_evidence_absorbed_from_contract():
    legacy = {"route": "research", "original_query": "q", "tasks": [
        {"id": "t1", "subject_type": "company", "tickers": ["AAPL"],
         "operation": {"name": "investment_opinion", "confidence": 0.8}, "priority": 25, "reason": "x"},
    ], "blocked_tasks": []}
    contract = {"required_evidence": ["price_snapshot", "recent_news"], "primary_tickers": ["AAPL"]}
    frame = intent_frame_from_legacy(legacy, intent_contract=contract)
    assert frame.tasks[0].required_evidence == ["price_snapshot", "recent_news"]


def test_route_inference_and_blocked():
    legacy = {
        "original_query": "帮我分析一下",
        "tasks": [],
        "blocked_tasks": [{
            "id": "blocked_1", "reason": "missing_analysis_target",
            "question": "需要分析对象。", "suggestions": ["输入 ticker"], "fallback_allowed": False,
        }],
    }
    frame = intent_frame_from_legacy(legacy)
    assert frame.route == "clarify"
    assert frame.blocked[0].reason == "missing_analysis_target"
    back = legacy_understanding_from_frame(frame)
    assert back["blocked_tasks"][0]["question"] == "需要分析对象。"
    assert back["user_visible_summary"] == "阻塞项:1"


def test_frame_defaults():
    frame = IntentFrame(route="direct", query="PE 是什么")
    assert frame.schema_version == "intent_frame/v1"
    assert frame.source == "rules_fallback"
    assert frame.tasks == []
    task = IntentTask(id="t1", subject_type="company", operation="price")
    assert task.priority == 50 and task.params == {}

# -*- coding: utf-8 -*-
from backend.graph.nodes.render_node import render_node


def test_supporting_news_does_not_replace_explicit_technical_answer():
    result = render_node({
        "query": "AAPL 的短线趋势、RSI、MACD 和支撑阻力怎么看？",
        "output_mode": "chat",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "operation": {"name": "technical"},
        "tasks": [{"id": "task_1", "tickers": ["AAPL"], "subject_type": "company",
                   "operation": {"name": "technical"}}],
        "plan_ir": {"steps": [
            {"id": "technical", "kind": "tool", "name": "get_technical_snapshot", "inputs": {"ticker": "AAPL"}},
            {"id": "news", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "AAPL"}},
        ]},
        "artifacts": {"step_results": {
            "technical": {"output": {"summary": "RSI(14) 65；MACD 多头；支撑 320；阻力 345；趋势偏强"}},
            "news": {"output": [{"title": "Apple latest update", "url": "https://example.com/apple"}]},
        }},
    })
    markdown = result["artifacts"]["draft_markdown"]
    assert "技术面结论" in markdown
    assert "RSI(14) 65" in markdown
    assert "MACD" in markdown
    assert "支撑 320" in markdown
    assert "阻力 345" in markdown
    assert "舆情简报" not in markdown

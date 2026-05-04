# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.graph.nodes.decide_output_mode import decide_output_mode
from backend.graph.nodes.render_stub import render_stub


FORBIDDEN_CHAT_MARKERS = (
    "问题：",
    "后续关注：",
    "本轮问题包含",
    "get_stock_price",
    "get_company_news",
    "Suggested ladder",
    "暂无技术指标",
    "分析对象",
)


def _render_chat(state: dict) -> str:
    result = render_stub(
        {
            "query": state.get("query", ""),
            "output_mode": "chat",
            "subject": state.get("subject", {"subject_type": "company", "tickers": ["NVDA"]}),
            "operation": state.get("operation", {"name": "qa"}),
            "tasks": state.get("tasks", []),
            "memory_context": state.get("memory_context", {}),
            "artifacts": state.get("artifacts", {}),
            "plan_ir": state.get("plan_ir", {"steps": []}),
        }
    )
    return result["artifacts"]["draft_markdown"]


def _assert_chat_contract(markdown: str) -> None:
    assert markdown.strip()
    for marker in FORBIDDEN_CHAT_MARKERS:
        assert marker not in markdown


def test_default_output_mode_is_chat_not_brief() -> None:
    assert decide_output_mode({"query": "英伟达（NVDA）今天多少钱"})["output_mode"] == "chat"


def test_report_words_still_trigger_investment_report() -> None:
    assert decide_output_mode({"query": "请做 Apple 深度投资报告"})["output_mode"] == "investment_report"


def test_price_chat_answer_does_not_leak_tool_or_template_terms() -> None:
    markdown = _render_chat(
        {
            "query": "英伟达（NVDA）今天多少钱",
            "operation": {"name": "price"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["NVDA"],
                    "operation": {"name": "price"},
                }
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "NVDA"}},
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {
                        "output": {
                            "price": 912.34,
                            "change": 8.12,
                            "change_percent": 0.9,
                            "currency": "USD",
                            "as_of": "2026-05-04T20:00:00Z",
                        }
                    }
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "NVDA" in markdown
    assert "912.34" in markdown


def test_news_chat_answer_uses_clean_citations() -> None:
    markdown = _render_chat(
        {
            "query": "特斯拉最新关键新闻（24小时）及对股价影响的解读",
            "subject": {"subject_type": "company", "tickers": ["TSLA"]},
            "operation": {"name": "fetch"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["TSLA"],
                    "operation": {"name": "fetch"},
                },
                {
                    "id": "task_2",
                    "subject_type": "company",
                    "tickers": ["TSLA"],
                    "operation": {"name": "analyze_impact"},
                },
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "TSLA"}},
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {
                        "output": [
                            {
                                "title": "Tesla shares move after delivery update",
                                "url": "https://example.com/tesla-delivery",
                                "source": "Example News",
                                "published_at": "2026-05-04T10:00:00Z",
                            }
                        ]
                    }
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "Tesla shares move after delivery update" in markdown
    assert "[Tesla shares move after delivery update](https://example.com/tesla-delivery)" in markdown


def test_technical_chat_missing_data_is_natural() -> None:
    markdown = _render_chat(
        {
            "query": "英伟达（NVDA）技术面分析：RSI、MACD、关键支撑阻力位",
            "operation": {"name": "technical"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["NVDA"],
                    "operation": {"name": "technical"},
                }
            ],
        }
    )

    _assert_chat_contract(markdown)
    assert "没有拿到" in markdown
    assert "RSI" in markdown


def test_report_followup_chat_uses_last_report_context_without_report_mode() -> None:
    markdown = _render_chat(
        {
            "query": "刚才那份报告里最大的风险是什么？",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
            "operation": {"name": "qa"},
            "artifacts": {},
            "memory_context": {
                "last_report": {
                    "report_id": "rpt-ctx-001",
                    "title": "Apple investment report",
                    "summary": "Apple report summary.",
                    "risks": [
                        "Valuation remains sensitive to rates.",
                        "China demand can pressure revenue.",
                    ],
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "Apple investment report" in markdown
    assert "Valuation remains sensitive to rates." in markdown

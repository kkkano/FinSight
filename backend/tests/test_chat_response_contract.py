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
    "get_company_info",
    "Suggested ladder",
    "output（）",
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


def test_chat_renderer_uses_tool_data_instead_of_existing_fallback_draft() -> None:
    markdown = _render_chat(
        {
            "query": "NVDA 今天多少钱？",
            "subject": {"subject_type": "company", "tickers": ["NVDA"]},
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
                "draft_markdown": "我理解你的问题是：NVDA 今天多少钱。",
                "step_results": {
                    "s1": {
                        "output": {
                            "ticker": "NVDA",
                            "price": 912.34,
                            "change": 8.12,
                            "change_percent": 0.9,
                            "currency": "USD",
                        }
                    }
                },
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "912.34" in markdown
    assert "我理解你的问题是" not in markdown


def test_chat_renderer_multiticker_price_answer_lists_each_quote() -> None:
    markdown = _render_chat(
        {
            "query": "苹果、微软、谷歌现在分别多少？",
            "subject": {"subject_type": "company", "tickers": ["AAPL", "GOOGL", "MSFT"]},
            "operation": {"name": "price"},
            "tasks": [
                {"id": "task_1", "subject_type": "company", "tickers": ["AAPL"], "operation": {"name": "price"}},
                {"id": "task_2", "subject_type": "company", "tickers": ["GOOGL"], "operation": {"name": "price"}},
                {"id": "task_3", "subject_type": "company", "tickers": ["MSFT"], "operation": {"name": "price"}},
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "AAPL"}},
                    {"id": "s2", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "GOOGL"}},
                    {"id": "s3", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "MSFT"}},
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {"output": {"ticker": "AAPL", "price": 276.83, "change": -3.42, "change_percent": -1.22}},
                    "s2": {"output": {"ticker": "GOOGL", "price": 383.25, "change": -2.44, "change_percent": -0.63}},
                    "s3": {"output": {"ticker": "MSFT", "price": 513.24, "change": 1.1, "change_percent": 0.21}},
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "AAPL" in markdown and "276.83" in markdown
    assert "GOOGL" in markdown and "383.25" in markdown
    assert "MSFT" in markdown and "513.24" in markdown
    assert "历史回报" not in markdown


def test_chat_renderer_compound_news_answer_keeps_unrelated_price_and_focus_line() -> None:
    markdown = _render_chat(
        {
            "query": "AAPL 价格、MSFT 新闻、再解释一下为什么高估值怕利率，最后用一句话说我该关注什么。",
            "subject": {"subject_type": "company", "tickers": ["AAPL", "MSFT"]},
            "operation": {"name": "fetch"},
            "tasks": [
                {"id": "task_1", "subject_type": "company", "tickers": ["AAPL"], "operation": {"name": "price"}},
                {"id": "task_2", "subject_type": "company", "tickers": ["MSFT"], "operation": {"name": "fetch"}},
                {"id": "task_3", "subject_type": "macro", "tickers": [], "operation": {"name": "analyze_impact"}},
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "AAPL"}},
                    {"id": "s2", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "MSFT"}},
                ]
            },
            "artifacts": {
                "render_vars": {
                    "impact_analysis": "高估值怕利率，是因为折现率上升会压低远期现金流现值。",
                },
                "step_results": {
                    "s1": {"output": {"ticker": "AAPL", "price": 276.83, "change": -3.42, "change_percent": -1.22}},
                    "s2": {
                        "output": [
                            {
                                "title": "Microsoft AI spending under scrutiny",
                                "url": "https://example.com/msft-ai",
                                "source": "Example",
                                "published_at": "2026-05-05",
                            }
                        ]
                    },
                },
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "MSFT 我找到几条比较相关的消息" in markdown
    assert "AAPL" in markdown and "276.83" in markdown
    assert "折现率" in markdown
    assert "一句话：" not in markdown


def test_price_chat_parses_string_quote_payload() -> None:
    markdown = _render_chat(
        {
            "query": "MSFT 今天多少钱？",
            "subject": {"subject_type": "company", "tickers": ["MSFT"]},
            "operation": {"name": "price"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["MSFT"],
                    "operation": {"name": "price"},
                }
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "MSFT"}},
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {"output": "MSFT Current Price: $414.19 | Change: +6.17 (+1.51%) | Suggested ladder: $410.05 / $405.91"}
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "MSFT" in markdown
    assert "414.19" in markdown
    assert "1.51%" in markdown


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


def test_news_chat_adds_search_link_when_source_has_no_url() -> None:
    markdown = _render_chat(
        {
            "query": "小米最新新闻",
            "subject": {"subject_type": "company", "tickers": ["XIACY"]},
            "operation": {"name": "fetch"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["XIACY"],
                    "operation": {"name": "fetch"},
                }
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "XIACY"}},
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {
                        "output": [
                            {
                                "title": "Xiaomi EV delivery update",
                                "source": "Search",
                                "published_at": "2026-05-04T08:00:00Z",
                            }
                        ]
                    }
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "[Xiaomi EV delivery update](https://www.google.com/search?q=Xiaomi+EV+delivery+update)" in markdown


def test_news_chat_adds_search_links_when_requested_news_source_is_empty() -> None:
    markdown = _render_chat(
        {
            "query": "给我 3 条 NVDA 最新新闻，要带链接。",
            "subject": {"subject_type": "company", "tickers": ["NVDA"]},
            "operation": {"name": "fetch"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["NVDA"],
                    "operation": {"name": "fetch", "params": {"topic": "news", "count": 3, "include_links": True}},
                }
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "NVDA"}},
                ]
            },
            "artifacts": {"step_results": {"s1": {"output": []}}},
        }
    )

    _assert_chat_contract(markdown)
    assert "硬编新闻" in markdown
    assert markdown.count("](") >= 2
    assert "NVDA" in markdown


def test_compare_chat_without_data_uses_generic_fallback_outside_etf_query() -> None:
    markdown = _render_chat(
        {
            "query": "GOOGL 和 MSFT 今天谁更强，新闻、涨跌幅、风险点各一句。",
            "subject": {"subject_type": "company", "tickers": ["GOOGL", "MSFT"]},
            "operation": {"name": "compare"},
            "tasks": [
                {"id": "task_1", "subject_type": "company", "tickers": ["GOOGL", "MSFT"], "operation": {"name": "compare"}},
            ],
            "artifacts": {"step_results": {}},
        }
    )

    _assert_chat_contract(markdown)
    assert "ETF" not in markdown
    assert "GOOGL, MSFT" in markdown


def test_multiticker_chat_groups_price_and_news_naturally() -> None:
    markdown = _render_chat(
        {
            "query": "谷歌和微软今天谁更强，新闻和涨跌幅各一句",
            "subject": {"subject_type": "company", "tickers": ["GOOGL", "MSFT"]},
            "operation": {"name": "compare"},
            "tasks": [
                {"id": "task_1", "subject_type": "company", "tickers": ["GOOGL"], "operation": {"name": "price"}},
                {"id": "task_2", "subject_type": "company", "tickers": ["GOOGL"], "operation": {"name": "fetch"}},
                {"id": "task_3", "subject_type": "company", "tickers": ["MSFT"], "operation": {"name": "price"}},
                {"id": "task_4", "subject_type": "company", "tickers": ["MSFT"], "operation": {"name": "fetch"}},
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "GOOGL"}, "task_ids": ["task_1"]},
                    {"id": "s2", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "GOOGL"}, "task_ids": ["task_2"]},
                    {"id": "s3", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "MSFT"}, "task_ids": ["task_3"]},
                    {"id": "s4", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "MSFT"}, "task_ids": ["task_4"]},
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {"output": {"price": 180.5, "change": 1.2, "change_percent": 0.67, "currency": "USD"}},
                    "s2": {"output": [{"title": "Google AI product update", "url": "https://example.com/google-ai"}]},
                    "s3": {"output": {"price": 414.19, "change": 6.17, "change_percent": 1.51, "currency": "USD"}},
                    "s4": {"output": [{"title": "Microsoft cloud growth", "url": "https://example.com/msft-cloud"}]},
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "GOOGL" in markdown
    assert "MSFT" in markdown
    assert "180.50" in markdown
    assert "414.19" in markdown
    assert "[Google AI product update](https://example.com/google-ai)" in markdown
    assert "[Microsoft cloud growth](https://example.com/msft-cloud)" in markdown


def test_compare_chat_does_not_leak_low_value_theme_search_when_tickers_exist() -> None:
    markdown = _render_chat(
        {
            "query": "半导体 ETF 能不能看？如果不知道就按 NVDA、AMD、TSM 这几个代表说。",
            "subject": {"subject_type": "company", "tickers": ["NVDA", "AMD", "TSM"]},
            "operation": {"name": "compare"},
            "tasks": [
                {"id": "task_1", "subject_type": "company", "tickers": ["NVDA", "AMD", "TSM"], "operation": {"name": "compare"}},
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "search", "inputs": {"query": "主题/行业"}, "task_ids": ["task_1"]},
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {
                        "output": {
                            "title": "Wikipedia Results for \"特種行業\":",
                            "url": "https://www.google.com/search?q=主题%2F行业",
                            "source": "Wikipedia",
                        }
                    }
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "Wikipedia" not in markdown
    assert "特種行業" not in markdown
    assert "NVDA, AMD, TSM" in markdown
    assert "没有拿到足够" in markdown


def test_representative_etf_qa_renders_lightweight_without_compare_metrics() -> None:
    markdown = _render_chat(
        {
            "query": "先别长篇，半导体 ETF 能不能看？如果不知道就按 NVDA、AMD、TSM 这几个代表说。",
            "subject": {"subject_type": "company", "tickers": ["NVDA", "AMD", "TSM"]},
            "operation": {"name": "qa"},
            "tasks": [
                {"id": "task_1", "subject_type": "company", "tickers": ["NVDA", "AMD", "TSM"], "operation": {"name": "qa"}},
            ],
            "artifacts": {
                "render_vars": {
                    "comparison_conclusion": "\n".join(
                        [
                            "- 我先按 NVDA / AMD / TSM 这组代表标的理解，不把它当成严格绩效排名。",
                            "- 半导体 ETF 可以看，但核心是成分集中度、费率/流动性、周期波动和你能承受的回撤。",
                        ]
                    )
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "NVDA" in markdown
    assert "AMD" in markdown
    assert "TSM" in markdown
    assert "半导体 ETF" in markdown
    assert "YTD" not in markdown


def test_portfolio_chat_uses_visible_positions_without_asking_for_holdings_again() -> None:
    markdown = _render_chat(
        {
            "query": "这些新闻对我的持仓影响大吗？",
            "subject": {"subject_type": "portfolio", "tickers": ["AAPL", "MSFT", "NVDA"]},
            "operation": {"name": "portfolio_impact"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "portfolio",
                    "tickers": ["AAPL", "MSFT", "NVDA"],
                    "operation": {"name": "portfolio_impact"},
                    "params": {
                        "positions": [
                            {"ticker": "AAPL", "weight": 0.35},
                            {"ticker": "MSFT", "weight": 0.25},
                            {"ticker": "NVDA", "weight": 0.15},
                        ]
                    },
                }
            ],
        }
    )

    _assert_chat_contract(markdown)
    assert "AAPL" in markdown
    assert "MSFT" in markdown
    assert "NVDA" in markdown
    assert "需要你的持仓列表" not in markdown
    assert "不会按固定框架" in markdown


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
            "artifacts": {
                "conversation_decision": {
                    "execution_route": "direct_answer",
                    "context_binding": {
                        "source": "last_report",
                        "confidence": 0.9,
                        "reason": "用户接着最近报告追问",
                        "subject_hint": "Apple investment report",
                    },
                    "relation": "follow_up",
                    "domain_intent": "report_discussion",
                    "confidence": 0.9,
                    "needs_tools": False,
                    "reason": "报告上下文可直接回答",
                    "reply_guidance": "",
                }
            },
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


def test_chat_renderer_analyze_impact_news_answer_stays_natural() -> None:
    markdown = _render_chat(
        {
            "query": "理想汽车和 CPI 影响吗",
            "subject": {"subject_type": "company", "tickers": ["LI"]},
            "operation": {"name": "analyze_impact"},
            "tasks": [
                {"id": "task_1", "subject_type": "company", "subject_label": "LI", "tickers": ["LI"], "operation": {"name": "fetch"}},
                {"id": "task_2", "subject_type": "company", "subject_label": "LI", "tickers": ["LI"], "operation": {"name": "analyze_impact"}},
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "LI"}, "task_ids": ["task_1"]},
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {"output": [{"title": "Li Auto delivery update", "url": "https://example.com/li"}]},
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "我找到几条比较相关的消息" in markdown
    assert "[Li Auto delivery update](https://example.com/li)" in markdown
    assert "对股价的影响要看两点" not in markdown


def test_chat_renderer_macro_research_does_not_use_stock_news_template() -> None:
    markdown = _render_chat(
        {
            "query": "美联储降息预期变化会怎么影响大型科技股？",
            "subject": {"subject_type": "macro", "tickers": []},
            "operation": {"name": "analyze_impact"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "macro",
                    "subject_label": "利率路径",
                    "tickers": [],
                    "operation": {"name": "analyze_impact"},
                }
            ],
            "plan_ir": {
                "steps": [
                    {
                        "id": "s1",
                        "kind": "tool",
                        "name": "get_official_macro_releases",
                        "inputs": {"query": "Fed rates"},
                        "task_ids": ["task_1"],
                    },
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {
                        "output": {
                            "releases": [
                                {
                                    "title": "Major Economic Indicators Latest Numbers",
                                    "url": "https://www.bls.gov/bls/",
                                    "source": "BLS",
                                    "published_at": "2026-04-30",
                                }
                            ]
                        }
                    },
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "[Major Economic Indicators Latest Numbers](https://www.bls.gov/bls/)" in markdown
    assert "对股价的影响要看两点" not in markdown
    assert "不硬给" in markdown


def test_chat_renderer_filters_placeholder_evidence_for_risk_followup() -> None:
    markdown = _render_chat(
        {
            "query": "那它的风险主要在哪？",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
            "operation": {"name": "qa"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["AAPL"],
                    "operation": {"name": "qa"},
                }
            ],
            "artifacts": {
                "evidence_pool": [
                    {"title": " output（）", "source": "output"},
                    {"title": "get_company_info", "source": "tool"},
                ]
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "AAPL" in markdown
    assert "风险" in markdown
    assert "增长预期兑现" not in markdown
    assert "可用数据不足" in markdown or "不硬编风险点" in markdown
    assert "相关来源" not in markdown
    assert "仅供参考" not in markdown

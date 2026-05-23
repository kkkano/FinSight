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
            "reply_contract": state.get("reply_contract", {}),
            "intent_contract": state.get("intent_contract"),
            "intent_contracts": state.get("intent_contracts"),
            "artifacts": state.get("artifacts", {}),
            "plan_ir": state.get("plan_ir", {"steps": []}),
            "trace": state.get("trace", {}),
        }
    )
    return result["artifacts"]["draft_markdown"]


def _assert_chat_contract(markdown: str) -> None:
    assert markdown.strip()
    for marker in FORBIDDEN_CHAT_MARKERS:
        assert marker not in markdown


def test_preserved_report_draft_strips_internal_price_ladder_and_template_marker(monkeypatch) -> None:
    monkeypatch.setenv("RENDER_NARRATIVE_MIN_CHARS", "10")
    result = render_stub(
        {
            "query": "给我生成一份 AAPL 投资报告。",
            "output_mode": "investment_report",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
            "operation": {"name": "qa"},
            "artifacts": {
                "draft_markdown": (
                    "## 投资研报：AAPL\n\n"
                    "- AAPL Current Price: $293.32 | Suggested ladder: $290.39 / $287.45\n\n"
                    "**后续关注：**\n- 财报指引\n"
                )
            },
        }
    )

    markdown = result["artifacts"]["draft_markdown"]
    assert "Suggested ladder" not in markdown
    assert "后续关注：" not in markdown
    assert "后续观察" in markdown


def test_report_template_output_strips_template_marker(monkeypatch) -> None:
    monkeypatch.setenv("RENDER_NARRATIVE_MIN_CHARS", "100000")
    result = render_stub(
        {
            "query": "给我生成一份 AAPL 投资报告。",
            "output_mode": "investment_report",
            "subject": {"subject_type": "company", "tickers": ["AAPL"]},
            "operation": {"name": "qa"},
            "artifacts": {
                "render_vars": {
                    "investment_thesis": "**后续关注：**\n- 财报指引",
                }
            },
        }
    )

    markdown = result["artifacts"]["draft_markdown"]
    assert "后续关注：" not in markdown
    assert "后续观察" in markdown


def test_default_output_mode_is_chat_not_brief() -> None:
    assert decide_output_mode({"query": "英伟达（NVDA）今天多少钱"})["output_mode"] == "chat"


def test_report_words_still_trigger_investment_report() -> None:
    assert decide_output_mode({"query": "请做 Apple 深度投资报告"})["output_mode"] == "investment_report"


def test_generic_economic_report_is_not_investment_report() -> None:
    assert (
        decide_output_mode({"query": "Why might US stocks rally after a weak jobs report? Keep it conversational."})[
            "output_mode"
        ]
        == "chat"
    )


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
    assert "最近新闻" in markdown
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


def test_technical_chat_renders_clean_actionable_short_answer() -> None:
    markdown = _render_chat(
        {
            "query": "INTC 技术面怎么样？给出可执行结论。",
            "subject": {"subject_type": "company", "tickers": ["INTC"]},
            "operation": {"name": "technical"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["INTC"],
                    "operation": {"name": "technical"},
                }
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "INTC"}},
                    {"id": "s3", "kind": "agent", "name": "technical_agent", "inputs": {"ticker": "INTC"}},
                ]
            },
            "artifacts": {
                "render_vars": {
                    "price_snapshot": "- INTC Current Price: $118.50 | Change: -0.46 (-0.39%) | Suggested ladder: $117.31 / $116.13",
                },
                "step_results": {
                    "s3": {
                        "output": {
                            "ticker": "INTC",
                            "summary": (
                                "INTC 技术快照: 收盘价 118.50。 MA20 107.19 MA50 74.95 "
                                "RSI(14) 62.29（中性）。 MACD 12.3580 vs 信号线 13.6624（空头）。 "
                                "趋势: 上升趋势。 关键价位: 支撑 79.62，阻力 132.75。 "
                                "成交量为均量 0.62倍。 均线呈多头排列，趋势偏强。"
                            ),
                        }
                    }
                },
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "| :" not in markdown
    assert "$117.31" not in markdown
    assert "我会先看" not in markdown
    assert "技术面结论" in markdown
    assert "可执行" in markdown
    assert "支撑 79.62" in markdown
    assert "阻力 132.75" in markdown


def test_investment_opinion_chat_renders_quality_contract_sections() -> None:
    markdown = _render_chat(
        {
            "query": "INTC 最近走势如何 看好么",
            "subject": {"subject_type": "company", "tickers": ["INTC"]},
            "operation": {"name": "investment_opinion"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["INTC"],
                    "operation": {"name": "investment_opinion"},
                }
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "INTC"}},
                    {"id": "s2", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "INTC"}},
                    {"id": "s3", "kind": "agent", "name": "technical_agent", "inputs": {"ticker": "INTC"}},
                    {"id": "s4", "kind": "agent", "name": "fundamental_agent", "inputs": {"ticker": "INTC"}},
                    {"id": "s5", "kind": "agent", "name": "risk_agent", "inputs": {"ticker": "INTC"}},
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {
                        "output": {
                            "ticker": "INTC",
                            "price": 118.5,
                            "currency": "USD",
                            "change_percent": -0.39,
                            "as_of": "2026-05-22T12:00:00Z",
                        }
                    },
                    "s2": {
                        "output": [
                            {
                                "title": "Intel shares react to AI PC update",
                                "url": "https://example.com/intc-ai-pc",
                                "source": "Example News",
                                "published_at": "2026-05-22T09:00:00Z",
                            }
                        ]
                    },
                    "s3": {
                        "output": {
                            "summary": (
                                "INTC 技术快照: 收盘价 118.50。RSI(14) 62.29（中性）。"
                                "MACD 空头。趋势: 上升趋势。关键价位: 支撑 79.62，阻力 132.75。"
                            )
                        }
                    },
                    "s4": {
                        "output": {
                            "summary": "FundamentalAgent: 营收恢复仍需后续财报验证，估值结论需要结合 EPS 修正。",
                            "risks": ["盈利修复不及预期会压制估值。"],
                        }
                    },
                    "s5": {
                        "output": {
                            "summary": "RiskAgent: 波动和回撤风险中等，若跌破关键支撑需降低仓位。",
                            "risks": ["跌破支撑位后趋势会转弱。"],
                        }
                    },
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    for heading in ("结论", "价格/趋势", "技术面", "消息/催化", "基本面/估值", "风险"):
        assert heading in markdown
    assert "支撑 79.62" in markdown
    assert "Example News" in markdown
    assert "盈利修复" in markdown
    assert "跌破支撑" in markdown


def test_investment_opinion_answer_matrix_preserves_quality_sections() -> None:
    cases = [
        ("INTC 最近走势如何 看好么", "INTC"),
        ("NVDA 走势怎么看", "NVDA"),
        ("AAPL 值得买吗", "AAPL"),
        ("TSLA 后市怎么操作", "TSLA"),
        ("MSFT 短中期风险机会怎么看", "MSFT"),
        ("Should I buy AMD shares here?", "AMD"),
    ]

    for query, ticker in cases:
        markdown = _render_chat(
            {
                "query": query,
                "subject": {"subject_type": "company", "tickers": [ticker]},
                "operation": {"name": "investment_opinion"},
                "tasks": [
                    {
                        "id": "task_1",
                        "subject_type": "company",
                        "tickers": [ticker],
                        "operation": {"name": "investment_opinion"},
                    }
                ],
                "plan_ir": {
                    "steps": [
                        {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": ticker}},
                        {"id": "s2", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": ticker}},
                        {"id": "s3", "kind": "agent", "name": "technical_agent", "inputs": {"ticker": ticker}},
                        {"id": "s4", "kind": "agent", "name": "fundamental_agent", "inputs": {"ticker": ticker}},
                        {"id": "s5", "kind": "agent", "name": "risk_agent", "inputs": {"ticker": ticker}},
                    ]
                },
                "artifacts": {
                    "step_results": {
                        "s1": {"output": {"ticker": ticker, "price": 118.5, "currency": "USD", "change_percent": 0.8}},
                        "s2": {"output": [{"title": f"{ticker} update", "url": f"https://example.com/{ticker.lower()}", "source": "Example News"}]},
                        "s3": {"output": {"summary": f"{ticker} 技术快照: 上升趋势。关键价位: 支撑 100.00，阻力 125.00。"}},
                        "s4": {"output": {"summary": f"{ticker} 基本面仍需盈利验证，估值需要结合 EPS 修正。"}},
                        "s5": {"output": {"summary": f"{ticker} 回撤风险中等，跌破支撑需降低仓位。", "risks": ["跌破支撑后趋势转弱。"]}},
                    }
                },
            }
        )

        _assert_chat_contract(markdown)
        for heading in ("结论", "价格/趋势", "技术面", "消息/催化", "基本面/估值", "风险"):
            assert heading in markdown, query
        assert "数据缺失" not in markdown, query
        assert "支撑 100.00" in markdown, query


def test_investment_opinion_bias_does_not_treat_controlled_risk_as_bearish() -> None:
    markdown = _render_chat(
        {
            "query": "NVDA 走势怎么看",
            "subject": {"subject_type": "company", "tickers": ["NVDA"]},
            "operation": {"name": "investment_opinion"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["NVDA"],
                    "operation": {"name": "investment_opinion"},
                }
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "NVDA"}},
                    {"id": "s2", "kind": "agent", "name": "technical_agent", "inputs": {"ticker": "NVDA"}},
                    {"id": "s3", "kind": "agent", "name": "risk_agent", "inputs": {"ticker": "NVDA"}},
                    {"id": "s4", "kind": "agent", "name": "fundamental_agent", "inputs": {"ticker": "NVDA"}},
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {"output": {"ticker": "NVDA", "price": 125.4, "currency": "USD", "change_percent": 1.6}},
                    "s2": {"output": {"summary": "NVDA 技术快照: 偏强，上升趋势。关键价位: 支撑 118.00，阻力 132.00。"}},
                    "s3": {"output": {"summary": "RiskAgent: 波动风险可控，没有触及关键风控线。", "risks": ["波动风险可控。"]}},
                    "s4": {"output": {"summary": "FundamentalAgent: 盈利预期仍在上修，估值需要结合后续业绩兑现。"}},
                }
            },
        }
    )

    assert "「中性偏多」" in markdown


def test_earnings_performance_chat_renders_financial_sections_not_news_only() -> None:
    markdown = _render_chat(
        {
            "query": "英伟达最新季度财报表现如何",
            "subject": {"subject_type": "company", "tickers": ["NVDA"]},
            "operation": {"name": "earnings_performance"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["NVDA"],
                    "operation": {"name": "earnings_performance"},
                }
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_company_info", "inputs": {"ticker": "NVDA"}},
                    {"id": "s2", "kind": "tool", "name": "get_sec_company_facts_quarterly", "inputs": {"ticker": "NVDA"}},
                    {"id": "s3", "kind": "tool", "name": "get_earnings_estimates", "inputs": {"ticker": "NVDA"}},
                    {"id": "s4", "kind": "tool", "name": "get_eps_revisions", "inputs": {"ticker": "NVDA"}},
                    {"id": "s5", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "NVDA"}},
                    {"id": "s6", "kind": "agent", "name": "fundamental_agent", "inputs": {"ticker": "NVDA"}},
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {"output": {"ticker": "NVDA", "name": "NVIDIA Corp", "sector": "Technology"}},
                    "s2": {
                        "output": {
                            "ticker": "NVDA",
                            "source": "sec_companyfacts",
                            "periods": ["2026Q1", "2025Q4"],
                            "revenue": [44062000000, 39331000000],
                            "net_income": [18775000000, 22066000000],
                            "eps": [0.81, 0.89],
                            "error": None,
                        }
                    },
                    "s3": {
                        "output": {
                            "ticker": "NVDA",
                            "earnings_estimate": [{"period": "0q", "avg": 0.93}],
                            "revision_signal": "positive",
                            "error": None,
                        }
                    },
                    "s4": {
                        "output": {
                            "ticker": "NVDA",
                            "eps_revisions": [{"period": "0q", "upLast7days": 8, "downLast7days": 1}],
                            "revision_signal": "positive",
                            "error": None,
                        }
                    },
                    "s5": {
                        "output": [
                            {
                                "title": "Nvidia reports latest quarterly results",
                                "url": "https://example.com/nvda-results",
                                "source": "Example News",
                                "published_at": "2026-05-22",
                            },
                            {
                                "title": "Workday jumps after AI margin forecast",
                                "url": "https://example.com/workday-results",
                                "source": "Example News",
                                "published_at": "2026-05-22",
                            }
                        ]
                    },
                    "s6": {
                        "output": {
                            "summary": "FundamentalAgent: 数据中心收入继续支撑增长，但利润率和下一季指引仍需验证。"
                        }
                    },
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    for heading in ("结论", "最新季度/财务表现", "盈利预期/EPS 修正", "消息/指引", "风险/待验证"):
        assert heading in markdown
    assert "44.06B" in markdown
    assert "0.81" in markdown
    assert "数据中心收入继续支撑增长" in markdown
    assert "FundamentalAgent:" not in markdown
    assert "Nvidia reports latest quarterly results" in markdown
    assert "Workday jumps" not in markdown
    assert "价格/趋势" not in markdown


def test_earnings_performance_chat_uses_successful_synthesis_summary() -> None:
    markdown = _render_chat(
        {
            "query": "英伟达最新季度财报表现如何",
            "subject": {"subject_type": "company", "tickers": ["NVDA"]},
            "operation": {"name": "earnings_performance"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["NVDA"],
                    "operation": {"name": "earnings_performance"},
                }
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "agent", "name": "fundamental_agent", "inputs": {"ticker": "NVDA"}},
                ]
            },
            "artifacts": {
                "render_vars": {
                    "conclusion": "数据中心需求仍是核心驱动，但下一季指引决定股价能否继续消化估值。",
                    "impact_analysis": "财报表现需要同时看收入增速、毛利率和 EPS 预期修正。",
                },
                "step_results": {
                    "s1": {
                        "output": {
                            "summary": "FundamentalAgent: 数据中心收入继续支撑增长。"
                        }
                    },
                },
            },
            "trace": {"synthesize_runtime": {"mode": "llm", "fallback": False}},
        }
    )

    _assert_chat_contract(markdown)
    assert "数据中心需求仍是核心驱动" in markdown
    assert "财报表现需要同时看收入增速" in markdown
    assert "不能只看新闻标题" not in markdown
    assert "FundamentalAgent:" not in markdown


def test_earnings_performance_news_filter_uses_company_name_not_profile_body() -> None:
    markdown = _render_chat(
        {
            "query": "英伟达最新季度财报表现如何",
            "subject": {"subject_type": "company", "tickers": ["NVDA"]},
            "operation": {"name": "earnings_performance"},
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_company_info", "inputs": {"ticker": "NVDA"}},
                    {"id": "s2", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "NVDA"}},
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {
                        "output": (
                            "Company Profile (NVDA):\n"
                            "- Name: NVIDIA Corporation\n"
                            "- Sector: Technology\n"
                            "- Description: NVIDIA operates through Compute & Networking and Graphics.\n"
                        )
                    },
                    "s2": {
                        "output": [
                            {
                                "title": "NVIDIA Earnings: Key Metrics",
                                "url": "https://example.com/nvidia-earnings",
                                "source": "Example News",
                                "published_at": "2026-05-22",
                            },
                            {
                                "title": "Lenovo shares jump on record earnings and AI revenue",
                                "url": "https://example.com/lenovo-earnings",
                                "source": "Example News",
                                "published_at": "2026-05-22",
                            },
                        ]
                    },
                }
            },
        }
    )

    assert "NVIDIA Earnings: Key Metrics" in markdown
    assert "Lenovo shares jump" not in markdown


def test_earnings_chat_uses_earnings_transcripts_as_guidance_sources() -> None:
    markdown = _render_chat(
        {
            "query": "英伟达最新季度财报表现如何",
            "subject": {"subject_type": "company", "tickers": ["NVDA"]},
            "operation": {"name": "earnings_performance"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["NVDA"],
                    "operation": {"name": "earnings_performance"},
                }
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_company_info", "inputs": {"ticker": "NVDA"}},
                    {"id": "s2", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "NVDA"}},
                    {"id": "s3", "kind": "tool", "name": "get_earnings_call_transcripts", "inputs": {"ticker": "NVDA"}},
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {"output": {"ticker": "NVDA", "name": "NVIDIA Corporation"}},
                    "s2": {
                        "output": [
                            {
                                "title": f"Unrelated sector headline {i}",
                                "url": f"https://example.com/sector-{i}",
                                "source": "Example News",
                                "published_at": "2026-05-20",
                                "snippet": "NVIDIA peer read-through mentioned only in passing.",
                            }
                            for i in range(6)
                        ]
                    },
                    "s3": {
                        "output": {
                            "ticker": "NVDA",
                            "transcripts": [
                                {
                                    "title": "Nvidia (NVDA) Q1 2027 Earnings Transcript",
                                    "url": "https://example.com/nvda-q1-2027-transcript",
                                    "source": "The Motley Fool",
                                    "published_date": "2026-05-20",
                                    "type": "transcript",
                                }
                            ],
                        }
                    },
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "Nvidia (NVDA) Q1 2027 Earnings Transcript" in markdown
    assert markdown.index("Nvidia (NVDA) Q1 2027 Earnings Transcript") < markdown.index("Unrelated sector headline 0")
    assert "本轮没有可引用的财报新闻、电话会或指引来源" not in markdown


def test_earnings_impact_chat_renders_price_and_earnings_evidence() -> None:
    markdown = _render_chat(
        {
            "query": "请问英伟达这个季度财报对股价的影响",
            "subject": {"subject_type": "company", "tickers": ["NVDA"]},
            "operation": {"name": "earnings_impact"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["NVDA"],
                    "operation": {"name": "earnings_impact"},
                }
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "NVDA"}},
                    {"id": "s2", "kind": "tool", "name": "get_company_info", "inputs": {"ticker": "NVDA"}},
                    {"id": "s3", "kind": "tool", "name": "get_sec_company_facts_quarterly", "inputs": {"ticker": "NVDA"}},
                    {"id": "s4", "kind": "tool", "name": "get_earnings_estimates", "inputs": {"ticker": "NVDA"}},
                    {"id": "s5", "kind": "tool", "name": "get_eps_revisions", "inputs": {"ticker": "NVDA"}},
                    {"id": "s6", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "NVDA"}},
                    {"id": "s7", "kind": "agent", "name": "fundamental_agent", "inputs": {"ticker": "NVDA"}},
                    {"id": "s8", "kind": "agent", "name": "risk_agent", "inputs": {"ticker": "NVDA"}},
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {"output": {"ticker": "NVDA", "price": 176.2, "currency": "USD", "change_percent": 2.4}},
                    "s2": {"output": {"ticker": "NVDA", "name": "NVIDIA Corp"}},
                    "s3": {
                        "output": {
                            "ticker": "NVDA",
                            "source": "sec_companyfacts",
                            "periods": ["2026Q1"],
                            "revenue": [44062000000],
                            "net_income": [18775000000],
                            "eps": [0.81],
                            "error": None,
                        }
                    },
                    "s4": {"output": {"earnings_estimate": [{"period": "0q", "avg": 0.93}], "revision_signal": "positive"}},
                    "s5": {"output": {"eps_revisions": [{"period": "0q", "upLast7days": 8, "downLast7days": 1}]}},
                    "s6": {
                        "output": [
                            {
                                "title": "Nvidia earnings beat expectations",
                                "url": "https://example.com/nvidia-earnings-beat",
                                "source": "Example News",
                                "published_at": "2026-05-22",
                            }
                        ]
                    },
                    "s7": {"output": {"summary": "FundamentalAgent: 财报超预期主要来自数据中心需求和毛利率韧性。"}},
                    "s8": {"output": {"summary": "RiskAgent: 若指引不再上修，股价反应可能回吐。", "risks": ["估值对指引变化敏感。"]}},
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    for heading in ("结论", "股价反应", "财报/预期差", "盈利预期/EPS 修正", "消息/指引", "风险/后续观察"):
        assert heading in markdown
    assert "176.20 USD" in markdown
    assert "44.06B" in markdown
    assert "0.81" in markdown
    assert "Nvidia earnings beat expectations" in markdown
    assert "估值对指引变化敏感" in markdown


def test_earnings_impact_chat_uses_successful_synthesis_summary() -> None:
    markdown = _render_chat(
        {
            "query": "请问英伟达这个季度财报对股价的影响",
            "subject": {"subject_type": "company", "tickers": ["NVDA"]},
            "operation": {"name": "earnings_impact"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["NVDA"],
                    "operation": {"name": "earnings_impact"},
                }
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "NVDA"}},
                    {"id": "s2", "kind": "agent", "name": "fundamental_agent", "inputs": {"ticker": "NVDA"}},
                ]
            },
            "artifacts": {
                "render_vars": {
                    "conclusion": "股价短线取决于财报超预期能否转化为下一季 EPS 上修。",
                    "impact_analysis": "如果价格已提前反映利好，财报后反而要关注放量确认和回撤风险。",
                },
                "step_results": {
                    "s1": {"output": {"ticker": "NVDA", "price": 176.2, "currency": "USD"}},
                    "s2": {"output": {"summary": "FundamentalAgent: 财报超预期主要来自数据中心需求。"}},
                },
            },
            "trace": {"synthesize_runtime": {"mode": "llm", "fallback": False}},
        }
    )

    _assert_chat_contract(markdown)
    assert "股价短线取决于财报超预期" in markdown
    assert "价格已提前反映利好" in markdown
    assert "176.20 USD" in markdown
    assert "FundamentalAgent:" not in markdown


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


def test_chat_renderer_preserves_alert_markdown_with_followup_news() -> None:
    markdown = _render_chat(
        {
            "query": "give recent news links",
            "subject": {"subject_type": "company", "tickers": ["TSLA"]},
            "operation": {"name": "fetch"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "tickers": ["TSLA"],
                    "operation": {"name": "fetch", "params": {"topic": "news", "include_links": True}},
                }
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "TSLA"}},
                ]
            },
            "artifacts": {
                "alert_markdown": "Created alert for TSLA at 180.",
                "step_results": {
                    "s1": {
                        "output": [
                            {
                                "title": "Tesla delivery update",
                                "url": "https://example.com/tesla-delivery",
                                "source": "Example News",
                                "published_at": "2026-05-10",
                            }
                        ]
                    }
                },
            },
        }
    )

    _assert_chat_contract(markdown)
    assert markdown.startswith("Created alert for TSLA at 180.")
    assert "[Tesla delivery update](https://example.com/tesla-delivery)" in markdown


def test_news_chat_discloses_missing_article_url_when_source_has_no_url() -> None:
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
    assert "Xiaomi EV delivery update" in markdown
    assert "google.com/search" not in markdown
    assert "not treating search pages as citations" in markdown


def test_news_chat_links_source_page_when_requested_links_but_articles_have_no_urls() -> None:
    markdown = _render_chat(
        {
            "query": "Give me 3 latest NVDA news items with links.",
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
            "artifacts": {
                "step_results": {
                    "s1": {
                        "output": [
                            {
                                "title": "Nvidia data center demand stays strong",
                                "source": "Search",
                                "published_at": "2026-05-10T08:00:00Z",
                            }
                        ]
                    }
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "Nvidia data center demand stays strong" in markdown
    assert "not treating search pages as citations" in markdown
    assert "rather than treating them as article citations" in markdown
    assert "[NVDA Yahoo Finance news](https://finance.yahoo.com/quote/NVDA/news)" in markdown
    assert "google.com/search" not in markdown


def test_news_chat_does_not_invent_links_when_requested_news_source_is_empty() -> None:
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
    assert "I will not invent citation links" in markdown
    assert "google.com/search" not in markdown
    assert "finance.yahoo.com/search" not in markdown
    assert markdown.count("](") == 0
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
                "current_report": {
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


def test_news_link_request_fetches_article_fallback_when_plan_has_no_news(monkeypatch) -> None:
    from backend.graph.nodes import chat_renderer

    def fake_get_company_news(ticker: str, limit: int = 5, fast: bool = False):
        assert ticker == "NVDA"
        assert fast is True
        return [
            {
                "title": "Nvidia earnings preview",
                "url": "https://finance.yahoo.com/markets/stocks/articles/nvidia-earnings-preview-2026-05-18.html",
                "source": "Yahoo Finance",
                "published_at": "2026-05-18",
            }
        ][:limit]

    monkeypatch.setattr(chat_renderer, "get_company_news", fake_get_company_news, raising=False)
    monkeypatch.setattr(chat_renderer, "get_authoritative_media_news", None, raising=False)

    markdown = _render_chat(
        {
            "query": "NVDA latest news with links.",
            "subject": {"subject_type": "company", "tickers": ["NVDA"]},
            "operation": {"name": "fetch"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "subject_label": "NVDA",
                    "tickers": ["NVDA"],
                    "operation": {"name": "fetch", "params": {"topic": "news", "include_links": True, "count": 1}},
                }
            ],
            "artifacts": {"step_results": {}},
            "plan_ir": {"steps": []},
            "reply_contract": {
                "lane": "source_grounded_answer",
                "source_constraints": {"requires_links": True},
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "Nvidia earnings preview" in markdown
    assert "https://finance.yahoo.com/markets/stocks/articles/nvidia-earnings-preview-2026-05-18.html" in markdown
    assert "finance.yahoo.com/quote/NVDA/news" not in markdown


def test_news_link_article_fallback_limits_render_time_surface(monkeypatch) -> None:
    from backend.graph.nodes import chat_renderer

    calls: list[str] = []

    def fake_get_company_news(ticker: str, limit: int = 5, fast: bool = False):
        calls.append(ticker)
        return [
            {
                "title": f"{ticker} earnings article",
                "url": f"https://finance.yahoo.com/markets/stocks/articles/{ticker.lower()}-earnings.html",
                "source": "Yahoo Finance",
                "published_at": "2026-05-18",
            }
        ][:limit]

    monkeypatch.setattr(chat_renderer, "get_company_news", fake_get_company_news, raising=False)
    monkeypatch.setattr(chat_renderer, "get_authoritative_media_news", None, raising=False)
    monkeypatch.setenv("CHAT_RENDER_NEWS_FALLBACK_MAX_TICKERS", "1")
    monkeypatch.setenv("CHAT_RENDER_NEWS_FALLBACK_BUDGET_SECONDS", "5")

    markdown = _render_chat(
        {
            "query": "NVDA and MSFT latest news with links.",
            "subject": {"subject_type": "company", "tickers": ["NVDA", "MSFT"]},
            "operation": {"name": "fetch"},
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "subject_label": "NVDA, MSFT",
                    "tickers": ["NVDA", "MSFT"],
                    "operation": {"name": "fetch", "params": {"topic": "news", "include_links": True, "count": 3}},
                }
            ],
            "artifacts": {"step_results": {}},
            "reply_contract": {
                "lane": "source_grounded_answer",
                "source_constraints": {"requires_links": True},
            },
        }
    )

    _assert_chat_contract(markdown)
    assert calls == ["NVDA"]
    assert "NVDA earnings article" in markdown


def test_news_article_fallback_does_not_run_for_direct_answer_route(monkeypatch) -> None:
    from backend.graph.nodes import chat_renderer

    calls: list[str] = []

    def fake_get_company_news(ticker: str, limit: int = 5, fast: bool = False):
        calls.append(ticker)
        return [
            {
                "title": "Direct route should not fetch this article",
                "url": "https://finance.yahoo.com/markets/stocks/articles/direct-route.html",
                "source": "Yahoo Finance",
                "published_at": "2026-05-18",
            }
        ]

    monkeypatch.setattr(chat_renderer, "get_company_news", fake_get_company_news, raising=False)
    monkeypatch.setattr(chat_renderer, "get_authoritative_media_news", None, raising=False)

    markdown = _render_chat(
        {
            "query": "INTC 最新财报和竞争怎么看？",
            "subject": {"subject_type": "company", "tickers": ["INTC"]},
            "operation": {"name": "qa"},
            "artifacts": {
                "conversation_decision": {
                    "execution_route": "direct_answer",
                    "needs_tools": False,
                    "reason": "explicit subject context without grounded data request",
                }
            },
            "reply_contract": {
                "lane": "chat_answer",
                "source_constraints": {"requires_links": True},
            },
        }
    )

    _assert_chat_contract(markdown)
    assert calls == []
    assert "Direct route should not fetch this article" not in markdown


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
    assert "最近新闻" in markdown
    assert "[Li Auto delivery update](https://example.com/li)" in markdown
    assert "对股价的影响要看两点" not in markdown

def test_chat_renderer_external_entity_impact_adds_deterministic_judgment() -> None:
    markdown = _render_chat(
        {
            "query": "研究一下特斯拉会不会被 SpaceX 影响",
            "subject": {"subject_type": "company", "tickers": ["TSLA"]},
            "operation": {"name": "analyze_impact"},
            "trace": {
                "intent_contract": {
                    "facets": ["external_entity_impact"],
                    "budget_profile": "external_entity_impact_light",
                    "required_evidence": ["price_snapshot", "news_context", "risk_profile"],
                }
            },
            "tasks": [
                {
                    "id": "task_1",
                    "subject_type": "company",
                    "subject_label": "TSLA",
                    "tickers": ["TSLA"],
                    "operation": {
                        "name": "analyze_impact",
                        "params": {
                            "facets": ["external_entity_impact"],
                            "budget_profile": "external_entity_impact_light",
                        },
                    },
                }
            ],
            "plan_ir": {
                "steps": [
                    {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "TSLA"}, "task_ids": ["task_1"]},
                    {"id": "s2", "kind": "tool", "name": "get_company_news", "inputs": {"ticker": "TSLA"}, "task_ids": ["task_1"]},
                ]
            },
            "artifacts": {
                "step_results": {
                    "s1": {"output": {"price": 180.0, "change_percent": 1.2}},
                    "s2": {"output": [{"title": "Tesla and SpaceX investor attention", "url": "https://example.com/tsla-spacex"}]},
                }
            },
        }
    )

    _assert_chat_contract(markdown)
    assert "初步影响判断" in markdown
    assert "间接叙事/风险影响" in markdown
    assert "不能单独证明因果" in markdown


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

# -*- coding: utf-8 -*-
from backend.graph.nodes.render_stub import render_stub


FORBIDDEN_NORMAL_CHAT_MARKERS = (
    "本轮问题包含",
    "分析对象",
    "问题：",
    "后续关注：",
    "get_stock_price",
    "get_company_news",
    "Suggested ladder",
)


def _assert_natural_chat(md: str) -> None:
    assert "## 最终答案" not in md
    assert "## 快速摘要" not in md
    assert "### 新闻摘要" not in md
    assert "## 对比快评" not in md
    for marker in FORBIDDEN_NORMAL_CHAT_MARKERS:
        assert marker not in md


def test_render_news_brief_uses_natural_chat_not_news_template():
    state = {
        "query": "分析影响",
        "output_mode": "brief",
        "operation": {"name": "analyze_impact", "confidence": 0.7, "params": {}},
        "subject": {
            "subject_type": "news_item",
            "tickers": [],
            "selection_ids": ["n1"],
            "selection_types": ["news"],
            "selection_payload": [{"type": "news", "id": "n1", "title": "t"}],
        },
        "artifacts": {},
    }
    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""
    _assert_natural_chat(md)
    assert "可用新闻列表" in md or "不能硬编影响结论" in md
    assert "## 投资摘要" not in md


def test_render_news_report_uses_news_report_template():
    state = {
        "query": "生成研报",
        "output_mode": "investment_report",
        "operation": {"name": "analyze_impact", "confidence": 0.7, "params": {}},
        "subject": {
            "subject_type": "news_item",
            "tickers": [],
            "selection_ids": ["n1"],
            "selection_types": ["news"],
            "selection_payload": [{"type": "news", "id": "n1", "title": "t"}],
        },
        "artifacts": {},
    }
    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""
    assert "## 新闻事件研报" in md
    assert "## 投资摘要" not in md


def test_render_company_report_uses_company_report_template():
    state = {
        "query": "生成投资报告",
        "output_mode": "investment_report",
        "operation": {"name": "qa", "confidence": 0.4, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "artifacts": {},
    }
    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""
    assert "## 投资研报：AAPL" in md


def test_render_company_brief_includes_evidence_pool_links_naturally():
    state = {
        "query": "分析",
        "output_mode": "brief",
        "operation": {"name": "qa", "confidence": 0.4, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "artifacts": {"evidence_pool": [{"title": "T", "url": "https://example.com", "snippet": "S"}]},
    }
    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""
    _assert_natural_chat(md)
    assert "[T](https://example.com)" in md


def test_render_company_brief_includes_price_and_technical_data_naturally():
    state = {
        "query": "NVDA 最新股价和技术面分析",
        "output_mode": "brief",
        "operation": {"name": "technical", "confidence": 0.9, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["NVDA"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "artifacts": {"render_vars": {"price_snapshot": "- $100", "technical_snapshot": "- RSI(14): 55"}},
    }
    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""
    _assert_natural_chat(md)
    assert "$100" in md
    assert "RSI(14): 55" in md


def test_render_company_compare_brief_uses_natural_comparison_not_template():
    state = {
        "query": "对比 AAPL 和 MSFT 哪个更值得投资",
        "output_mode": "brief",
        "operation": {"name": "compare", "confidence": 0.9, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL", "MSFT"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "plan_ir": {
            "steps": [{"id": "s1", "kind": "tool", "name": "get_performance_comparison"}],
        },
        "artifacts": {
            "render_vars": {"comparison_conclusion": "- x", "comparison_metrics": "- y"},
            "step_results": {
                "s1": {"output": "Ticker Current YTD 1Y\nAAPL +12% +15% +20%\nMSFT +8% +10% +18%"},
            },
        },
    }
    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""
    _assert_natural_chat(md)
    assert "- x" in md
    assert "- y" in md


def test_render_company_fetch_brief_uses_natural_news_not_template():
    state = {
        "query": "特斯拉最近有什么重大新闻",
        "output_mode": "brief",
        "operation": {"name": "fetch", "confidence": 0.7, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["TSLA"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "artifacts": {"render_vars": {"news_summary": "- [t](https://example.com)", "conclusion": "- x"}},
    }
    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""
    _assert_natural_chat(md)
    assert "[t](https://example.com)" in md


def test_render_multitask_brief_uses_natural_answer_with_links():
    from backend.graph.nodes.render_stub import render_stub

    state = {
        "query": "小米和理想汽车，CPI 影响吗",
        "output_mode": "brief",
        "operation": {"name": "analyze_impact", "confidence": 0.8, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["XIACY", "LI"]},
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "subject_label": "LI",
                "tickers": ["LI"],
                "operation": {"name": "analyze_impact"},
            },
            {
                "id": "task_2",
                "subject_type": "company",
                "subject_label": "XIACY",
                "tickers": ["XIACY"],
                "operation": {"name": "analyze_impact"},
            },
            {
                "id": "task_3",
                "subject_type": "macro",
                "subject_label": "CPI",
                "tickers": [],
                "operation": {"name": "analyze_impact"},
            },
        ],
        "plan_ir": {
            "steps": [
                {"id": "s1", "name": "get_company_news", "inputs": {"ticker": "LI"}, "task_ids": ["task_1"]},
                {"id": "s2", "name": "get_company_news", "inputs": {"ticker": "XIACY"}, "task_ids": ["task_2"]},
                {"id": "s3", "name": "get_official_macro_releases", "inputs": {"query": "CPI"}, "task_ids": ["task_3"]},
            ]
        },
        "artifacts": {
            "step_results": {
                "s1": {
                    "output": '[{"title":"Li Auto delivery update","url":"https://example.com/li","source":"TestNews","published_at":"2026-05-03"}]',
                },
                "s2": {
                    "output": [{"title": "Xiaomi EV margin watch", "url": "https://example.com/xiaomi", "source": "TestNews"}],
                },
                "s3": {
                    "output": {"releases": [{"title": "CPI release", "url": "https://example.com/cpi", "source": "BLS"}]},
                },
            },
            "evidence_pool": [],
        },
    }

    out = render_stub(state)
    md = (out.get("artifacts") or {}).get("draft_markdown") or ""

    _assert_natural_chat(md)
    assert "LI" in md and "XIACY" in md and "CPI" in md
    assert "[Li Auto delivery update](https://example.com/li)" in md
    assert "[Xiaomi EV margin watch](https://example.com/xiaomi)" in md
    assert "[CPI release](https://example.com/cpi)" in md


def test_render_multitask_brief_is_natural_not_report_template():
    from backend.graph.nodes.render_stub import render_stub

    state = {
        "query": "小米和理想汽车，CPI 影响吗",
        "output_mode": "brief",
        "operation": {"name": "analyze_impact", "confidence": 0.8, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["XIACY", "LI"]},
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "subject_label": "LI",
                "tickers": ["LI"],
                "operation": {"name": "analyze_impact"},
            },
            {
                "id": "task_2",
                "subject_type": "macro",
                "subject_label": "CPI",
                "tickers": [],
                "operation": {"name": "analyze_impact"},
            },
        ],
        "plan_ir": {
            "steps": [
                {"id": "s1", "name": "get_company_news", "inputs": {"ticker": "LI"}, "task_ids": ["task_1"]},
                {"id": "s2", "name": "get_official_macro_releases", "inputs": {"query": "CPI"}, "task_ids": ["task_2"]},
            ]
        },
        "artifacts": {
            "step_results": {
                "s1": {
                    "output": [{"title": "Li Auto delivery update", "url": "https://example.com/li", "source": "TestNews"}],
                },
                "s2": {
                    "output": {"releases": [{"title": "CPI release", "url": "https://example.com/cpi", "source": "BLS"}]},
                },
            }
        },
    }

    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""

    _assert_natural_chat(md)
    assert "LI" in md
    assert "CPI" in md
    assert "[Li Auto delivery update](https://example.com/li)" in md
    assert "[CPI release](https://example.com/cpi)" in md


def test_render_multitask_search_output_adds_source_link():
    from backend.graph.nodes.render_stub import render_stub

    state = {
        "query": "小米和理想汽车，CPI 影响吗",
        "output_mode": "brief",
        "operation": {"name": "analyze_impact", "confidence": 0.8, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["XIACY", "LI"]},
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "subject_label": "LI",
                "tickers": ["LI"],
                "operation": {"name": "analyze_impact"},
            },
            {
                "id": "task_2",
                "subject_type": "macro",
                "subject_label": "CPI",
                "tickers": [],
                "operation": {"name": "analyze_impact"},
            },
        ],
        "plan_ir": {
            "steps": [
                {"id": "s1", "name": "search", "inputs": {"query": "LI CPI impact"}, "task_ids": ["task_1"]},
            ]
        },
        "artifacts": {
            "step_results": {
                "s1": {"output": "AI摘要:\nCPI may affect EV demand."},
            },
            "evidence_pool": [],
        },
    }

    out = render_stub(state)
    md = (out.get("artifacts") or {}).get("draft_markdown") or ""

    assert "https://www.google.com/search?q=LI+CPI+impact" in md

def test_render_two_tickers_qa_does_not_use_compare_template():
    """Regression: 2 tickers + operation=qa should use company_brief, NOT compare template.

    This is the pseudo-comparison bug that was fixed by gating compare template
    selection on operation.name instead of ticker count.
    """
    state = {
        "query": "那苹果和特斯拉呢",
        "output_mode": "brief",
        "operation": {"name": "qa", "confidence": 0.4, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL", "TSLA"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "artifacts": {},
    }
    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""
    # Should NOT use compare template
    assert "## 对比快评" not in md
    _assert_natural_chat(md)
    assert "AAPL" in md and "TSLA" in md


def test_render_two_tickers_price_does_not_use_compare_template():
    """Regression: 2 tickers + operation=price (guardrail A) should NOT use compare template."""
    state = {
        "query": "AAPL 和 TSLA 股价",
        "output_mode": "brief",
        "operation": {"name": "price", "confidence": 0.8, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL", "TSLA"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "artifacts": {},
    }
    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""
    assert "## 对比快评" not in md
    _assert_natural_chat(md)
    assert "AAPL" in md and "TSLA" in md


def test_render_compare_no_evidence_degrades_to_company_brief():
    """Gap-1 fix: operation=compare but no tool evidence → falls back to company_brief."""
    state = {
        "query": "对比 AAPL 和 MSFT",
        "output_mode": "brief",
        "operation": {"name": "compare", "confidence": 0.9, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL", "MSFT"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "artifacts": {},
    }
    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""
    # No evidence → should NOT use compare template
    assert "## 对比快评" not in md
    _assert_natural_chat(md)
    assert "AAPL" in md and "MSFT" in md


def test_render_multitask_report_fallback_avoids_mechanical_markers():
    state = {
        "query": "分析 GOOGL 和 MSFT，生成报告。",
        "output_mode": "investment_report",
        "operation": {"name": "compare", "confidence": 0.86, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["GOOGL", "MSFT"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "tickers": ["GOOGL", "MSFT"],
                "operation": {"name": "compare", "confidence": 0.86, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_2",
                "subject_type": "company",
                "tickers": ["GOOGL"],
                "operation": {"name": "price", "confidence": 0.82, "params": {}},
                "status": "ready",
            },
        ],
        "artifacts": {"step_results": {}},
    }
    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""
    assert "本轮问题包含" not in md
    assert "分析对象" not in md
    assert "## GOOGL vs MSFT 研究报告" in md


def test_render_multitask_report_fallback_sanitizes_tool_outputs():
    state = {
        "query": "分析 GOOGL 和 MSFT，生成报告。",
        "output_mode": "investment_report",
        "operation": {"name": "compare", "confidence": 0.86, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["GOOGL", "MSFT"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "tickers": ["GOOGL", "MSFT"],
                "operation": {"name": "compare", "confidence": 0.86, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_2",
                "subject_type": "company",
                "subject_label": "GOOGL",
                "tickers": ["GOOGL"],
                "operation": {"name": "price", "confidence": 0.82, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_3",
                "subject_type": "company",
                "subject_label": "MSFT",
                "tickers": ["MSFT"],
                "operation": {"name": "fetch", "confidence": 0.82, "params": {}},
                "status": "ready",
            },
        ],
        "plan_ir": {
            "steps": [
                {"id": "s1", "name": "get_stock_price", "inputs": {"ticker": "GOOGL"}, "task_ids": ["task_2"]},
                {"id": "s2", "name": "get_company_news", "inputs": {"ticker": "MSFT"}, "task_ids": ["task_3"]},
            ]
        },
        "artifacts": {
            "step_results": {
                "s1": {
                    "output": "GOOGL Current Price: $383.25 | Change: -2.44 (-0.63%) | Suggested ladder: $379.42 / $375.59"
                },
                "s2": {
                    "output": [
                        {
                            "title": "Microsoft expands AI infrastructure",
                            "url": "https://example.com/msft-ai",
                            "source": "UnitNews",
                        }
                    ]
                },
            }
        },
    }

    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""

    assert "get_stock_price" not in md
    assert "get_company_news" not in md
    assert "Suggested ladder" not in md
    assert "unspecified" not in md
    assert "已识别的分析类型" not in md
    assert "价格: 最新价格约为 383.25 USD，变动 -2.44，-0.63%。" in md
    assert "新闻: [Microsoft expands AI infrastructure](https://example.com/msft-ai)" in md


def test_render_chat_mixed_url_and_focus_task_does_not_become_empty_portfolio():
    state = {
        "query": "AAPL 价格、看下这个 https://example.com/msft-rates 对 MSFT 有没有用，再解释一下为什么高估值怕利率，最后用一句话说我该关注什么。",
        "output_mode": "chat",
        "operation": {"name": "qa", "confidence": 0.8, "params": {}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL", "MSFT"],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
        },
        "tasks": [
            {
                "id": "task_price",
                "subject_type": "company",
                "subject_label": "AAPL",
                "tickers": ["AAPL"],
                "operation": {"name": "price", "confidence": 0.8, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_url",
                "subject_type": "research_doc",
                "subject_label": "MSFT rates analysis",
                "tickers": ["MSFT"],
                "operation": {"name": "fetch", "confidence": 0.8, "params": {"url": "https://example.com/msft-rates"}},
                "status": "ready",
            },
            {
                "id": "task_macro",
                "subject_type": "macro",
                "subject_label": "利率与估值",
                "tickers": [],
                "operation": {"name": "qa", "confidence": 0.8, "params": {"topic": "为什么高估值怕利率"}},
                "status": "ready",
            },
            {
                "id": "task_focus",
                "subject_type": "portfolio",
                "subject_label": "投资关注点",
                "tickers": [],
                "operation": {"name": "qa", "confidence": 0.8, "params": {}},
                "status": "ready",
            },
        ],
        "plan_ir": {
            "steps": [
                {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "AAPL"}, "task_ids": ["task_price"]},
                {"id": "s2", "kind": "tool", "name": "fetch_url_content", "inputs": {"url": "https://example.com/msft-rates"}, "task_ids": ["task_url"]},
                {"id": "s3", "kind": "tool", "name": "search", "inputs": {"query": "利率与估值"}, "task_ids": ["task_macro"]},
            ]
        },
        "artifacts": {
            "render_vars": {
                "impact_analysis": "提供的 URL 无法访问；高估值股票怕利率，核心是折现率上升会压低远期现金流现值。",
                "next_watch": "一句话：先关注通胀和美联储利率路径，再看 MSFT/AAPL 的业绩指引能否抵消估值压力。",
            },
            "step_results": {
                "s1": {"output": {"ticker": "AAPL", "price": 276.83, "change": -3.42, "change_percent": -1.22, "currency": "USD"}},
                "s2": {"output": {"url": "https://example.com/msft-rates", "error": "404 Client Error"}},
                "s3": {"output": "利率与估值相关搜索结果"},
            },
        },
    }

    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""

    assert md.strip()
    assert "我先按你给的持仓看" not in md
    assert "AAPL 最新价格" in md
    assert "折现率" in md
    assert "关注" in md


def test_render_chat_mixed_url_fallback_uses_tasks_without_render_vars():
    state = {
        "query": "AAPL 价格、看下这个 https://example.com/msft-rates 对 MSFT 有没有用，再解释一下为什么高估值怕利率，最后用一句话说我该关注什么。",
        "output_mode": "chat",
        "operation": {"name": "price", "confidence": 0.8, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["AAPL", "MSFT"], "selection_payload": []},
        "tasks": [
            {"id": "task_price", "subject_type": "company", "subject_label": "AAPL", "tickers": ["AAPL"], "operation": {"name": "price", "confidence": 0.8, "params": {}}, "status": "ready"},
            {"id": "task_url", "subject_type": "company", "subject_label": "MSFT", "tickers": ["MSFT"], "operation": {"name": "qa", "confidence": 0.8, "params": {"url": "https://example.com/msft-rates"}}, "status": "ready"},
            {"id": "task_macro", "subject_type": "macro", "subject_label": "利率与估值", "tickers": [], "operation": {"name": "analyze_impact", "confidence": 0.8, "params": {}}, "status": "ready"},
            {"id": "task_focus", "subject_type": "portfolio", "subject_label": "关注点总结", "tickers": [], "operation": {"name": "qa", "confidence": 0.8, "params": {}}, "status": "ready"},
        ],
        "plan_ir": {
            "steps": [
                {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "AAPL"}, "task_ids": ["task_price"]},
                {"id": "s2", "kind": "tool", "name": "fetch_url_content", "inputs": {"url": "https://example.com/msft-rates"}, "task_ids": ["task_url"]},
                {"id": "s3", "kind": "tool", "name": "search", "inputs": {"query": "利率与估值"}, "task_ids": ["task_macro"]},
            ]
        },
        "artifacts": {
            "step_results": {
                "s1": {"output": {"ticker": "AAPL", "price": 276.83, "change": -3.42, "change_percent": -1.22, "currency": "USD"}},
                "s2": {"output": {"url": "https://example.com/msft-rates", "error": "404 Client Error"}},
                "s3": {"output": [{"title": "Major Economic Indicators Latest Numbers", "url": "https://www.bls.gov/bls/", "source": "BLS", "published_date": "2026-04-30"}]},
            },
        },
    }

    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""

    assert "AAPL" in md
    assert "MSFT" in md
    assert "404" in md
    assert "折现率" in md
    assert "关注" in md


def test_render_chat_empty_primary_renderer_falls_back_to_multitask(monkeypatch):
    import importlib

    render_mod = importlib.import_module("backend.graph.nodes.render_stub")

    monkeypatch.setattr(render_mod, "render_chat_markdown", lambda _state: "")

    state = {
        "query": "AAPL 价格和这个链接怎么看？",
        "output_mode": "chat",
        "operation": {"name": "qa", "confidence": 0.8, "params": {}},
        "subject": {"subject_type": "company", "tickers": ["AAPL"], "selection_payload": []},
        "tasks": [
            {
                "id": "task_price",
                "subject_type": "company",
                "subject_label": "AAPL",
                "tickers": ["AAPL"],
                "operation": {"name": "price", "confidence": 0.8, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_url",
                "subject_type": "research_doc",
                "subject_label": "链接内容",
                "tickers": ["AAPL"],
                "operation": {"name": "fetch", "confidence": 0.8, "params": {"url": "https://example.com/aapl"}},
                "status": "ready",
            },
        ],
        "plan_ir": {
            "steps": [
                {"id": "s1", "kind": "tool", "name": "get_stock_price", "inputs": {"ticker": "AAPL"}, "task_ids": ["task_price"]},
                {"id": "s2", "kind": "tool", "name": "fetch_url_content", "inputs": {"url": "https://example.com/aapl"}, "task_ids": ["task_url"]},
            ]
        },
        "artifacts": {
            "step_results": {
                "s1": {"output": {"ticker": "AAPL", "price": 276.83, "change_percent": -1.22}},
                "s2": {"output": {"url": "https://example.com/aapl", "error": "404 Client Error"}},
            }
        },
    }

    md = (render_mod.render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""

    assert md.strip()
    assert "AAPL" in md
    assert "这轮没有合成出可用文字" not in md


def test_render_filing_report_includes_section_level_citations():
    state = {
        "query": "解读最新 10-K",
        "output_mode": "investment_report",
        "operation": {"name": "summarize", "confidence": 0.8, "params": {}},
        "subject": {
            "subject_type": "filing",
            "tickers": ["AAPL"],
            "selection_ids": ["f1"],
            "selection_types": ["filing"],
            "selection_payload": [{"type": "filing", "id": "f1", "title": "AAPL 10-K"}],
        },
        "artifacts": {
            "evidence_pool": [
                {
                    "title": "Form 10-K Item 1A Risk Factors",
                    "url": "https://example.com/aapl-10k#item1a",
                    "snippet": "Item 1A details principal risks.",
                    "source": "sec",
                }
            ]
        },
    }
    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""
    assert "Section-Level Citations" in md
    assert "Item 1A" in md

# -*- coding: utf-8 -*-
from backend.graph.nodes.render_stub import render_stub


def test_render_news_brief_uses_news_template_not_company_report():
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
    assert "### 新闻摘要" in md
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


def test_render_company_brief_does_not_leak_evidence_pool_by_default():
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
    assert "[T](https://example.com)" not in md


def test_render_company_brief_includes_price_and_technical_sections():
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
    assert "### 价格快照" in md
    assert "### 技术面" in md
    assert "$100" in md
    assert "RSI(14): 55" in md


def test_render_company_compare_uses_compare_template():
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
        "artifacts": {"render_vars": {"comparison_conclusion": "- x", "comparison_metrics": "- y"}},
    }
    md = (render_stub(state).get("artifacts") or {}).get("draft_markdown") or ""
    assert "## 对比快评" in md
    assert "AAPL vs MSFT" in md


def test_render_company_fetch_uses_company_news_template():
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
    assert "### 公司快讯" in md
    assert "### 最新新闻" in md

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

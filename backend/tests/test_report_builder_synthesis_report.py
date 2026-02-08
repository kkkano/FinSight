# -*- coding: utf-8 -*-

from backend.graph.report_builder import _count_content_chars, build_report_payload


def test_count_content_chars_ignores_raw_urls():
    markdown = "Hello https://example.com/path/to/resource\n"
    assert _count_content_chars(markdown) == 1


def test_synthesis_report_does_not_include_evidence_overview_or_duplicate_query():
    query = "详细分析苹果公司，生成投资报告"
    unique_url = "https://example.com/unique-evidence"
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "policy": {
            "allowed_agents": [
                "price_agent",
                "news_agent",
                "fundamental_agent",
                "technical_agent",
                "macro_agent",
                "deep_search_agent",
            ]
        },
        "plan_ir": {"steps": []},
        "artifacts": {
            # Template already contains a single 问题 行; synthesis_report must not repeat it again.
            "draft_markdown": f"## 投资研报：AAPL\n\n**问题**：{query}\n\n## 投资摘要\n- ...\n",
            "evidence_pool": [
                {
                    "title": "Evidence",
                    "url": unique_url,
                    "snippet": "Snippet",
                    "source": "unit-test",
                    "published_date": "2026-02-05T00:00:00Z",
                    "confidence": 0.7,
                }
            ],
            "step_results": {},
            "errors": [],
            "render_vars": {},
        },
        "trace": {},
    }

    report = build_report_payload(state=state, query=query, thread_id="t1")
    assert isinstance(report, dict)
    synthesis_report = report.get("synthesis_report") or ""
    assert isinstance(synthesis_report, str)

    assert "证据池概览" not in synthesis_report
    assert unique_url not in synthesis_report
    assert synthesis_report.count(query) == 1


def test_build_report_payload_filing_includes_section_level_citations_in_meta_and_sections():
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "filing", "tickers": ["AAPL"]},
        "policy": {"allowed_agents": []},
        "plan_ir": {"steps": []},
        "artifacts": {
            "draft_markdown": "## 文档解读\n\n",
            "evidence_pool": [
                {
                    "title": "10-K Item 7 Management Discussion",
                    "url": "https://example.com/10k#item7",
                    "snippet": "Item 7 discusses liquidity and operations.",
                    "source": "sec",
                    "published_date": "2026-02-01T00:00:00Z",
                    "confidence": 0.8,
                }
            ],
            "step_results": {},
            "errors": [],
            "render_vars": {},
        },
        "trace": {},
    }

    report = build_report_payload(state=state, query="解读AAPL 10-K", thread_id="t-filing")
    assert isinstance(report, dict)

    meta = report.get("meta") or {}
    section_refs = meta.get("filing_section_citations")
    assert isinstance(section_refs, list)
    assert section_refs and section_refs[0].get("section") == "Item 7"

    sections = report.get("sections") or []
    assert any((s.get("title") or "") == "Section-level Citations" for s in sections)


def test_build_report_payload_agent_status_exposes_evidence_quality_and_skip_reason():
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "policy": {"allowed_agents": ["fundamental_agent", "macro_agent"]},
        "plan_ir": {
            "steps": [
                {"id": "s1", "kind": "agent", "name": "fundamental_agent"},
                {"id": "s2", "kind": "agent", "name": "macro_agent"},
            ]
        },
        "artifacts": {
            "draft_markdown": "## Report\n",
            "evidence_pool": [],
            "errors": [],
            "render_vars": {},
            "step_results": {
                "s1": {
                    "output": {
                        "summary": "ok",
                        "confidence": 0.8,
                        "data_sources": ["yfinance"],
                        "evidence_quality": {"overall_score": 0.77, "has_conflicts": False},
                    }
                },
                "s2": {
                    "output": {
                        "skipped": True,
                        "reason": "escalation_not_needed",
                    }
                },
            },
        },
        "trace": {},
    }

    report = build_report_payload(state=state, query="analyze AAPL", thread_id="t-status")
    assert isinstance(report, dict)

    agent_status = report.get("agent_status") or {}
    fundamental = agent_status.get("fundamental_agent") or {}
    macro = agent_status.get("macro_agent") or {}

    assert fundamental.get("status") == "success"
    assert isinstance(fundamental.get("evidence_quality"), dict)
    assert fundamental.get("evidence_quality", {}).get("overall_score") == 0.77

    assert macro.get("status") == "not_run"
    assert macro.get("skipped_reason") == "escalation_not_needed"
    assert macro.get("escalation_not_needed") is True


def test_build_report_payload_adds_compare_and_conflict_hints_and_tags():
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["AAPL", "MSFT"]},
        "policy": {"allowed_agents": ["fundamental_agent", "macro_agent"]},
        "plan_ir": {
            "steps": [
                {"id": "s1", "kind": "agent", "name": "fundamental_agent"},
                {"id": "s2", "kind": "agent", "name": "macro_agent"},
            ]
        },
        "artifacts": {
            "draft_markdown": "## Report\n",
            "evidence_pool": [],
            "errors": [],
            "render_vars": {
                "comparison_conclusion": "AAPL has better margin profile than MSFT in this window.",
                "comparison_metrics": "- Gross margin spread\n- Revenue growth spread",
            },
            "step_results": {
                "s1": {
                    "output": {
                        "summary": "ok",
                        "confidence": 0.8,
                        "data_sources": ["yfinance"],
                        "evidence_quality": {"overall_score": 0.77, "has_conflicts": False},
                    }
                },
                "s2": {
                    "output": {
                        "summary": "macro with conflict",
                        "confidence": 0.6,
                        "data_sources": ["fmp"],
                        "evidence_quality": {"overall_score": 0.61, "has_conflicts": True},
                    }
                },
            },
        },
        "trace": {},
    }

    report = build_report_payload(state=state, query="compare AAPL vs MSFT", thread_id="t-hints")
    assert isinstance(report, dict)

    tags = report.get("tags") or []
    assert "compare" in tags
    assert "conflict" in tags

    hints = report.get("report_hints") or {}
    assert hints.get("is_compare") is True
    assert hints.get("has_conflict") is True
    assert "macro_agent" in (hints.get("conflict_agents") or [])

    meta_hints = ((report.get("meta") or {}).get("report_hints") or {})
    assert meta_hints.get("is_compare") is True
    assert meta_hints.get("has_conflict") is True

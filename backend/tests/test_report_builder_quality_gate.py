# -*- coding: utf-8 -*-

from backend.graph.report_builder import _build_report_quality_hints, build_report_payload


def test_build_report_payload_adds_quality_gap_for_deep_report_when_requirements_missing():
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "policy": {"allowed_agents": []},
        "plan_ir": {"steps": []},
        "artifacts": {
            "draft_markdown": "## 投资研报：AAPL\n\n",
            "evidence_pool": [
                {
                    "title": "Apple 10-K",
                    "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                    "snippet": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                    "source": "sec",
                    "published_date": "2026-02-05T00:00:00Z",
                    "confidence": 0.8,
                }
            ],
            "step_results": {},
            "errors": [],
            "render_vars": {"investment_summary": "测试摘要"},
        },
        "trace": {},
    }

    report = build_report_payload(
        state=state,
        query="请做 Apple 深度投资报告（deep report，filing document longform）",
        thread_id="t-quality-gap",
    )
    assert isinstance(report, dict)

    tags = report.get("tags") or []
    assert "quality_gap" in tags

    risks = report.get("risks") or []
    assert any("质量门槛未满足" in str(item) for item in risks)

    synthesis_report = report.get("synthesis_report") or ""
    assert "## 研究完整性校验" in synthesis_report

    hints = report.get("report_hints") or {}
    quality = hints.get("quality") or {}
    assert quality.get("deep_report_required") is True
    assert quality.get("qualified") is False
    assert isinstance(quality.get("missing_requirements"), list)
    assert quality.get("missing_requirements")
    report_quality = report.get("report_quality") or {}
    assert report_quality.get("state") in {"warn", "block"}
    assert isinstance(report_quality.get("reasons"), list)


def test_build_report_payload_no_quality_gap_when_deep_report_requirements_are_met():
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "policy": {"allowed_agents": []},
        "plan_ir": {"steps": []},
        "artifacts": {
            "draft_markdown": "## 投资研报：AAPL\n\n",
            "evidence_pool": [
                {
                    "title": "Apple 10-K annual report",
                    "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                    "snippet": "Apple annual filing discusses revenue mix, gross margin trend, and capital allocation policy in detail.",
                    "source": "sec",
                    "published_date": "2026-02-05T00:00:00Z",
                    "confidence": 0.8,
                },
                {
                    "title": "Apple 10-Q quarterly report",
                    "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000008/aapl-20241228.htm",
                    "snippet": "Quarterly filing provides updated segment growth, cash flow changes, and working capital profile.",
                    "source": "sec",
                    "published_date": "2026-02-05T00:00:00Z",
                    "confidence": 0.8,
                },
                {
                    "title": "Apple earnings call transcript",
                    "url": "https://www.cnbc.com/2026/02/10/apple-earnings-call-transcript.html",
                    "snippet": "Management answered questions on guidance, iPhone demand, AI roadmap, and margin outlook.",
                    "source": "cnbc",
                    "published_date": "2026-02-05T00:00:00Z",
                    "confidence": 0.8,
                },
                {
                    "title": "CNBC Apple coverage",
                    "url": "https://www.cnbc.com/quotes/AAPL",
                    "snippet": "CNBC coverage summarizes analyst rating changes and short-term risk sentiment after earnings.",
                    "source": "cnbc",
                    "published_date": "2026-02-05T00:00:00Z",
                    "confidence": 0.8,
                },
            ],
            "step_results": {},
            "errors": [],
            "render_vars": {"investment_summary": "测试摘要"},
        },
        "trace": {},
    }

    report = build_report_payload(
        state=state,
        query="请做 Apple 深度投资报告（deep report，filing document longform）",
        thread_id="t-quality-pass",
    )
    assert isinstance(report, dict)

    tags = report.get("tags") or []
    assert "quality_gap" not in tags

    hints = report.get("report_hints") or {}
    quality = hints.get("quality") or {}
    assert quality.get("deep_report_required") is True
    assert quality.get("qualified") is True


def test_quality_hints_technical_query_does_not_require_10k_or_10q():
    quality = _build_report_quality_hints(
        query="AAPL technical analysis with RSI and MACD",
        citations=[
            {
                "title": "AAPL technical snapshot",
                "url": "https://www.cnbc.com/quotes/AAPL",
                "snippet": "RSI and MACD indicate neutral momentum while price stays near short-term support.",
            }
        ],
    )

    assert quality.get("report_type") == "technical"
    assert quality.get("deep_report_required") is False
    missing = quality.get("missing_requirements") or []
    assert all("10-K" not in str(item) and "10-Q" not in str(item) for item in missing)


def test_build_report_payload_quality_penalty_is_graded_not_hard_capped():
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "policy": {"allowed_agents": ["price_agent", "news_agent"]},
        "plan_ir": {
            "steps": [
                {"id": "s1", "kind": "agent", "name": "price_agent", "inputs": {}},
                {"id": "s2", "kind": "agent", "name": "news_agent", "inputs": {}},
            ]
        },
        "artifacts": {
            "draft_markdown": "## 投资研报：AAPL\n\n",
            "evidence_pool": [
                {
                    "title": "Apple 10-K annual report",
                    "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
                    "snippet": "short",
                    "source": "sec",
                    "published_date": "2026-02-05T00:00:00Z",
                    "confidence": 0.8,
                },
                {
                    "title": "Apple 10-Q quarterly report",
                    "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019325000008/aapl-20241228.htm",
                    "snippet": "short",
                    "source": "sec",
                    "published_date": "2026-02-05T00:00:00Z",
                    "confidence": 0.8,
                },
                {
                    "title": "Apple earnings call transcript",
                    "url": "https://www.cnbc.com/2026/02/10/apple-earnings-call-transcript.html",
                    "snippet": "short",
                    "source": "cnbc",
                    "published_date": "2026-02-10T00:00:00Z",
                    "confidence": 0.8,
                },
            ],
            "step_results": {
                "s1": {"output": {"summary": "price ok", "confidence": 0.95}},
                "s2": {"output": {"summary": "news ok", "confidence": 0.95}},
            },
            "errors": [],
            "render_vars": {"investment_summary": "测试摘要"},
        },
        "trace": {},
    }

    report = build_report_payload(
        state=state,
        query="AAPL deep report with filing and transcript checks",
        thread_id="t-quality-graded-penalty",
    )
    assert isinstance(report, dict)

    confidence = float(report.get("confidence_score") or 0.0)
    # Only snippet quality missing => minor penalty, should stay well above legacy hard cap 0.62.
    assert confidence > 0.85


def test_build_report_payload_populates_grounding_metadata():
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "policy": {"allowed_agents": []},
        "plan_ir": {"steps": []},
        "artifacts": {
            "draft_markdown": "## 投资研报：AAPL\n\n",
            "evidence_pool": [
                {
                    "title": "AAPL valuation update",
                    "url": "https://example.com/aapl-valuation",
                    "snippet": "AAPL 当前 PE 28.5x，营收增长 12%，毛利率 44%。",
                    "source": "example",
                    "published_date": "2026-02-18T00:00:00Z",
                    "confidence": 0.8,
                }
            ],
            "step_results": {},
            "errors": [],
            "render_vars": {
                "investment_summary": "当前PE 28.5x，营收增长12%，估值仍有支撑。",
                "valuation": "估值面：PE 28.5x，毛利率44%，需关注盈利持续性。",
            },
        },
        "trace": {},
    }

    report = build_report_payload(
        state=state,
        query="请做 AAPL 投资分析",
        thread_id="t-grounding-ok",
    )
    assert isinstance(report, dict)

    grounding_rate = report.get("grounding_rate")
    assert isinstance(grounding_rate, float)
    assert 0.0 <= grounding_rate <= 1.0

    report_hints = report.get("report_hints") or {}
    grounding = report_hints.get("grounding") or {}
    assert grounding.get("claim_count", 0) > 0
    assert grounding.get("grounded_count", 0) >= 0

    meta = report.get("meta") or {}
    assert isinstance(meta.get("grounding"), dict)


def test_build_report_payload_adds_grounding_gap_when_rate_low():
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "policy": {"allowed_agents": []},
        "plan_ir": {"steps": []},
        "artifacts": {
            "draft_markdown": "## 投资研报：AAPL\n\n",
            "evidence_pool": [
                {
                    "title": "AAPL basic snapshot",
                    "url": "https://example.com/aapl-basic",
                    "snippet": "当前仅包含基础价格与成交量摘要。",
                    "source": "example",
                    "published_date": "2026-02-18T00:00:00Z",
                    "confidence": 0.7,
                }
            ],
            "step_results": {},
            "errors": [],
            "render_vars": {
                "investment_summary": "预计2028Q4发布新产品并带来30%增长。",
                "valuation": "未来两年利润有望提升25%，但证据待验证。",
            },
        },
        "trace": {},
    }

    report = build_report_payload(
        state=state,
        query="请做 AAPL 投资分析",
        thread_id="t-grounding-gap",
    )
    assert isinstance(report, dict)

    tags = report.get("tags") or []
    assert "grounding_gap" in tags

    risks = report.get("risks") or []
    assert any("证据溯源率偏低" in str(item) for item in risks)


def test_build_report_payload_marks_verifier_gap_when_unsupported_claims_exist():
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["GOOG"]},
        "policy": {"allowed_agents": []},
        "plan_ir": {"steps": []},
        "artifacts": {
            "draft_markdown": "## 投资研报：GOOG\n\n",
            "evidence_pool": [
                {
                    "title": "GOOG fundamentals",
                    "url": "https://example.com/goog-fundamentals",
                    "snippet": "Revenue growth 11%, PE 28x, cloud margin improving.",
                    "source": "example",
                    "published_date": "2026-02-18T00:00:00Z",
                    "confidence": 0.8,
                }
            ],
            "step_results": {},
            "errors": [],
            "render_vars": {
                "investment_summary": "基于当前估值与增长，维持中性偏多。",
                "conclusion": "结论偏中性，等待更多证据。",
            },
            "verifier_result": {
                "enabled": True,
                "checked": True,
                "unsupported_claims": [
                    {"claim": "Gemini 2.0 will launch in 2026Q2", "reason": "missing in evidence"}
                ],
            },
        },
        "trace": {},
    }

    report = build_report_payload(
        state=state,
        query="请做 GOOG 深度投资报告",
        thread_id="t-verifier-gap",
    )
    assert isinstance(report, dict)

    tags = report.get("tags") or []
    assert "verifier_gap" in tags

    risks = report.get("risks") or []
    assert any("二次事实核查发现" in str(item) for item in risks)

    hints = report.get("report_hints") or {}
    verifier_hint = hints.get("verifier") or {}
    assert verifier_hint.get("checked") is True
    assert verifier_hint.get("unsupported_count") == 1

    meta = report.get("meta") or {}
    verifier_meta = meta.get("verifier") or {}
    assert verifier_meta.get("checked") is True


def test_build_report_payload_uses_unresolved_verifier_claims_for_quality_gate():
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["GOOG"]},
        "policy": {"allowed_agents": []},
        "plan_ir": {"steps": []},
        "artifacts": {
            "draft_markdown": "## 投资研报：GOOG\n\n",
            "evidence_pool": [
                {
                    "title": "GOOG fundamentals",
                    "url": "https://example.com/goog-fundamentals",
                    "snippet": "Revenue growth 11%, PE 28x, cloud margin improving.",
                    "source": "example",
                    "published_date": "2026-02-18T00:00:00Z",
                    "confidence": 0.8,
                }
            ],
            "step_results": {},
            "errors": [],
            "render_vars": {
                "investment_summary": "基于当前估值与增长，维持中性偏多。",
                "conclusion": "结论偏中性，等待更多证据。",
            },
            "verifier_result": {
                "enabled": True,
                "checked": True,
                "unsupported_claims": [
                    {"claim": "Gemini 2.0 will launch in 2026Q2", "reason": "missing evidence"}
                ],
                "unresolved_unsupported_claims": [],
            },
        },
        "trace": {},
    }

    report = build_report_payload(
        state=state,
        query="请做 GOOG 深度投资报告",
        thread_id="t-verifier-unresolved-empty",
    )
    assert isinstance(report, dict)

    tags = report.get("tags") or []
    assert "verifier_gap" not in tags

    hints = report.get("report_hints") or {}
    verifier_hint = hints.get("verifier") or {}
    assert verifier_hint.get("unsupported_count") == 1
    assert verifier_hint.get("unresolved_unsupported_count") == 0

    quality = report.get("report_quality") or {}
    reasons = quality.get("reasons") or []
    reason_codes = {str(item.get("code")) for item in reasons if isinstance(item, dict)}
    assert "VERIFIER_UNSUPPORTED_CLAIMS_BLOCK" not in reason_codes
    assert "VERIFIER_UNSUPPORTED_CLAIMS_WARN" not in reason_codes


def test_build_report_payload_excludes_not_run_agents_from_sections_and_quality_coverage():
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "policy": {"allowed_agents": ["price_agent", "news_agent", "fundamental_agent"]},
        "plan_ir": {
            "steps": [
                {"id": "s_price", "kind": "agent", "name": "price_agent"},
            ]
        },
        "artifacts": {
            "draft_markdown": "## 投资研报：AAPL\n\n",
            "evidence_pool": [
                {
                    "title": "AAPL valuation note",
                    "url": "https://example.com/aapl/valuation",
                    "snippet": "估值与增长指标更新。",
                    "source": "example",
                    "published_date": "2026-02-18T00:00:00Z",
                    "confidence": 0.8,
                },
                {
                    "title": "AAPL revenue outlook",
                    "url": "https://example.com/aapl/revenue",
                    "snippet": "收入预期与利润率趋势。",
                    "source": "example",
                    "published_date": "2026-02-18T00:00:00Z",
                    "confidence": 0.8,
                },
            ],
            "step_results": {
                "s_price": {
                    "output": {
                        "summary": "价格与估值结论稳定。",
                        "confidence": 0.86,
                        "evidence": [
                            {"url": "https://example.com/aapl/valuation/"},
                            {"url": "https://example.com/aapl/revenue?utm_source=test"},
                        ],
                    }
                }
            },
            "errors": [],
            "render_vars": {"investment_summary": "测试摘要"},
        },
        "trace": {},
    }

    report = build_report_payload(
        state=state,
        query="请做 AAPL 投资分析",
        thread_id="t-not-run-coverage",
    )
    assert isinstance(report, dict)

    sections = report.get("sections") or []
    agent_names = [str(section.get("agent_name") or "") for section in sections]
    assert "news_agent" not in agent_names
    assert "fundamental_agent" not in agent_names

    quality = report.get("report_quality") or {}
    assert quality.get("state") == "pass"
    metrics = quality.get("metrics") or {}
    assert metrics.get("total_blocks") == 1
    assert metrics.get("covered_blocks") == 1


def test_build_report_payload_uses_internal_citations_when_agent_evidence_has_no_url():
    state = {
        "output_mode": "investment_report",
        "subject": {"subject_type": "company", "tickers": ["AAPL"]},
        "policy": {"allowed_agents": ["risk_agent"]},
        "plan_ir": {"steps": [{"id": "s_risk", "kind": "agent", "name": "risk_agent"}]},
        "artifacts": {
            "draft_markdown": "## 投资研报：AAPL\n\n",
            "evidence_pool": [],
            "step_results": {
                "s_risk": {
                    "output": {
                        "summary": "风险评分上升，需关注因子暴露和压力场景。",
                        "confidence": 0.72,
                        "as_of": "2026-02-20T12:00:00Z",
                        "evidence": [
                            {
                                "title": "Risk score snapshot",
                                "text": "Risk score: 67 (high). Primary driver: macro stress.",
                                "source": "risk_rule_engine",
                                "timestamp": "2026-02-20T12:00:00Z",
                            },
                            {
                                "title": "Factor beta exposure",
                                "text": "Market beta 1.31, growth factor beta 0.94.",
                                "source": "factor_model",
                                "timestamp": "2026-02-20T12:00:00Z",
                            },
                        ],
                    }
                }
            },
            "errors": [],
            "render_vars": {"investment_summary": "测试摘要"},
        },
        "trace": {},
    }

    report = build_report_payload(
        state=state,
        query="请做 AAPL 风险分析简报",
        thread_id="t-risk-internal-citations",
    )
    assert isinstance(report, dict)

    sections = report.get("sections") or []
    risk_section = next((section for section in sections if section.get("agent_name") == "risk_agent"), None)
    assert isinstance(risk_section, dict)
    contents = risk_section.get("contents") or []
    refs = contents[0].get("citation_refs") if contents and isinstance(contents[0], dict) else []
    assert isinstance(refs, list)
    assert len(refs) >= 2

    citations = report.get("citations") or []
    citation_url_by_id = {
        str(item.get("source_id")): str(item.get("url") or "")
        for item in citations
        if isinstance(item, dict) and item.get("source_id")
    }
    assert all(ref in citation_url_by_id for ref in refs)
    assert any(citation_url_by_id[ref].startswith("internal://") for ref in refs)

    quality = report.get("report_quality") or {}
    codes = {
        str(item.get("code"))
        for item in (quality.get("reasons") or [])
        if isinstance(item, dict)
    }
    assert "EVIDENCE_COVERAGE_BELOW_MIN" not in codes
    assert "KEY_SECTION_SOURCES_BELOW_MIN" not in codes

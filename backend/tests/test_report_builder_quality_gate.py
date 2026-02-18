# -*- coding: utf-8 -*-

from backend.graph.report_builder import build_report_payload


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
    assert any("深度报告质量门槛未满足" in str(item) for item in risks)

    synthesis_report = report.get("synthesis_report") or ""
    assert "## 研究完整性校验" in synthesis_report

    hints = report.get("report_hints") or {}
    quality = hints.get("quality") or {}
    assert quality.get("deep_report_required") is True
    assert quality.get("qualified") is False
    assert isinstance(quality.get("missing_requirements"), list)
    assert quality.get("missing_requirements")


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
                    "url": "https://www.fool.com/earnings/call-transcripts/2024/10/31/apple-aapl-q4-2024-earnings-call-transcript/",
                    "snippet": "Management answered questions on guidance, iPhone demand, AI roadmap, and margin outlook.",
                    "source": "fool",
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

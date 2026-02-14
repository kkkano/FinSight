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

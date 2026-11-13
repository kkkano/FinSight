"""缺总判断及未校准置信度在报告序列化后保持明确未知。"""
from __future__ import annotations

from backend.graph.report_builder import _build_structured_report_payload
from backend.report.validator import ReportValidator


def test_structured_report_without_conclusion_has_no_default_direction_or_confidence():
    synthesis = {
        "overall_conclusion": None, "claim_index": {}, "task_results": [],
        "evidence_index": {"fact": {"text": "已取得财务数据。", "source_name": "披露文件", "url": "https://example.invalid/report"}},
        "citation_ids": ["fact"], "risks": [],
    }
    artifacts = {
        "research_synthesis": synthesis,
        "research_synthesis_gate": {"state": "warn", "reasons": ["missing_overall_conclusion"]},
        "draft_markdown": "## 总判断\n\n无法判断：证据尚不足以形成总体结论。\n",
    }
    state = {"output_mode": "investment_report", "subject": {"tickers": ["IBM"]}, "artifacts": artifacts}
    report = _build_structured_report_payload(state=state, thread_id="test", artifacts=artifacts)
    assert report["sentiment"] == "unknown"
    assert report["confidence_score"] is None
    assert report["report_quality"]["conclusion_status"] == "unavailable"
    assert report["report_quality"]["confidence_status"] == "uncalibrated"
    assert report["sections"][0]["confidence"] is None
    assert all(citation["confidence"] is None for citation in report["citations"])
    restored = ReportValidator.validate_and_fix(report, as_dict=True)
    assert restored["sentiment"] == "unknown" and restored["confidence_score"] is None
    assert all(citation["confidence"] is None for citation in restored["citations"])


def test_validator_preserves_explicit_legacy_neutral_and_source_confidence():
    restored = ReportValidator.validate_and_fix({
        "report_id": "legacy", "ticker": "IBM", "title": "既有报告", "summary": "既有中性判断",
        "sentiment": "neutral", "confidence_score": 0.8,
        "sections": [{"title": "研究报告", "contents": [{"type": "text", "content": "既有判断"}]}],
        "citations": [{"source_id": "verified", "title": "既有来源", "url": "https://example.invalid/report", "confidence": 0.9}],
    }, as_dict=True)
    assert restored["sentiment"] == "neutral"
    assert restored["confidence_score"] == 0.8
    assert restored["citations"][0]["confidence"] == 0.9

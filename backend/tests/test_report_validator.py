from backend.report.validator import ReportValidator


def test_report_validator_minimal_payload():
    data = {
        "ticker": "AAPL",
        "summary": "Sample summary",
    }
    result = ReportValidator.validate_and_fix(data, as_dict=True)

    assert result["ticker"] == "AAPL"
    assert result["company_name"] == "AAPL"
    assert result["summary"] == "Sample summary"
    assert result["sections"]
    assert result["sentiment"] == "neutral"


def test_report_validator_sentiment_and_confidence():
    data = {
        "ticker": "TSLA",
        "summary": "Summary",
        "sentiment": "unknown",
        "confidence_score": 2.5,
    }
    result = ReportValidator.validate_and_fix(data, as_dict=True)

    assert result["sentiment"] == "neutral"
    assert result["confidence_score"] == 1.0


def test_report_validator_sections_and_types():
    data = {
        "ticker": "MSFT",
        "summary": "Summary",
        "sections": [
            {
                "title": "Section 1",
                "order": "1",
                "contents": [
                    {"type": "unknown", "content": "Hello", "citation_refs": "bad"},
                ],
            }
        ],
    }
    result = ReportValidator.validate_and_fix(data, as_dict=True)

    section = result["sections"][0]
    assert section["order"] == 1
    assert section["contents"][0]["type"] == "text"
    assert isinstance(section["contents"][0]["citation_refs"], list)


def test_report_validator_section_metadata():
    data = {
        "ticker": "META",
        "summary": "Summary",
        "sections": [
            {
                "title": "Section 1",
                "order": 1,
                "confidence": 0.82,
                "agent_name": "NewsAgent",
                "data_sources": ["news", "search"],
                "contents": [
                    {"type": "text", "content": "Hello"},
                ],
            }
        ],
    }
    result = ReportValidator.validate_and_fix(data, as_dict=True)

    section = result["sections"][0]
    assert section["confidence"] == 0.82
    assert section["agent_name"] == "NewsAgent"
    assert section["data_sources"] == ["news", "search"]


def test_report_validator_risks_recommendation():
    data = {
        "ticker": "NVDA",
        "summary": "Summary",
        "risks": ["Valuation risk", "Macro risk"],
        "recommendation": "BUY",
    }
    result = ReportValidator.validate_and_fix(data, as_dict=True)

    assert "Valuation risk" in result["risks"]
    assert "Macro risk" in result["risks"]
    assert result["recommendation"] == "BUY"


def test_report_validator_citations_fields():
    data = {
        "ticker": "AAPL",
        "summary": "Summary",
        "citations": [
            {
                "source_id": "1",
                "title": "Example",
                "url": "https://example.com",
                "snippet": "Snippet",
                "published_date": "2026-01-20T00:00:00",
            }
        ],
    }
    result = ReportValidator.validate_and_fix(data, as_dict=True)

    citation = result["citations"][0]
    assert "confidence" in citation
    assert "freshness_hours" in citation
    assert 0.0 <= citation["confidence"] <= 1.0
    assert citation["freshness_hours"] >= 0.0


def test_report_validator_evidence_policy_filters_invalid_refs():
    data = {
        "ticker": "AAPL",
        "summary": "Summary",
        "citations": [
            {
                "source_id": "src_1",
                "title": "Example",
                "url": "https://example.com",
                "snippet": "Snippet",
                "published_date": "2026-01-20T00:00:00",
            }
        ],
        "sections": [
            {
                "title": "Summary",
                "order": 1,
                "contents": [
                    {"type": "text", "content": "Hello", "citation_refs": ["src_1", "bad_ref"]},
                ],
            }
        ],
    }
    result = ReportValidator.validate_and_fix(data, as_dict=True)

    refs = result["sections"][0]["contents"][0]["citation_refs"]
    assert refs == ["src_1"]
    policy = result["meta"]["evidence_policy"]
    assert "bad_ref" in policy["invalid_refs"]


def test_report_validator_evidence_policy_flags_low_coverage():
    data = {
        "ticker": "AAPL",
        "summary": "Summary",
        "citations": [
            {
                "source_id": "src_1",
                "title": "Example",
                "url": "https://example.com",
                "snippet": "Snippet",
                "published_date": "2026-01-20T00:00:00",
            }
        ],
        "sections": [
            {
                "title": "Key Findings",
                "order": 1,
                "contents": [
                    {"type": "text", "content": "Block A", "citation_refs": ["src_1"]},
                    {"type": "text", "content": "Block B", "citation_refs": []},
                ],
            }
        ],
    }
    result = ReportValidator.validate_and_fix(data, as_dict=True)
    policy = result["meta"]["evidence_policy"]
    assert policy["status"] == "warning"
    assert any("证据覆盖率" in risk for risk in result["risks"])

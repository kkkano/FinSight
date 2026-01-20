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


def test_report_validator_risks_recommendation():
    data = {
        "ticker": "NVDA",
        "summary": "Summary",
        "risks": ["Valuation risk", "Macro risk"],
        "recommendation": "BUY",
    }
    result = ReportValidator.validate_and_fix(data, as_dict=True)

    assert result["risks"] == ["Valuation risk", "Macro risk"]
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

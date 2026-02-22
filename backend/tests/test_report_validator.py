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
    assert policy["status"] == "block"
    report_quality = result.get("report_quality")
    assert isinstance(report_quality, dict)
    assert report_quality.get("state") == "block"
    reasons = report_quality.get("reasons") or []
    assert any(reason.get("code") == "EVIDENCE_COVERAGE_BELOW_MIN" for reason in reasons)
    assert any("证据覆盖率或引用来源不足" in risk for risk in result["risks"])


def test_report_validator_evidence_policy_excludes_appendix_from_coverage_denominator():
    data = {
        "ticker": "AAPL",
        "summary": "Summary",
        "citations": [
            {
                "source_id": "src_1",
                "title": "Example",
                "url": "https://example.com/1",
                "snippet": "Snippet",
                "published_date": "2026-01-20T00:00:00",
            },
            {
                "source_id": "src_2",
                "title": "Example2",
                "url": "https://example.com/2",
                "snippet": "Snippet2",
                "published_date": "2026-01-21T00:00:00",
            },
        ],
        "sections": [
            {
                "title": "Summary",
                "order": 1,
                "contents": [
                    {"type": "text", "content": "Main block", "citation_refs": ["src_1", "src_2"]},
                ],
            },
            {
                "title": "Section-level Citations",
                "order": 2,
                "contents": [
                    {
                        "type": "text",
                        "content": "- Item 7: [src_1], [src_2]",
                        "citation_refs": ["src_1", "src_2"],
                        "metadata": {"exclude_from_quality_coverage": True},
                    }
                ],
            },
        ],
    }

    result = ReportValidator.validate_and_fix(data, as_dict=True)
    report_quality = result.get("report_quality") or {}
    metrics = report_quality.get("metrics") or {}

    assert report_quality.get("state") == "pass"
    assert metrics.get("total_blocks") == 1
    assert metrics.get("covered_blocks") == 1


def test_report_validator_evidence_policy_adds_structured_key_section_issue_details():
    data = {
        "ticker": "AAPL",
        "summary": "Summary",
        "citations": [
            {
                "source_id": "src_1",
                "title": "Example",
                "url": "https://example.com/key",
                "snippet": "Snippet",
                "published_date": "2026-01-20T00:00:00",
            }
        ],
        "sections": [
            {
                "title": "Executive Summary",
                "order": 1,
                "contents": [
                    {"type": "text", "content": "Key section block", "citation_refs": ["src_1"]},
                ],
            }
        ],
    }

    result = ReportValidator.validate_and_fix(data, as_dict=True)
    report_quality = result.get("report_quality") or {}
    details = report_quality.get("details") or {}
    thresholds = report_quality.get("thresholds") or {}
    threshold = thresholds.get("min_key_section_sources") or 1

    issue_details = details.get("key_section_issue_details") or []
    assert isinstance(issue_details, list)
    assert issue_details
    assert issue_details[0].get("section") == "Executive Summary"
    assert issue_details[0].get("actual") == 1
    assert issue_details[0].get("threshold") == threshold


def test_report_validator_internal_only_key_section_shortfall_is_warn():
    data = {
        "ticker": "AAPL",
        "summary": "Summary",
        "citations": [
            {
                "source_id": "int_1",
                "title": "Risk engine snapshot",
                "url": "internal://risk-signal",
                "snippet": "Risk score moved to high zone.",
                "published_date": "2026-01-20T00:00:00",
            },
            {
                "source_id": "src_2",
                "title": "Macro source",
                "url": "https://example.com/macro",
                "snippet": "Macro regime remains tight.",
                "published_date": "2026-01-20T00:00:00",
            },
        ],
        "sections": [
            {
                "title": "Risk Outlook",
                "order": 1,
                "contents": [
                    {"type": "text", "content": "Key risk section", "citation_refs": ["int_1"]},
                ],
            },
            {
                "title": "Market Context",
                "order": 2,
                "contents": [
                    {"type": "text", "content": "Supplementary context", "citation_refs": ["src_2"]},
                ],
            },
        ],
    }

    result = ReportValidator.validate_and_fix(data, as_dict=True)
    report_quality = result.get("report_quality") or {}
    assert report_quality.get("state") == "warn"

    reasons = [item for item in (report_quality.get("reasons") or []) if isinstance(item, dict)]
    severity_by_code = {str(item.get("code")): str(item.get("severity")) for item in reasons}
    assert severity_by_code.get("KEY_SECTION_INTERNAL_SOURCES_BELOW_MIN") == "warn"
    assert "KEY_SECTION_SOURCES_BELOW_MIN" not in severity_by_code

    details = report_quality.get("details") or {}
    issue_details = details.get("key_section_issue_details") or []
    assert issue_details
    assert issue_details[0].get("section") == "Risk Outlook"
    assert issue_details[0].get("internal_only") is True

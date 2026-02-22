# -*- coding: utf-8 -*-
"""
Frozen API/Graph/SSE contract versions.
"""

CHAT_REQUEST_SCHEMA_VERSION = "chat.request.v1"
CHAT_RESPONSE_SCHEMA_VERSION = "chat.response.v1"
GRAPH_STATE_SCHEMA_VERSION = "graph.state.v1"
SSE_EVENT_SCHEMA_VERSION = "chat.sse.v1"
TRACE_SCHEMA_VERSION = "trace.v1"
DASHBOARD_DATA_SCHEMA_VERSION = "dashboard.data.v2"
REPORT_QUALITY_SCHEMA_VERSION = "report.quality.v1"
REPORT_QUALITY_REASON_CODES_VERSION = "report.quality.reason-codes.v1"
REPORT_QUALITY_REASON_CODES: tuple[str, ...] = (
    "EVIDENCE_COVERAGE_BELOW_MIN",
    "EVIDENCE_SOURCES_BELOW_MIN",
    "GROUNDING_RATE_BELOW_MIN",
    "GROUNDING_RATE_WARN",
    "INVALID_CITATION_REFS_REMOVED",
    "KEY_SECTION_INTERNAL_SOURCES_BELOW_MIN",
    "KEY_SECTION_SOURCES_BELOW_MIN",
    "QUALITY_PROFILE_CRITICAL_MISSING",
    "QUALITY_PROFILE_IMPORTANT_MISSING",
    "QUALITY_PROFILE_MINOR_MISSING",
    "QUALITY_PROFILE_MISSING_LIST",
    "QUALITY_STATE_ONLY",
    "VERIFIER_UNSUPPORTED_CLAIMS_BLOCK",
    "VERIFIER_UNSUPPORTED_CLAIMS_WARN",
)


def contract_manifest() -> dict[str, str]:
    return {
        "chat_request": CHAT_REQUEST_SCHEMA_VERSION,
        "chat_response": CHAT_RESPONSE_SCHEMA_VERSION,
        "graph_state": GRAPH_STATE_SCHEMA_VERSION,
        "sse_event": SSE_EVENT_SCHEMA_VERSION,
        "trace": TRACE_SCHEMA_VERSION,
        "dashboard_data": DASHBOARD_DATA_SCHEMA_VERSION,
        "report_quality": REPORT_QUALITY_SCHEMA_VERSION,
    }


def report_quality_reason_codes_manifest() -> dict[str, object]:
    return {
        "schema_version": REPORT_QUALITY_REASON_CODES_VERSION,
        "codes": list(REPORT_QUALITY_REASON_CODES),
    }


__all__ = [
    "CHAT_REQUEST_SCHEMA_VERSION",
    "CHAT_RESPONSE_SCHEMA_VERSION",
    "GRAPH_STATE_SCHEMA_VERSION",
    "SSE_EVENT_SCHEMA_VERSION",
    "TRACE_SCHEMA_VERSION",
    "DASHBOARD_DATA_SCHEMA_VERSION",
    "REPORT_QUALITY_SCHEMA_VERSION",
    "REPORT_QUALITY_REASON_CODES_VERSION",
    "REPORT_QUALITY_REASON_CODES",
    "contract_manifest",
    "report_quality_reason_codes_manifest",
]

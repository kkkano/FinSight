# -*- coding: utf-8 -*-
"""
Frozen API/Graph/SSE contract versions.
"""

CHAT_REQUEST_SCHEMA_VERSION = "chat.request.v1"
CHAT_RESPONSE_SCHEMA_VERSION = "chat.response.v1"
GRAPH_STATE_SCHEMA_VERSION = "graph.state.v1"
SSE_EVENT_SCHEMA_VERSION = "chat.sse.v1"
TRACE_SCHEMA_VERSION = "trace.v1"


def contract_manifest() -> dict[str, str]:
    return {
        "chat_request": CHAT_REQUEST_SCHEMA_VERSION,
        "chat_response": CHAT_RESPONSE_SCHEMA_VERSION,
        "graph_state": GRAPH_STATE_SCHEMA_VERSION,
        "sse_event": SSE_EVENT_SCHEMA_VERSION,
        "trace": TRACE_SCHEMA_VERSION,
    }


__all__ = [
    "CHAT_REQUEST_SCHEMA_VERSION",
    "CHAT_RESPONSE_SCHEMA_VERSION",
    "GRAPH_STATE_SCHEMA_VERSION",
    "SSE_EVENT_SCHEMA_VERSION",
    "TRACE_SCHEMA_VERSION",
    "contract_manifest",
]


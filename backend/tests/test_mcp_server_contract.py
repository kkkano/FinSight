# -*- coding: utf-8 -*-
import json


EXPECTED_TOOLS = {
    "research_company",
    "get_evidence_ledger",
    "run_debate",
    "track_institutional_holdings",
    "get_insider_transactions",
}

FORBIDDEN_SCHEMA_TERMS = {
    "trace",
    "secret",
    "secrets",
    "password",
    "api_key",
    "raw_internal",
    "diagnostic",
    "diagnostics",
}


def _ledger():
    return {
        "ledger_id": "ledger:test",
        "query": "NVDA investment debate",
        "subject": {"tickers": ["NVDA"]},
        "claims": [
            {
                "claim_id": "c-bull-1",
                "claim": "NVDA demand remains strong across data center customers.",
                "stance": "bull",
                "evidence_ids": ["s-1"],
                "confidence": 0.82,
                "agent_name": "fundamental_agent",
            },
            {
                "claim_id": "c-bear-1",
                "claim": "Valuation is vulnerable if AI capex expectations reset.",
                "stance": "bear",
                "evidence_ids": ["s-2"],
                "confidence": 0.7,
                "agent_name": "risk_agent",
            },
        ],
        "sources": [
            {"source_id": "s-1", "title": "Demand note", "source": "filing", "reliability": 0.8},
            {"source_id": "s-2", "title": "Valuation note", "source": "risk", "reliability": 0.65},
        ],
        "uncertainties": ["AI capex durability is uncertain."],
        "contradictions": [{"claim_id": "c-bear-1", "reason": "Growth and valuation signals diverge."}],
    }


def _assert_no_forbidden_keys(payload):
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True).lower()
    for term in FORBIDDEN_SCHEMA_TERMS:
        assert term not in text


def test_mcp_server_is_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MCP_SERVER_ENABLED", raising=False)

    from backend.protocols.mcp_server import build_tool_registry

    registry = build_tool_registry()

    assert registry.enabled is False
    assert registry.list_tools() == []

    result = registry.call_tool("run_debate", {"ledger": _ledger()})

    assert result["isError"] is True
    assert result["error"]["code"] == "mcp_server_disabled"


def test_enabled_registry_exposes_only_read_only_stable_tools(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_ENABLED", "true")

    from backend.protocols.mcp_server import build_tool_registry

    registry = build_tool_registry()
    tools = registry.list_tools()

    assert {tool["name"] for tool in tools} == EXPECTED_TOOLS
    for tool in tools:
        annotations = tool["annotations"]
        assert annotations["readOnlyHint"] is True
        assert annotations["destructiveHint"] is False
        assert annotations["idempotentHint"] is True
        _assert_no_forbidden_keys(
            {
                "description": tool["description"],
                "inputSchema": tool["inputSchema"],
                "outputSchema": tool["outputSchema"],
            }
        )


def test_dispatcher_sanitizes_tool_results(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_ENABLED", "true")

    from backend.protocols.mcp_server import build_tool_registry

    def _unsafe_handler(**_kwargs):
        return {
            "ticker": "NVDA",
            "trace": {"node": "execute_plan"},
            "secret": "do-not-return",
            "nested": {
                "value": 1,
                "raw_internal_diagnostics": {"token": "hidden"},
                "items": [{"password": "hidden"}, {"kept": True}],
            },
        }

    registry = build_tool_registry(handlers={"research_company": _unsafe_handler})

    result = registry.call_tool("research_company", {"ticker": "NVDA", "session_id": "s1"})

    assert result["isError"] is False
    assert result["structuredContent"]["ticker"] == "NVDA"
    assert result["structuredContent"]["nested"]["value"] == 1
    assert result["structuredContent"]["nested"]["items"] == [{}, {"kept": True}]
    _assert_no_forbidden_keys(result)


def test_run_debate_dispatch_uses_existing_debate_artifact(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_ENABLED", "true")

    from backend.protocols.mcp_server import build_tool_registry

    registry = build_tool_registry()

    result = registry.call_tool("run_debate", {"ledger": _ledger(), "query": "NVDA investment debate"})

    assert result["isError"] is False
    artifact = result["structuredContent"]
    assert artifact["status"] == "done"
    assert artifact["ledger_id"] == "ledger:test"
    assert artifact["bull_thesis"]["claim_count"] == 1
    assert artifact["bear_thesis"]["claim_count"] == 1
    _assert_no_forbidden_keys(result)

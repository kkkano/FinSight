# -*- coding: utf-8 -*-


def test_extract_claims_marks_bullish_summary_as_bull():
    from backend.research.claim_extractor import extract_claims_from_agent_output

    claims = extract_claims_from_agent_output(
        {
            "agent_name": "fundamental_agent",
            "summary": "AAPL shows strong revenue growth with upside momentum after a positive earnings beat.",
            "confidence": 0.82,
            "evidence": [{"source_id": "src-1", "text": "earnings beat"}],
        },
        query="Should we buy AAPL?",
        ticker="AAPL",
    )

    assert claims
    assert claims[0]["stance"] == "bull"
    assert "AAPL" in claims[0]["claim"]


def test_infer_stance_marks_risk_or_downside_summary_as_bear_or_risk():
    from backend.research.claim_extractor import infer_stance

    stance = infer_stance(
        "MSFT has downside pressure from margin contraction and regulatory risk.",
        risks=["regulatory risk remains elevated"],
    )

    assert stance in {"bear", "risk"}


def test_conflicting_claims_flow_to_ledger_contradictions_for_core_agents():
    from backend.graph.adapters import agent_adapter
    from backend.research.claim_extractor import conflicts_to_contradictions
    from backend.research.evidence_ledger import from_agent_output

    for agent_name in ["technical_agent", "macro_agent", "fundamental_agent"]:
        output = {
            "agent_name": agent_name,
            "summary": f"{agent_name} sees mixed signals for NVDA.",
            "confidence": 0.61,
            "evidence": [{"source_id": f"{agent_name}-src", "text": "indicator evidence"}],
            "data_sources": ["unit"],
            "conflicting_claims": [
                {"claim": "Momentum is bullish", "conflicts_with": "Valuation downside remains high"}
            ],
        }

        contradictions = conflicts_to_contradictions(output)
        normalized = agent_adapter._normalize_agent_output(
            step_name=agent_name,
            output=output,
            query="Analyze NVDA",
            ticker="NVDA",
        )
        ledger = from_agent_output(
            normalized,
            query="Analyze NVDA",
            subject={"ticker": "NVDA"},
            task_ids=[agent_name],
        )

        assert contradictions
        assert normalized["conflicting_claims"] == output["conflicting_claims"]
        assert ledger.contradictions == output["conflicting_claims"]


def test_adapter_preserves_legacy_keys_and_adds_claims():
    from backend.graph.adapters import agent_adapter

    normalized = agent_adapter._normalize_agent_output(
        step_name="fundamental_agent",
        output={
            "summary": "TSLA has improving margins and upside from deliveries.",
            "confidence": 0.77,
            "evidence": [{"source_id": "delivery-src", "text": "delivery update"}],
            "data_sources": ["filing", "market_data"],
        },
        query="Analyze TSLA",
        ticker="TSLA",
    )

    for key in ["summary", "evidence", "confidence", "data_sources"]:
        assert key in normalized
    assert normalized["claims"]
    assert normalized["claims"][0]["stance"] == "bull"

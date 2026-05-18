# -*- coding: utf-8 -*-
from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from backend.agents.base_agent import AgentOutput, EvidenceItem
from backend.research.evidence_ledger import (
    EvidenceLedger,
    ResearchClaim,
    SourceRef,
    from_agent_output,
    to_prompt_context,
)


def test_research_claim_rejects_empty_claim() -> None:
    with pytest.raises(ValidationError):
        ResearchClaim(
            claim_id="claim:empty",
            claim="   ",
            stance="neutral",
            evidence_ids=[],
            confidence=0.5,
            agent_name="news_agent",
            task_ids=[],
            limitations=[],
        )


def test_evidence_ledger_keeps_contract_fields() -> None:
    source = SourceRef(
        source_id="source:reuters:aapl",
        title="Apple quarterly report",
        url="https://example.com/aapl",
        source="Reuters",
        published_date="2026-05-01",
        as_of="2026-05-02T09:30:00",
        reliability=0.92,
        freshness_hours=12.0,
        layer="kb",
        collection="kb:stock:AAPL",
    )
    claim = ResearchClaim(
        claim_id="claim:aapl:margin",
        claim="Apple margin improved year over year.",
        stance="bull",
        evidence_ids=[source.source_id],
        confidence=0.81,
        agent_name="fundamental_agent",
        task_ids=["task-1"],
        limitations=["latest quarter only"],
    )

    ledger = EvidenceLedger(
        ledger_id="ledger:aapl:test",
        query="AAPL margin outlook",
        subject={"ticker": "AAPL", "asset_type": "equity"},
        claims=[claim],
        sources=[source],
        uncertainties=["FX sensitivity remains unclear"],
        contradictions=[{"claim_id": claim.claim_id, "reason": "one source reports flat margin"}],
        coverage_targets=[
            {"target": "margin", "status": "covered"},
            {"target": "risks", "status": "partial"},
        ],
    )

    assert ledger.claims == [claim]
    assert ledger.sources == [source]
    assert ledger.uncertainties == ["FX sensitivity remains unclear"]
    assert ledger.contradictions == [{"claim_id": claim.claim_id, "reason": "one source reports flat margin"}]
    assert ledger.subject == {"ticker": "AAPL", "asset_type": "equity"}
    assert ledger.coverage_targets == [
        {"target": "margin", "status": "covered"},
        {"target": "risks", "status": "partial"},
    ]


def test_from_agent_output_links_legacy_evidence_without_mutating_output() -> None:
    evidence = [
        EvidenceItem(
            text="Revenue grew 8% year over year.",
            source="sec",
            url="https://example.com/sec/aapl-10q",
            timestamp="2026-05-01",
            confidence=0.93,
            title="AAPL 10-Q",
            meta={
                "as_of": "2026-05-02T10:00:00",
                "reliability": 0.97,
                "freshness_hours": 24,
                "layer": "kb",
                "collection": "kb:stock:AAPL",
                "raw_trace": {"token": "secret-token"},
                "private_diagnostics": {"debug": True},
            },
        ),
        EvidenceItem(
            text="Management cited services strength.",
            source="earnings_call",
            url="https://example.com/aapl-call",
            timestamp="2026-05-02",
            confidence=0.84,
            title="AAPL earnings call",
            meta={"layer": "ws", "collection": "ws:deepsearch:aapl"},
        ),
    ]
    output = AgentOutput(
        agent_name="fundamental_agent",
        summary="Apple revenue growth remains supported by services strength.",
        evidence=evidence,
        confidence=0.86,
        data_sources=["sec", "earnings_call"],
        as_of="2026-05-02T12:00:00",
        trace=[{"raw_trace": "do-not-copy"}],
    )
    original_evidence = list(output.evidence)
    original_trace = list(output.trace)

    ledger = from_agent_output(
        output,
        query="AAPL growth quality",
        subject={"ticker": "AAPL", "asset_type": "equity"},
        task_ids=["task-1", "task-2"],
    )

    assert isinstance(ledger, EvidenceLedger)
    assert output.evidence == original_evidence
    assert output.trace == original_trace
    assert output.ledger is None
    assert output.claims == []

    assert len(ledger.sources) == 2
    assert len(ledger.claims) == 1
    assert ledger.claims[0].claim == output.summary
    assert ledger.claims[0].evidence_ids == [source.source_id for source in ledger.sources]
    assert ledger.claims[0].agent_name == "fundamental_agent"
    assert ledger.claims[0].task_ids == ["task-1", "task-2"]
    assert ledger.sources[0].reliability == 0.97
    assert ledger.sources[0].freshness_hours == 24
    assert ledger.sources[0].layer == "kb"
    assert ledger.sources[0].collection == "kb:stock:AAPL"


def test_to_prompt_context_is_compact_and_excludes_private_diagnostics() -> None:
    output = AgentOutput(
        agent_name="news_agent",
        summary="A new product launch creates both upside and execution risk.",
        evidence=[
            EvidenceItem(
                text="Private trace should not leak.",
                source="news",
                url="https://example.com/news",
                timestamp="2026-05-03",
                confidence=0.7,
                title="Product launch",
                meta={
                    "raw_trace": "secret-token",
                    "private_diagnostics": {"prompt": "hidden"},
                    "layer": "ws",
                    "collection": "ws:deepsearch:AAPL",
                },
            )
        ],
        confidence=0.72,
        data_sources=["news"],
        as_of="2026-05-03T08:00:00",
        evidence_quality={"private_diagnostics": "secret-token"},
        trace=[{"raw_trace": "secret-token"}],
    )
    ledger = from_agent_output(
        output,
        query="AAPL launch risk",
        subject={"ticker": "AAPL", "asset_type": "equity"},
        task_ids=["task-9"],
    )

    context = to_prompt_context(ledger, max_claims=1, max_sources=1)
    encoded = json.dumps(context, ensure_ascii=False, sort_keys=True)

    assert set(context).issuperset({"ledger_id", "query", "subject", "claims", "sources"})
    assert context["subject"] == {"ticker": "AAPL", "asset_type": "equity"}
    assert len(context["claims"]) == 1
    assert len(context["sources"]) == 1
    assert "trace" not in encoded
    assert "raw_trace" not in encoded
    assert "private_diagnostics" not in encoded
    assert "secret-token" not in encoded

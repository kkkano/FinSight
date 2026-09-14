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
from backend.research.ledger_builder import build_ledger_from_artifacts


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


def test_pool_sources_bind_only_to_claims_in_the_same_task() -> None:
    artifacts = {
        "step_results": {
            "agent-a": {
                "task_ids": ["task-a"],
                "output": {
                    "agent_name": "news_agent",
                    "claims": [{"claim": "Claim for A", "evidence_ids": []}],
                },
            },
            "agent-b": {
                "task_ids": ["task-b"],
                "output": {
                    "agent_name": "news_agent",
                    "claims": [{"claim": "Claim for B", "evidence_ids": []}],
                },
            },
        },
        "evidence_pool": [
            {
                "title": "Source for A",
                "url": "https://example.com/a",
                "source": "fixture",
                "task_ids": ["task-a"],
            },
            {
                "title": "Source for B",
                "url": "https://example.com/b",
                "source": "fixture",
                "task_ids": ["task-b"],
            },
        ],
    }

    ledger = build_ledger_from_artifacts({"query": "A and B"}, artifacts)
    sources = {source["source_id"]: source for source in ledger["sources"]}
    claims = {claim["claim"]: claim for claim in ledger["claims"]}

    assert {source["url"]: source["task_ids"] for source in sources.values()} == {
        "https://example.com/a": ["task-a"],
        "https://example.com/b": ["task-b"],
    }
    assert [sources[source_id]["url"] for source_id in claims["Claim for A"]["evidence_ids"]] == [
        "https://example.com/a"
    ]
    assert [sources[source_id]["url"] for source_id in claims["Claim for B"]["evidence_ids"]] == [
        "https://example.com/b"
    ]


def test_shared_agent_source_merges_task_scope_without_evidence_pool() -> None:
    shared_url = "https://example.com/shared-agent-source"
    artifacts = {
        "step_results": {
            "agent-a": {
                "task_ids": ["task-a"],
                "output": {
                    "agent_name": "news_agent",
                    "claims": [{"claim": "Agent claim for A"}],
                    "evidence": [
                        {
                            "title": "Shared agent source",
                            "url": shared_url,
                            "text": "Evidence observed by task A",
                            "source": "fixture",
                        }
                    ],
                },
            },
            "agent-b": {
                "task_ids": ["task-b"],
                "output": {
                    "agent_name": "news_agent",
                    "claims": [{"claim": "Agent claim for B"}],
                    "evidence": [
                        {
                            "title": "Shared agent source",
                            "url": shared_url,
                            "text": "Evidence observed by task B",
                            "source": "fixture",
                        }
                    ],
                },
            },
        }
    }

    ledger = build_ledger_from_artifacts({"query": "A and B share a source"}, artifacts)

    assert len(ledger["sources"]) == 1
    source = ledger["sources"][0]
    claims = {claim["claim"]: claim for claim in ledger["claims"]}
    assert source["url"] == shared_url
    assert source["task_ids"] == ["task-a", "task-b"]
    assert claims["Agent claim for A"]["task_ids"] == ["task-a"]
    assert claims["Agent claim for B"]["task_ids"] == ["task-b"]
    assert claims["Agent claim for A"]["evidence_ids"] == [source["source_id"]]
    assert claims["Agent claim for B"]["evidence_ids"] == [source["source_id"]]


def test_embedded_ledger_claim_inherits_step_scope_without_binding_other_task_pool() -> None:
    task_a_url = "https://example.com/deepsearch-a"
    task_b_url = "https://example.com/deepsearch-b"
    artifacts = {
        "step_results": {
            "deepsearch-a": {
                "task_ids": ["task-a"],
                "output": {
                    "agent_name": "deep_search_agent",
                    "ledger": {
                        "ledger_id": "ledger:deepsearch-a",
                        "query": "DeepSearch A",
                        "subject": {"ticker": "AAPL"},
                        "sources": [
                            {
                                "source_id": "deep-source-a",
                                "title": "DeepSearch source A",
                                "url": task_a_url,
                                "source": "deep_search",
                            }
                        ],
                        "claims": [
                            {
                                "claim_id": "claim:missing-scope",
                                "claim": "Embedded claim without scope",
                                "evidence_ids": [],
                            },
                            {
                                "claim_id": "claim:explicit-scope",
                                "claim": "Embedded claim with explicit scope",
                                "evidence_ids": ["deep-source-a"],
                                "task_ids": ["task-explicit"],
                            },
                        ],
                    },
                },
            }
        },
        "evidence_pool": [
            {
                "title": "Pool source A",
                "url": task_a_url,
                "source": "fixture",
                "task_ids": ["task-a"],
            },
            {
                "title": "Pool source B",
                "url": task_b_url,
                "source": "fixture",
                "task_ids": ["task-b"],
            },
        ],
    }

    ledger = build_ledger_from_artifacts({"query": "DeepSearch A"}, artifacts)
    sources = {source["source_id"]: source for source in ledger["sources"]}
    claims = {claim["claim_id"]: claim for claim in ledger["claims"]}
    inherited = claims["claim:missing-scope"]

    assert inherited["task_ids"] == ["task-a"]
    assert [sources[source_id]["url"] for source_id in inherited["evidence_ids"]] == [
        task_a_url
    ]
    assert claims["claim:explicit-scope"]["task_ids"] == ["task-explicit"]

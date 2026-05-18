# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from backend.agents.base_agent import AgentOutput, EvidenceItem
from backend.agents.base_agent import BaseFinancialAgent
from backend.research.agent_quality_contract import (
    apply_agent_quality_contract,
    assign_evidence_source_ids,
    build_agent_claim,
    evaluate_agent_quality,
)


def _output_with_evidence() -> AgentOutput:
    return AgentOutput(
        agent_name="fundamental",
        summary="Apple revenue growth is supported by services strength.",
        evidence=[
            EvidenceItem(
                text="Revenue: $92.0B, +4.5% YoY",
                source="yfinance",
                url="https://finance.yahoo.com/quote/AAPL/financials/",
                timestamp="2026-03-31",
                confidence=0.9,
                meta={"metric_key": "revenue"},
            ),
            EvidenceItem(
                text="EPS revision signal: positive",
                source="yfinance_earnings",
                timestamp="2026-05-18T00:00:00Z",
                confidence=0.8,
                meta={"metric_key": "eps_revision_signal"},
            ),
        ],
        confidence=0.86,
        data_sources=["yfinance", "yfinance_earnings"],
        as_of="2026-05-18T00:00:00Z",
        evidence_quality={"existing_metric": 1},
        risks=["基本面数据未见重大风险信号。"],
    )


def test_assign_evidence_source_ids_is_stable_and_auditable() -> None:
    output = _output_with_evidence()

    first_ids = assign_evidence_source_ids(output.evidence, agent_name=output.agent_name)
    second_ids = assign_evidence_source_ids(output.evidence, agent_name=output.agent_name)

    assert first_ids == second_ids
    assert len(first_ids) == 2
    assert all(source_id.startswith("agent_source:") for source_id in first_ids)
    assert output.evidence[0].meta["source_id"] == first_ids[0]
    assert output.evidence[0].meta["audit_fields"] == ["source", "url", "timestamp", "confidence"]


def test_assign_evidence_source_ids_do_not_depend_on_evidence_order() -> None:
    original = _output_with_evidence().evidence
    reordered = list(reversed(_output_with_evidence().evidence))

    original_ids = {
        item.meta["metric_key"]: source_id
        for item, source_id in zip(original, assign_evidence_source_ids(original, agent_name="fundamental"))
    }
    reordered_ids = {
        item.meta["metric_key"]: source_id
        for item, source_id in zip(reordered, assign_evidence_source_ids(reordered, agent_name="fundamental"))
    }

    assert reordered_ids == original_ids


def test_evaluate_agent_quality_scores_supported_claims() -> None:
    output = _output_with_evidence()
    source_ids = assign_evidence_source_ids(output.evidence, agent_name=output.agent_name)
    output.claims = [
        build_agent_claim(
            agent_name=output.agent_name,
            ticker="AAPL",
            query="AAPL 估值、风险、未来三个月看什么？",
            claim="AAPL revenue growth remains positive and EPS revisions are supportive.",
            evidence_ids=source_ids,
            stance="bull",
            confidence=0.84,
            limitations=["fixture data only"],
        )
    ]

    quality = evaluate_agent_quality(output, query="AAPL quality", ticker="AAPL")

    assert quality["schema_version"] == "2026-05-18.agent-quality.v1"
    assert quality["status"] == "pass"
    assert quality["metrics"]["claim_count"] == 1
    assert quality["metrics"]["supported_claim_count"] == 1
    assert quality["metrics"]["claim_source_ratio"] == 1.0
    assert quality["metrics"]["evidence_freshness_rate"] == 1.0
    assert quality["metrics"]["limitation_count"] == 1
    assert quality["reason_codes"] == []


def test_apply_agent_quality_contract_merges_existing_quality_and_flags_unsupported_claim() -> None:
    output = _output_with_evidence()
    output.claims = [
        build_agent_claim(
            agent_name=output.agent_name,
            ticker="AAPL",
            query="AAPL risk",
            claim="AAPL has unsupported downside risk.",
            evidence_ids=["missing-source"],
            stance="risk",
            confidence=0.6,
        )
    ]

    result = apply_agent_quality_contract(output, query="AAPL risk", ticker="AAPL")

    assert result is output
    assert result.evidence_quality["existing_metric"] == 1
    assert result.evidence_quality["agent_quality"]["status"] == "warn"
    assert result.evidence_quality["agent_quality"]["metrics"]["claim_source_ratio"] == 0.0
    assert "unsupported_claim" in result.evidence_quality["agent_quality"]["reason_codes"]


@pytest.mark.asyncio
async def test_base_agent_research_attaches_quality_contract() -> None:
    class _ContractAgent(BaseFinancialAgent):
        AGENT_NAME = "contract_agent"

        async def _initial_search(self, query: str, ticker: str) -> dict[str, str]:
            return {"query": query, "ticker": ticker}

        async def _first_summary(self, data: object) -> str:
            return "AAPL has a source-backed catalyst."

        def _format_output(self, summary: str, raw_data: object) -> AgentOutput:
            del raw_data
            return AgentOutput(
                agent_name=self.AGENT_NAME,
                summary=summary,
                evidence=[
                    EvidenceItem(
                        text="Source-backed catalyst",
                        source="fixture",
                        timestamp="2026-05-18T00:00:00Z",
                        meta={"source_id": "agent_source:fixture-1"},
                    )
                ],
                claims=[
                    build_agent_claim(
                        agent_name=self.AGENT_NAME,
                        ticker="AAPL",
                        query="AAPL catalyst",
                        claim="AAPL has a source-backed catalyst.",
                        evidence_ids=["agent_source:fixture-1"],
                        stance="bull",
                        confidence=0.7,
                    )
                ],
                confidence=0.7,
                data_sources=["fixture"],
                as_of="2026-05-18T00:00:00Z",
            )

    result = await _ContractAgent(llm=None, cache=None).research("AAPL catalyst", "AAPL")

    quality = result.evidence_quality["agent_quality"]
    assert quality["status"] == "pass"
    assert quality["metrics"]["claim_count"] == 1
    assert quality["metrics"]["claim_source_ratio"] == 1.0

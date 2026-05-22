# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import time

import pytest

from backend.agents.base_agent import AgentOutput, BaseFinancialAgent, EvidenceItem
from backend.research.agent_quality_contract import apply_agent_quality_contract, build_agent_claim
from backend.research.agent_research_loop import (
    apply_agent_self_check,
    build_quality_gap_plan,
)


def test_build_quality_gap_plan_flags_missing_claims_and_low_freshness() -> None:
    output = AgentOutput(
        agent_name="news",
        summary="Recent news exists but has not been converted into claims.",
        evidence=[
            EvidenceItem(
                text="Apple shares move after analyst target update",
                source="Yahoo Finance",
                url="https://finance.yahoo.com/news/apple-analyst-target",
                confidence=0.7,
            )
        ],
        confidence=0.7,
        data_sources=["Yahoo Finance"],
        as_of="2026-05-18T00:00:00Z",
    )
    apply_agent_quality_contract(output, query="AAPL news", ticker="AAPL")

    plan = build_quality_gap_plan(output, query="AAPL news", ticker="AAPL")

    gap_codes = {gap["code"] for gap in plan["gaps"]}
    assert {"extract_claims", "refresh_sources"}.issubset(gap_codes)
    assert plan["status"] == "warn"
    assert any(action["tool_hint"] == "claim_extractor" for action in plan["next_actions"])


def test_apply_agent_self_check_attaches_diagnostics_without_overwriting_quality() -> None:
    output = AgentOutput(
        agent_name="fundamental",
        summary="AAPL revenue growth is positive.",
        evidence=[
            EvidenceItem(
                text="Revenue: $92.0B, +4.5% YoY",
                source="yfinance",
                timestamp="2026-03-31",
                confidence=0.9,
                meta={"source_id": "agent_source:revenue"},
            )
        ],
        claims=[
            build_agent_claim(
                agent_name="fundamental",
                ticker="AAPL",
                query="AAPL fundamental",
                claim="AAPL revenue growth is positive.",
                evidence_ids=["agent_source:revenue"],
                stance="bull",
                confidence=0.8,
            )
        ],
        confidence=0.8,
        data_sources=["yfinance"],
        as_of="2026-05-18T00:00:00Z",
        evidence_quality={"existing": "kept"},
    )
    apply_agent_quality_contract(output, query="AAPL fundamental", ticker="AAPL")

    result = apply_agent_self_check(output, query="AAPL fundamental", ticker="AAPL")

    assert result is output
    assert output.evidence_quality["existing"] == "kept"
    assert output.evidence_quality["agent_quality"]["status"] == "pass"
    assert output.evidence_quality["agent_self_check"]["status"] == "pass"
    assert output.evidence_quality["agent_self_check"]["gaps"] == []


@pytest.mark.asyncio
async def test_base_agent_research_attaches_self_check_diagnostics() -> None:
    class _NoClaimAgent(BaseFinancialAgent):
        AGENT_NAME = "no_claim_agent"

        async def _initial_search(self, query: str, ticker: str) -> dict[str, str]:
            return {"query": query, "ticker": ticker}

        async def _first_summary(self, data: object) -> str:
            return "AAPL has evidence but no native claims."

        def _format_output(self, summary: str, raw_data: object) -> AgentOutput:
            del raw_data
            return AgentOutput(
                agent_name=self.AGENT_NAME,
                summary=summary,
                evidence=[
                    EvidenceItem(
                        text="Evidence without native claim",
                        source="fixture",
                        timestamp="2026-05-18T00:00:00Z",
                    )
                ],
                confidence=0.6,
                data_sources=["fixture"],
                as_of="2026-05-18T00:00:00Z",
            )

    output = await _NoClaimAgent(llm=None, cache=None).research("AAPL check", "AAPL")

    assert output.evidence_quality["agent_quality"]["status"] == "warn"
    assert output.evidence_quality["agent_self_check"]["status"] == "warn"
    assert output.evidence_quality["agent_self_check"]["gaps"][0]["code"] == "extract_claims"


@pytest.mark.asyncio
async def test_agent_llm_analysis_is_opt_in_by_default(monkeypatch) -> None:
    class _UnexpectedLLM:
        model_name = "unexpected-fixture"

        async def ainvoke(self, _messages):
            raise AssertionError("agent LLM analysis should be disabled by default")

    class _OptInAgent(BaseFinancialAgent):
        AGENT_NAME = "optin_agent"

    monkeypatch.delenv("AGENT_LLM_ANALYZE_ENABLED", raising=False)
    monkeypatch.delenv("OPTIN_AGENT_LLM_ANALYZE_ENABLED", raising=False)

    agent = _OptInAgent(llm=_UnexpectedLLM(), cache=None)

    assert await agent._llm_analyze("price 10", role="fixture", focus="fixture") is None


@pytest.mark.asyncio
async def test_agent_llm_analysis_has_hard_call_timeout(monkeypatch) -> None:
    class _SlowLLM:
        model_name = "slow-fixture"

        async def ainvoke(self, _messages):
            await asyncio.sleep(2.0)
            return type("_Resp", (), {"content": "这段内容不应该在超时后返回。"})()

    class _TimeoutAgent(BaseFinancialAgent):
        AGENT_NAME = "timeout_agent"

    monkeypatch.setenv("AGENT_LLM_ANALYZE_ENABLED", "true")
    monkeypatch.setenv("TIMEOUT_AGENT_LLM_ANALYZE_TIMEOUT_SECONDS", "0.1")
    monkeypatch.setenv("TIMEOUT_AGENT_LLM_ANALYZE_CALL_TIMEOUT_SECONDS", "0.1")
    monkeypatch.setattr(
        "backend.services.rate_limiter.acquire_llm_token",
        lambda *args, **kwargs: asyncio.sleep(0, result=True),
    )

    agent = _TimeoutAgent(llm=_SlowLLM(), cache=None)

    start = time.perf_counter()
    result = await agent._llm_analyze(
        "price 10, MA20 9, RSI 55",
        role="fixture",
        focus="fixture",
    )
    elapsed = time.perf_counter() - start

    assert result is None
    assert elapsed < 0.8


@pytest.mark.asyncio
async def test_agent_reflection_gap_detection_has_hard_call_timeout(monkeypatch) -> None:
    class _SlowLLM:
        model_name = "slow-fixture"

        async def ainvoke(self, _messages):
            await asyncio.sleep(2.0)
            return type("_Resp", (), {"content": "{\"complete\": true}"})()

    class _TimeoutAgent(BaseFinancialAgent):
        AGENT_NAME = "timeout_agent"

    monkeypatch.setenv("TIMEOUT_AGENT_LLM_ANALYZE_CALL_TIMEOUT_SECONDS", "0.1")
    monkeypatch.setattr(
        "backend.services.rate_limiter.acquire_llm_token",
        lambda *args, **kwargs: asyncio.sleep(0, result=True),
    )

    agent = _TimeoutAgent(llm=_SlowLLM(), cache=None)
    agent._current_query = "AAPL technical"
    agent._current_ticker = "AAPL"

    start = time.perf_counter()
    result = await agent._identify_gaps("AAPL has price and RSI evidence.")
    elapsed = time.perf_counter() - start

    assert result == []
    assert elapsed < 0.8

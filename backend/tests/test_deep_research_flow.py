# -*- coding: utf-8 -*-
import pytest
from unittest.mock import AsyncMock, MagicMock

from backend.agents.deep_search_agent import DeepSearchAgent
from backend.research.deep_research_flow import run_deep_research_flow


@pytest.mark.asyncio
async def test_deep_research_flow_emits_fixed_stage_records():
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())
    base_docs = [
        {
            "title": "AAPL filing",
            "url": "https://www.sec.gov/aapl",
            "snippet": "Revenue growth remained resilient.",
            "content": "Revenue growth remained resilient.",
            "source": "sec",
            "published_date": "2026-02-01T00:00:00Z",
            "is_pdf": False,
            "confidence": 0.9,
        }
    ]
    followup_docs = [
        {
            "title": "AAPL risk note",
            "url": "https://www.reuters.com/markets/aapl-risk",
            "snippet": "Margin risk remains visible.",
            "content": "Margin risk remains visible.",
            "source": "Reuters",
            "published_date": "2026-02-02T00:00:00Z",
            "is_pdf": False,
            "confidence": 0.8,
        }
    ]

    agent._initial_search = AsyncMock(return_value=base_docs)
    agent._first_summary = AsyncMock(return_value="AAPL has resilient revenue growth.")
    agent._identify_gaps = AsyncMock(side_effect=[["margin risk"], []])
    agent._targeted_search = AsyncMock(return_value=followup_docs)
    agent._update_summary = AsyncMock(return_value="AAPL has resilient revenue growth but margin risk remains visible.")
    agent._record_rag_observability = AsyncMock(return_value={"enabled": True, "collection": "ws:deepsearch:aapl:test"})

    result = await run_deep_research_flow(agent, "AAPL deep research", "AAPL")

    assert [stage.stage for stage in result.stages] == [
        "plan_search",
        "fetch_sources",
        "extract_claims",
        "gap_check",
        "targeted_followup",
        "ledger_write",
    ]
    for stage in result.stage_records:
        assert stage["query"] == "AAPL deep research"
        assert "source_count" in stage
        assert "claim_count" in stage
    assert result.stage_records[-1]["source_count"] == 2
    assert result.stage_records[-1]["claim_count"] >= 1
    assert result.output.ledger


def test_deepsearch_collection_uses_working_set_names():
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())

    collection = agent._build_rag_collection(query="AAPL deep research", ticker="AAPL")
    assert collection.startswith("ws:deepsearch:aapl:")
    assert not collection.startswith("session:deepsearch:")

    agent.thread_id = "tenant:user:thread-1"
    assert agent._build_rag_collection(query="AAPL deep research", ticker="AAPL") == "ws:thread:tenant:user:thread-1"


def test_deepsearch_finance_queries_keep_user_specific_report_targets():
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())

    queries = agent._build_queries(
        "请做 INTC 深度投资报告，覆盖最新财报、Arrow Lake、NVIDIA/AMD/TSMC 竞争、分析师评级和目标价",
        "INTC",
    )

    joined = " ".join(queries)
    assert any("sec.gov" in query and "10-K" in query and "10-Q" in query for query in queries)
    assert "Arrow Lake" in joined
    assert "analyst" in joined.lower() or "rating" in joined.lower()
    assert "AMD" in joined and "NVDA" in joined and "TSM" in joined
    assert len(queries) <= 4


@pytest.mark.asyncio
async def test_deepsearch_gap_queries_are_budget_limited(monkeypatch):
    agent = DeepSearchAgent(MagicMock(), MagicMock(), MagicMock())
    monkeypatch.setattr(agent, "MAX_GAP_QUERIES", 1)

    async def fake_call_llm(_prompt):
        return '{"needs_more": true, "queries": ["margin risk", "analyst rating", "Arrow Lake roadmap"]}'

    agent._call_llm = fake_call_llm

    assert await agent._identify_gaps("summary") == ["margin risk"]


@pytest.mark.asyncio
async def test_deepsearch_targeted_search_sanitizes_long_gap_query():
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())
    captured: list[str] = []

    def fake_search(query: str):
        captured.append(query)
        return []

    agent._search_web = MagicMock(side_effect=fake_search)

    await agent._targeted_search(
        [
            "深入研究英特尔与主要竞争对手NVIDIA（GPU/AI）、AMD（CPU）、TSMC（代工/制程）的最新竞争态势、"
            "技术差距变化、市场份额争夺情况。分析英特尔在AI、制程、客户端、服务器各细分领域的相对位置。"
        ],
        "INTC",
    )

    assert captured == ["INTC NVDA AMD TSM competitive landscape"]


@pytest.mark.asyncio
async def test_deep_research_flow_rejects_unsafe_urls_before_fetch():
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())
    unsafe = "http://127.0.0.1/admin"
    safe = "https://www.sec.gov/aapl"
    captured = {}

    agent._search_web = MagicMock(
        return_value=[
            {"title": "Unsafe", "url": unsafe, "snippet": "internal", "source": "search"},
            {"title": "Safe", "url": safe, "snippet": "filing", "source": "search"},
        ]
    )

    def fake_fetch(results):
        captured["urls"] = [item.get("url") for item in results]
        return [
            {
                "title": "Safe",
                "url": safe,
                "snippet": "filing",
                "content": "filing content",
                "source": "search",
                "is_pdf": False,
            }
        ]

    agent._fetch_documents = MagicMock(side_effect=fake_fetch)
    agent._first_summary = AsyncMock(return_value="Safe filing content.")
    agent._identify_gaps = AsyncMock(return_value=[])
    agent._record_rag_observability = AsyncMock(return_value={})

    await run_deep_research_flow(agent, "AAPL filing", "AAPL")

    assert captured["urls"] == [safe]
    assert unsafe not in captured["urls"]


def test_deepsearch_format_output_attaches_claims_and_ledger():
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())
    output = agent._format_output(
        "Bullish growth claim with risk caveat.",
        [
            {
                "title": "AAPL report",
                "url": "https://www.reuters.com/markets/aapl-report",
                "snippet": "Bullish growth claim with risk caveat.",
                "content": "Bullish growth claim with risk caveat.",
                "source": "Reuters",
                "published_date": "2026-02-01T00:00:00Z",
                "is_pdf": False,
                "confidence": 0.8,
            }
        ],
        query="AAPL outlook",
        ticker="AAPL",
    )

    assert output.claims
    assert output.ledger
    assert output.ledger["query"] == "AAPL outlook"
    assert output.ledger["subject"]["ticker"] == "AAPL"
    assert output.ledger["claims"][0]["evidence_ids"]

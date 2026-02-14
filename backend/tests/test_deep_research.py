import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from typing import Any
import backend.agents.deep_search_agent as deep_search_module
from backend.agents.deep_search_agent import DeepSearchAgent
from backend.agents.macro_agent import MacroAgent
from backend.orchestration.supervisor_agent import SupervisorAgent
from backend.orchestration.intent_classifier import ClassificationResult, AgentIntent
from backend.agents.base_agent import AgentOutput

@pytest.mark.asyncio
async def test_deep_search_agent():
    mock_cache = MagicMock()
    mock_cache.get.return_value = None
    mock_tools = MagicMock()

    agent = DeepSearchAgent(None, mock_cache, mock_tools)
    agent._search_web = MagicMock(return_value=[{
        "title": "Sample Report",
        "url": "https://example.com/report",
        "snippet": "Sample snippet",
        "source": "search",
    }])
    agent._fetch_documents = MagicMock(return_value=[{
        "title": "Sample Report",
        "url": "https://example.com/report",
        "snippet": "Sample snippet",
        "content": "Sample content for deep search report.",
        "source": "search",
        "is_pdf": False,
    }])

    # Test research flow
    result = await agent.research("NVDA investment thesis", "NVDA")

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "deep_search"
    assert "search" in result.data_sources
    assert len(result.evidence) == 1

@pytest.mark.asyncio
async def test_deep_search_agent_self_rag_merges_docs():
    mock_cache = MagicMock()
    mock_tools = MagicMock()
    agent = DeepSearchAgent(None, mock_cache, mock_tools)

    base_docs = [{
        "title": "Base Doc",
        "url": "https://example.com/base",
        "snippet": "Base snippet",
        "content": "Base content.",
        "source": "tavily",
        "is_pdf": False,
    }]
    extra_docs = [{
        "title": "Gap Doc",
        "url": "https://example.com/gap",
        "snippet": "Gap snippet",
        "content": "Gap content.",
        "source": "search",
        "is_pdf": True,
    }]

    agent._initial_search = AsyncMock(return_value=base_docs)
    agent._identify_gaps = AsyncMock(side_effect=[["competitors"], []])
    agent._targeted_search = AsyncMock(return_value=extra_docs)
    agent._first_summary = AsyncMock(return_value="Initial summary")
    agent._update_summary = AsyncMock(return_value="Updated summary")

    result = await agent.research("NVDA investment thesis", "NVDA")

    assert isinstance(result, AgentOutput)
    assert result.summary == "Updated summary"
    assert len(result.evidence) == 2
    assert "tavily" in result.data_sources
    assert "search" in result.data_sources


@pytest.mark.asyncio
async def test_deep_search_agent_outputs_evidence_quality_and_conflict_flags():
    mock_cache = MagicMock()
    mock_tools = MagicMock()
    agent = DeepSearchAgent(None, mock_cache, mock_tools)

    docs = [
        {
            "title": "Analyst upgrade with strong growth outlook",
            "url": "https://www.reuters.com/markets/aapl-upgrade",
            "snippet": "Analysts see upside and raised targets.",
            "content": "Strong demand and growth momentum support a bullish outlook.",
            "source": "tavily",
            "published_date": "2026-02-06T10:00:00Z",
            "is_pdf": False,
            "confidence": 0.8,
        },
        {
            "title": "Downside risk rises after miss",
            "url": "https://example.com/risk-note",
            "snippet": "Company may miss guidance and face downside pressure.",
            "content": "Weak demand and elevated risk could pressure margins.",
            "source": "search",
            "published_date": "2025-12-15T00:00:00Z",
            "is_pdf": False,
            "confidence": 0.7,
        },
    ]

    agent._initial_search = AsyncMock(return_value=docs)
    agent._first_summary = AsyncMock(return_value="Initial summary")
    agent._identify_gaps = AsyncMock(return_value=[])

    result = await agent.research("AAPL deep analysis", "AAPL")

    assert isinstance(result, AgentOutput)
    assert len(result.evidence) == 2
    assert any("冲突" in r or "分歧" in r for r in result.risks)

    for item in result.evidence:
        assert isinstance(item.meta, dict)
        assert "doc_quality" in item.meta
        assert "evidence_quality" in item.meta
        assert "conflict_flag" in item.meta

    quality_events = [e for e in result.trace if isinstance(e, dict) and e.get("event_type") == "evidence_quality"]
    assert quality_events, "deep_search should emit evidence_quality trace event"
    payload = quality_events[-1].get("metadata") or {}
    assert payload.get("has_conflicts") is True
    assert float(payload.get("overall_score", 0.0)) >= 0.0

@pytest.mark.asyncio
async def test_macro_agent():
    mock_llm = MagicMock()
    mock_cache = MagicMock()
    mock_tools = MagicMock()
    mock_tools.get_fred_data.return_value = {"fed_rate": 5.0, "cpi": 3.2, "unemployment": 4.1}
    mock_tools.get_market_sentiment.return_value = "CNN Fear & Greed Index: 60 (Greed)"
    mock_tools.get_economic_events.return_value = "FOMC this week"
    mock_tools.search.return_value = "Federal funds rate 4.9%, CPI 3.1%, unemployment rate 4.2%"

    agent = MacroAgent(mock_llm, mock_cache, mock_tools)

    # Test research flow with macro keyword
    result = await agent.research("inflation analysis", "N/A")

    assert isinstance(result, AgentOutput)
    assert result.agent_name == "macro"
    assert result.evidence
    assert any(item.source == "FRED" for item in result.evidence)
    assert result.evidence_quality.get("overall_score", 0) > 0
    assert result.evidence_quality.get("source_diversity", 0) >= 1
    assert "FRED" in result.data_sources

@pytest.mark.asyncio
async def test_macro_agent_fallback_structured():
    mock_llm = MagicMock()
    mock_cache = MagicMock()
    mock_tools = MagicMock()
    mock_tools.get_fred_data.side_effect = Exception("FRED down")
    mock_tools.search.return_value = "latest CPI 3.0% and unemployment rate 4.0%"
    mock_tools.get_market_sentiment.return_value = ""
    mock_tools.get_economic_events.return_value = ""

    agent = MacroAgent(mock_llm, mock_cache, mock_tools)
    result = await agent.research("inflation analysis", "N/A")

    assert "备用" in result.summary or "不可用" in result.summary
    assert "Web Search" in result.data_sources
    assert result.evidence is not None
    assert len(result.evidence) > 0
    assert result.fallback_used is True


@pytest.mark.asyncio
async def test_macro_agent_conflict_merge_prefers_fred():
    mock_llm = MagicMock()
    mock_cache = MagicMock()
    mock_tools = MagicMock()
    mock_tools.get_fred_data.return_value = {"fed_rate": 5.5, "cpi": 3.0, "unemployment": 3.9}
    mock_tools.get_market_sentiment.return_value = ""
    mock_tools.get_economic_events.return_value = ""
    mock_tools.search.return_value = "Federal funds rate 4.4%, CPI 2.1%, unemployment rate 4.8%"

    agent = MacroAgent(mock_llm, mock_cache, mock_tools)
    result = await agent.research("macro update", "N/A")

    assert result.agent_name == "macro"
    assert result.evidence_quality.get("has_conflicts") is True
    assert any("冲突" in risk for risk in result.risks)

@pytest.mark.asyncio
async def test_supervisor_integration_phase2():
    mock_llm = MagicMock()
    mock_tools = MagicMock()
    mock_cache = MagicMock()

    supervisor = SupervisorAgent(mock_llm, mock_tools, mock_cache)

    # Check if new agents are registered
    assert "deep_search" in supervisor.agents
    assert "macro" in supervisor.agents
    assert "technical" in supervisor.agents
    assert "fundamental" in supervisor.agents

    # Mock all agents research method to avoid actual calls
    for name, agent in supervisor.agents.items():
        agent.research = AsyncMock(return_value=AgentOutput(
            agent_name=name,
            summary=f"{name} summary",
            evidence=[],
            confidence=0.8,
            data_sources=["test"],
            as_of="2023-01-01"
        ))

    # Mock Forum synthesize
    supervisor.forum.synthesize = AsyncMock(return_value=MagicMock())

    classification = ClassificationResult(
        intent=AgentIntent.REPORT,
        confidence=1.0,
        tickers=["NVDA"],
        method="test",
        reasoning="forced",
        scores={},
    )

    # Run report handler directly (avoids agent reset in process)
    await supervisor._handle_report("Deep analysis of NVDA", "NVDA", None, classification)

    # Verify agents were called
    supervisor.agents["deep_search"].research.assert_called()
    supervisor.agents["macro"].research.assert_called()
    supervisor.agents["technical"].research.assert_called()
    supervisor.agents["fundamental"].research.assert_called()


def test_deep_search_queries_dynamic():
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())
    queries = agent._build_queries("valuation risk", "AAPL")
    assert any("risk factors" in q for q in queries)
    assert any("valuation model" in q for q in queries)


def test_deep_search_filter_results_finance_mode_blocks_untrusted_domains(monkeypatch):
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())
    monkeypatch.setenv("DEEPSEARCH_STRICT_FINANCE_SOURCES", "true")
    results = [
        {
            "title": "Apple 10-K",
            "url": "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm",
            "snippet": "SEC filing",
            "source": "tavily",
        },
        {
            "title": "Random tagged site",
            "url": "https://wikiwiki.mtevfryb.cc/tag/finance",
            "snippet": "noise",
            "source": "search",
        },
        {
            "title": "Finnhub API redirect",
            "url": "https://finnhub.io/api/news?id=abc123",
            "snippet": "noise",
            "source": "search",
        },
        {
            "title": "Reuters earnings",
            "url": "https://www.reuters.com/technology/apple-earnings-call-2026-02-10/",
            "snippet": "earnings call transcript",
            "source": "tavily",
        },
    ]

    filtered = agent._filter_results(
        results,
        query="AAPL deep report 10-K 10-Q earnings call transcript",
        ticker="AAPL",
    )
    urls = [item.get("url") for item in filtered]
    assert "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm" in urls
    assert "https://www.reuters.com/technology/apple-earnings-call-2026-02-10/" in urls
    assert "https://wikiwiki.mtevfryb.cc/tag/finance" not in urls
    assert "https://finnhub.io/api/news?id=abc123" not in urls


@pytest.mark.asyncio
async def test_deep_search_targeted_search_applies_domain_filter(monkeypatch):
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())
    monkeypatch.setenv("DEEPSEARCH_STRICT_FINANCE_SOURCES", "true")

    trusted_url = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/aapl-20240928.htm"
    untrusted_url = "https://random-finance.cc/aapl-deep-dive"
    agent._search_web = MagicMock(return_value=[
        {"title": "SEC filing", "url": trusted_url, "snippet": "10-K", "source": "search"},
        {"title": "Untrusted blog", "url": untrusted_url, "snippet": "noise", "source": "search"},
    ])

    captured: dict[str, Any] = {}

    def _fake_fetch(results):
        captured["results"] = results
        return results

    agent._fetch_documents = MagicMock(side_effect=_fake_fetch)

    docs = await agent._targeted_search(["10-K filing"], "AAPL")
    urls = [item.get("url") for item in captured.get("results", [])]

    assert trusted_url in urls
    assert untrusted_url not in urls
    assert all(item.get("url") != untrusted_url for item in docs)


def test_fetch_documents_pdf_without_reader_uses_snippet_fallback(monkeypatch):
    mock_cache = MagicMock()
    mock_tools = MagicMock()
    agent = DeepSearchAgent(None, mock_cache, mock_tools)

    class _MockPdfResponse:
        def __init__(self, url: str):
            self.url = url
            self.headers = {"Content-Type": "application/pdf"}
            self.content = b"%PDF-1.4 mock"
            self.text = ""

        def raise_for_status(self):
            return None

    class _MockSession:
        def __init__(self, response):
            self._response = response

        def get(self, *_args, **_kwargs):
            return self._response

    url = "https://example.com/alpha-report.pdf"
    result_item = {
        "title": "Alpha Research",
        "url": url,
        "snippet": "This report highlights margin expansion and cash flow resilience.",
        "source": "search",
    }

    monkeypatch.setattr(deep_search_module, "PdfReader", None)
    monkeypatch.setattr(agent, "_get_session", lambda: _MockSession(_MockPdfResponse(url)))

    docs = agent._fetch_documents([result_item])

    assert docs
    assert docs[0]["is_pdf"] is True
    assert docs[0]["content"]
    assert "margin expansion" in docs[0]["content"].lower()


def test_fetch_documents_all_short_content_falls_back_to_snippets():
    mock_cache = MagicMock()
    mock_tools = MagicMock()
    agent = DeepSearchAgent(None, mock_cache, mock_tools)

    results = [
        {
            "title": "Doc 1",
            "url": "https://example.com/doc1",
            "snippet": "Snippet one with useful but short context.",
            "source": "search",
        },
        {
            "title": "Doc 2",
            "url": "https://example.com/doc2",
            "snippet": "Snippet two with another useful clue.",
            "source": "search",
        },
    ]

    short_doc = {
        "title": "Short",
        "url": "https://example.com/short",
        "snippet": "short snippet",
        "content": "tiny",
        "source": "search",
        "is_pdf": True,
        "confidence": 0.8,
    }
    agent._fetch_document = MagicMock(return_value=short_doc)

    docs = agent._fetch_documents(results)

    assert docs
    assert len(docs) == 2
    assert all(doc.get("content") for doc in docs)
    assert all(doc.get("confidence", 1.0) <= 0.5 for doc in docs)


def test_build_degraded_summary_is_structured_and_filters_noise():
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())

    docs = [
        {
            "title": "AAPL Q4 Earnings Preview",
            "url": "https://example.com/aapl-earnings",
            "snippet": "Revenue expected to grow 8% YoY with gross margin expansion.",
            "content": "SummaryRatingsFinancialsTechnicalsMarketWatch Revenue expected to grow 8% YoY with gross margin expansion.",
            "source": "search",
            "is_pdf": True,
            "degraded": True,
        },
        {
            "title": "Supply Chain Check",
            "url": "https://example.com/supply-chain",
            "snippet": "Channel inventory normalized and lead times improved.",
            "content": "Channel inventory normalized and lead times improved.",
            "source": "search",
            "is_pdf": False,
            "degraded": True,
        },
    ]

    summary = agent._build_degraded_summary(docs)

    assert "## 核心发现" in summary
    assert "## 风险提示" in summary
    assert "## 信息缺口" in summary
    assert "SummaryRatingsFinancialsTechnicalsMarketWatch" not in summary
    assert "Revenue expected to grow" in summary


def test_source_reliability_score_penalizes_degraded_pdf():
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())

    degraded_pdf_score = agent._source_reliability_score({
        "url": "https://example.com/report.pdf",
        "source": "search",
        "is_pdf": True,
        "degraded": True,
    })
    normal_pdf_score = agent._source_reliability_score({
        "url": "https://www.sec.gov/ixviewer/report.pdf",
        "source": "sec.gov",
        "is_pdf": True,
        "degraded": False,
        "content": "x" * 1200,
    })

    assert degraded_pdf_score <= 0.6
    assert normal_pdf_score >= 0.85


def test_estimate_confidence_caps_all_degraded_docs():
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())

    docs = [
        {
            "title": "Doc 1",
            "source": "search",
            "is_pdf": True,
            "degraded": True,
            "confidence": 0.45,
        },
        {
            "title": "Doc 2",
            "source": "search",
            "is_pdf": False,
            "degraded": True,
            "confidence": 0.4,
        },
    ]

    confidence = agent._estimate_confidence(docs)
    assert confidence <= 0.55


def test_build_queries_default_does_not_force_pdf_bias(monkeypatch):
    monkeypatch.setenv("DEEPSEARCH_ENABLE_PDF_QUERY_BIAS", "0")
    agent = DeepSearchAgent(None, MagicMock(), MagicMock())

    queries = agent._build_queries("", "AAPL")

    assert queries
    assert all("filetype:pdf" not in q.lower() for q in queries)

if __name__ == "__main__":
    asyncio.run(test_deep_search_agent())
    asyncio.run(test_macro_agent())
    asyncio.run(test_supervisor_integration_phase2())

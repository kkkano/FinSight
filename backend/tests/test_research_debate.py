# -*- coding: utf-8 -*-

import asyncio


def _run(coro):
    return asyncio.run(coro)


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
                "claim_id": "c-bull-2",
                "claim": "Gross margin resilience supports the upside thesis.",
                "stance": "bull",
                "evidence_ids": ["s-2"],
                "confidence": 0.74,
                "agent_name": "price_agent",
            },
            {
                "claim_id": "c-bear-1",
                "claim": "Valuation is vulnerable if AI capex expectations reset.",
                "stance": "bear",
                "evidence_ids": ["s-3"],
                "confidence": 0.7,
                "agent_name": "risk_agent",
            },
            {
                "claim_id": "c-risk-1",
                "claim": "Export controls remain a material downside risk.",
                "stance": "risk",
                "evidence_ids": ["s-4"],
                "confidence": 0.66,
                "agent_name": "macro_agent",
            },
            {
                "claim_id": "c-neutral-1",
                "claim": "Near-term price action is mixed.",
                "stance": "neutral",
                "evidence_ids": ["s-5"],
                "confidence": 0.55,
                "agent_name": "technical_agent",
            },
        ],
        "sources": [
            {"source_id": "s-1", "title": "Demand note", "source": "filing", "reliability": 0.8},
            {"source_id": "s-2", "title": "Margin note", "source": "market_data", "reliability": 0.7},
            {"source_id": "s-3", "title": "Valuation note", "source": "risk", "reliability": 0.65},
            {"source_id": "s-4", "title": "Policy note", "source": "macro", "reliability": 0.75},
            {"source_id": "s-5", "title": "Technical note", "source": "technical", "reliability": 0.6},
        ],
        "uncertainties": ["AI capex durability is uncertain."],
        "contradictions": [{"claim_id": "c-neutral-1", "reason": "Momentum and valuation signals diverge."}],
    }


def test_build_debate_artifact_splits_bull_bear_and_judges():
    from backend.research.debate import build_debate_artifact

    artifact = build_debate_artifact(_ledger(), query="NVDA investment debate")

    assert artifact["status"] == "done"
    assert [claim["claim_id"] for claim in artifact["bull_thesis"]["claims"]] == ["c-bull-1", "c-bull-2"]
    assert [claim["claim_id"] for claim in artifact["bear_thesis"]["claims"]] == ["c-bear-1", "c-risk-1"]
    assert artifact["cross_examination"], "bull/bear claims should be cross-examined"
    scorecard = artifact["judge_scorecard"]
    assert 0.0 <= scorecard["bull_score"] <= 1.0
    assert 0.0 <= scorecard["bear_score"] <= 1.0
    assert scorecard["evidence_balance"] in {"bull", "bear", "mixed", "insufficient"}
    assert scorecard["key_disagreements"]
    assert artifact["consensus"]
    assert artifact["open_questions"]


def test_build_debate_artifact_outputs_read_only_adjudications():
    from backend.research.debate import build_debate_artifact

    artifact = build_debate_artifact(_ledger(), query="NVDA investment debate")

    adjudications = artifact.get("adjudications") or []
    assert adjudications
    first = adjudications[0]
    assert first["topic"]
    assert first["supporting_agents"]
    assert first["opposing_agents"]
    assert first["adjudication"] in {"bull", "bear", "mixed", "insufficient"}
    assert first["rationale"]


def test_research_debate_node_respects_flag_and_missing_ledger(monkeypatch):
    from backend.graph.nodes.research_debate import research_debate

    monkeypatch.setenv("DEBATE_GRAPH_ENABLED", "false")
    assert _run(research_debate({"artifacts": {"evidence_ledger": _ledger()}, "trace": {}})) == {}

    monkeypatch.setenv("DEBATE_GRAPH_ENABLED", "true")
    out = _run(research_debate({"query": "NVDA", "artifacts": {}, "trace": {}}))
    debate = (out.get("artifacts") or {}).get("debate") or {}
    assert debate == {
        "enabled": True,
        "status": "skipped",
        "reason": "missing_evidence_ledger",
    }


def test_research_debate_node_attaches_artifact_when_enabled(monkeypatch):
    from backend.graph.nodes.research_debate import research_debate

    monkeypatch.setenv("DEBATE_GRAPH_ENABLED", "true")
    state = {"query": "NVDA investment debate", "artifacts": {"evidence_ledger": _ledger()}, "trace": {}}

    out = _run(research_debate(state))

    artifacts = out.get("artifacts") or {}
    debate = artifacts.get("debate") or {}
    assert debate.get("status") == "done"
    assert debate.get("judge_scorecard", {}).get("evidence_balance") in {"bull", "bear", "mixed"}
    assert (out.get("trace") or {}).get("research_debate", {}).get("status") == "done"

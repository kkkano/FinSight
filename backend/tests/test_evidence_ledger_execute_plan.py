# -*- coding: utf-8 -*-
import asyncio
import importlib


def _run(coro):
    return asyncio.run(coro)


def test_execute_plan_stub_builds_evidence_ledger_from_execution_artifacts(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "false")
    monkeypatch.setenv("RESEARCH_LEDGER_ENABLED", "true")
    monkeypatch.setenv("JINA_ENRICH_EVIDENCE", "false")

    execute_mod = importlib.import_module("backend.graph.nodes.execute_plan_stub")

    async def _fake_execute_plan(*_args, **_kwargs):
        return (
            {
                "step_results": {
                    "price-step": {
                        "cached": False,
                        "status_reason": "done",
                        "task_ids": ["task-price"],
                        "output": {
                            "agent_name": "price_agent",
                            "summary": "Apple shares closed higher after stronger iPhone demand.",
                            "confidence": 0.84,
                            "as_of": "2026-05-17T00:00:00Z",
                            "claims": [
                                {
                                    "claim": "Apple shares rose on stronger iPhone demand.",
                                    "confidence": 0.82,
                                    "evidence_ids": [],
                                }
                            ],
                            "evidence": [
                                {
                                    "title": "Apple price update",
                                    "url": "https://example.com/aapl-price",
                                    "text": "AAPL closed at 190 after stronger iPhone demand.",
                                    "source": "market_data",
                                    "timestamp": "2026-05-17",
                                    "confidence": 0.9,
                                }
                            ],
                        },
                    }
                },
                "evidence_pool": [
                    {
                        "id": "pool-1",
                        "type": "price",
                        "title": "Apple price update",
                        "snippet": "AAPL closed at 190 after stronger iPhone demand.",
                        "source": "pool_feed",
                        "url": "https://example.com/aapl-price",
                        "published_date": "2026-05-17",
                        "confidence": 0.91,
                    }
                ],
                "rag_context": [
                    {
                        "title": "AAPL working set hit",
                        "url": "https://example.com/aapl-rag",
                        "source": "rag",
                        "content": "Working set chunk about AAPL price momentum.",
                        "layer": "ws",
                        "collection": "ws:thread:ledger-test",
                        "chunk_id": "chunk-123",
                        "source_id": "vec-123",
                        "metadata": {
                            "layer": "ws",
                            "collection": "ws:thread:ledger-test",
                            "chunk_id": "chunk-123",
                        },
                    }
                ],
            },
            [{"event": "fake"}],
        )

    monkeypatch.setattr(execute_mod, "execute_plan", _fake_execute_plan)
    monkeypatch.setattr("backend.rag.observability_store.get_rag_observability_store", lambda: None)
    from backend.rag.rag_router import RAGPriority

    monkeypatch.setattr("backend.rag.rag_router.decide_rag_priority", lambda **_kwargs: RAGPriority.SKIP)

    state = {
        "thread_id": "ledger-test",
        "query": "AAPL price move",
        "plan_ir": {
            "goal": "AAPL price move",
            "subject": {
                "subject_type": "company",
                "tickers": ["AAPL"],
                "selection_ids": ["pool-1"],
                "selection_types": ["price"],
                "selection_payload": [],
            },
            "output_mode": "investment_report",
            "steps": [
                {
                    "id": "price-step",
                    "kind": "agent",
                    "name": "price_agent",
                    "inputs": {"ticker": "AAPL"},
                    "task_ids": ["task-price"],
                }
            ],
            "tasks": [{"id": "task-price", "subject_type": "company", "tickers": ["AAPL"]}],
            "budget": {"max_rounds": 1, "max_tools": 1},
            "synthesis": {"style": "concise", "sections": []},
        },
        "policy": {"allowed_tools": [], "allowed_agents": [], "budget": {"max_rounds": 1, "max_tools": 1}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_payload": [],
        },
        "trace": {},
    }

    out = _run(execute_mod.execute_plan_stub(state))
    artifacts = out.get("artifacts") or {}
    ledger = artifacts.get("evidence_ledger") or {}

    assert ledger, "execute_plan_stub should attach evidence_ledger"
    assert any(
        item.get("source") == "pool_feed" and item.get("url") == "https://example.com/aapl-price"
        for item in (artifacts.get("evidence_pool") or [])
    ), "executor-provided evidence_pool should be preserved through dedupe"

    source_ids = [source.get("source_id") for source in ledger.get("sources", [])]
    assert len(source_ids) == len(set(source_ids)), "ledger source IDs should be deduped"

    price_sources = [
        source
        for source in ledger.get("sources", [])
        if source.get("url") == "https://example.com/aapl-price"
    ]
    assert len(price_sources) == 1, "agent evidence should not duplicate the matching pool URL"
    assert price_sources[0].get("source") == "pool_feed"

    rag_sources = [
        source
        for source in ledger.get("sources", [])
        if source.get("url") == "https://example.com/aapl-rag"
    ]
    assert rag_sources
    assert rag_sources[0].get("layer") == "ws"
    assert rag_sources[0].get("collection") == "ws:thread:ledger-test"

    claim = ledger.get("claims", [])[0]
    assert price_sources[0]["source_id"] in claim.get("evidence_ids", [])

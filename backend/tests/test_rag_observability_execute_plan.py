# -*- coding: utf-8 -*-
import asyncio


def _run(coro):
    return asyncio.run(coro)


class _FakeObservabilityStore:
    def __init__(self):
        self.run_records = []
        self.events = []
        self.source_docs = []
        self.chunks = []
        self.retrieval_hits = []
        self.rerank_hits = []
        self.fallback_events = []
        self.updates = []

    def ensure_schema(self):
        return True

    def start_query_run(self, record):
        self.run_records.append(record)
        return record.id

    def update_query_run(self, run_id, **fields):
        self.updates.append((run_id, fields))
        return 1

    def append_query_events(self, records):
        self.events.extend(list(records))
        return len(self.events)

    def append_source_docs(self, records):
        self.source_docs.extend(list(records))
        return len(self.source_docs)

    def append_chunks(self, records):
        self.chunks.extend(list(records))
        return len(self.chunks)

    def append_retrieval_hits(self, records):
        self.retrieval_hits.extend(list(records))
        return len(self.retrieval_hits)

    def append_rerank_hits(self, records):
        self.rerank_hits.extend(list(records))
        return len(self.rerank_hits)

    def append_fallback_event(self, record):
        self.fallback_events.append(record)
        return record.id


def test_execute_plan_stub_records_rag_observability(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "false")
    monkeypatch.setenv("RAG_V2_BACKEND", "memory")
    monkeypatch.setenv("RAG_V2_TOP_K", "4")
    monkeypatch.setenv("RAG_ENABLE_RERANKER", "false")

    from backend.rag.hybrid_service import reset_rag_service_cache
    from backend.rag.observability_store import reset_rag_observability_store_cache

    reset_rag_service_cache()
    reset_rag_observability_store_cache()

    fake_store = _FakeObservabilityStore()
    monkeypatch.setattr(
        "backend.rag.observability_store.get_rag_observability_store",
        lambda: fake_store,
    )

    from backend.graph.nodes.execute_plan_stub import execute_plan_stub

    thread_id = "tenant1:userA:thread-rag-observe"
    selection_payload = [
        {
            "id": "n1",
            "type": "news",
            "title": "Apple reports strong iPhone demand",
            "snippet": "Revenue guidance improved with stronger iPhone upgrades.",
            "source": "news",
            "url": "https://example.com/apple-1",
        },
        {
            "id": "n2",
            "type": "news",
            "title": "Apple AI features lift services engagement",
            "snippet": "Services usage rose as Apple Intelligence previews expanded.",
            "source": "news",
            "url": "https://example.com/apple-2",
        },
    ]
    state = {
        "thread_id": thread_id,
        "query": "苹果最近的 iPhone 需求和服务业务怎么样",
        "plan_ir": {
            "goal": "x",
            "subject": {
                "subject_type": "company",
                "tickers": ["AAPL"],
                "selection_ids": ["n1", "n2"],
                "selection_types": ["news", "news"],
                "selection_payload": selection_payload,
            },
            "output_mode": "investment_report",
            "steps": [],
            "budget": {"max_rounds": 1, "max_tools": 1},
            "synthesis": {"style": "concise", "sections": []},
        },
        "policy": {"allowed_tools": [], "allowed_agents": [], "budget": {"max_rounds": 1, "max_tools": 1}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_payload": selection_payload,
        },
        "trace": {},
    }

    out = _run(execute_plan_stub(state))
    artifacts = out.get("artifacts") or {}
    rag_trace = (out.get("trace") or {}).get("rag") or {}

    assert fake_store.run_records, "should create query run record"
    run_record = fake_store.run_records[0]
    assert run_record.id.startswith("ragrun_")
    assert run_record.user_id == "userA"
    assert run_record.session_id == thread_id

    assert fake_store.source_docs, "should persist source docs"
    assert fake_store.chunks, "should persist chunks"
    assert fake_store.retrieval_hits, "should persist retrieval hits"
    assert fake_store.rerank_hits, "should persist rerank hits"
    assert fake_store.events, "should persist query events"
    assert any(event.event_type == "retrieval_done" for event in fake_store.events)
    assert any(event.event_type == "run_completed" for event in fake_store.events)

    rag_context = artifacts.get("rag_context") or []
    assert rag_context, "rag_context should remain populated"
    top_hit = rag_context[0]
    assert top_hit.get("run_id") == run_record.id
    assert top_hit.get("source_doc_id")
    assert top_hit.get("chunk_id")
    assert top_hit.get("chunk_strategy")

    assert rag_trace.get("run_id") == run_record.id
    assert rag_trace.get("source_doc_count", 0) >= 1
    assert rag_trace.get("chunk_count", 0) >= 1
    assert fake_store.updates and fake_store.updates[-1][0] == run_record.id



def test_execute_plan_stub_searches_memory_working_set_and_kb(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "false")
    monkeypatch.setenv("RAG_V2_BACKEND", "memory")
    monkeypatch.setenv("RAG_V2_TOP_K", "12")
    monkeypatch.setenv("RAG_V2_RERANK_TOP_N", "12")
    monkeypatch.setenv("RAG_ENABLE_RERANKER", "false")

    from backend.rag.hybrid_service import reset_rag_service_cache
    from backend.rag.observability_store import reset_rag_observability_store_cache

    reset_rag_service_cache()
    reset_rag_observability_store_cache()

    fake_store = _FakeObservabilityStore()
    monkeypatch.setattr(
        "backend.rag.observability_store.get_rag_observability_store",
        lambda: fake_store,
    )

    from backend.graph.nodes.execute_plan_stub import execute_plan_stub

    selection_payload = [
        {
            "id": "filing1",
            "type": "filing",
            "title": "Alphabet annual report gross margin and capex",
            "snippet": "Alphabet annual report highlights gross margin stability and AI capex discipline.",
            "source": "filing",
            "url": "https://example.com/googl-10k",
        },
        {
            "id": "news1",
            "type": "news",
            "title": "Alphabet services outlook improves",
            "snippet": "Google services and advertising demand improved with stronger monetization.",
            "source": "news",
            "url": "https://example.com/googl-news",
        },
    ]
    state = {
        "thread_id": "tenant1:userA:thread-rag-3layer",
        "query": "GOOGL watchlist capex margin services outlook",
        "memory_context": {
            "watchlist": ["GOOGL"],
            "last_focus": {
                "ticker": "GOOGL",
                "query": "Alphabet capex margin",
                "summary": "Watch capex discipline and margin expansion for GOOGL.",
                "updated_at": "2026-03-07T10:00:00Z",
            },
            "recent_focuses": [
                {
                    "ticker": "GOOGL",
                    "query": "Alphabet services outlook",
                    "summary": "Services and advertising demand are improving.",
                    "updated_at": "2026-03-07T11:00:00Z",
                }
            ],
        },
        "plan_ir": {
            "goal": "x",
            "subject": {
                "subject_type": "company",
                "tickers": ["GOOGL"],
                "selection_ids": ["filing1", "news1"],
                "selection_types": ["filing", "news"],
                "selection_payload": selection_payload,
            },
            "output_mode": "investment_report",
            "steps": [],
            "budget": {"max_rounds": 1, "max_tools": 1},
            "synthesis": {"style": "concise", "sections": []},
        },
        "policy": {"allowed_tools": [], "allowed_agents": [], "budget": {"max_rounds": 1, "max_tools": 1}},
        "subject": {
            "subject_type": "company",
            "tickers": ["GOOGL"],
            "selection_payload": selection_payload,
        },
        "trace": {},
    }

    out = _run(execute_plan_stub(state))
    rag_trace = (out.get("trace") or {}).get("rag") or {}

    scope_event = next(event for event in fake_store.events if event.event_type == "retrieval_scope_planned")
    retrieval_event = next(event for event in fake_store.events if event.event_type == "retrieval_done")

    search_collections = scope_event.payload_json.get("search_collections") or []
    assert len(search_collections) == 3
    assert any(str(value).startswith("mem:") for value in search_collections)
    assert any(str(value).startswith("ws:") for value in search_collections)
    assert any(str(value).startswith("kb:") for value in search_collections)

    layers = {str(item.get("layer") or "") for item in (retrieval_event.payload_json.get("layer_hit_breakdown") or [])}
    assert {"memory", "ws", "kb"}.issubset(layers)

    hit_layers = {
        str((hit.metadata_json or {}).get("layer") or "")
        for hit in fake_store.retrieval_hits
    }
    assert {"memory", "ws", "kb"}.issubset(hit_layers)

    assert rag_trace.get("memory_collection")
    assert len(rag_trace.get("search_collections") or []) == 3
    assert {"memory", "ws", "kb"}.issubset({str(item.get("layer") or "") for item in (rag_trace.get("layer_hit_breakdown") or [])})



def test_execute_plan_stub_surfaces_memory_ws_kb_layers(monkeypatch):
    monkeypatch.setenv("LANGGRAPH_EXECUTE_LIVE_TOOLS", "false")
    monkeypatch.setenv("RAG_V2_BACKEND", "memory")
    monkeypatch.setenv("RAG_V2_TOP_K", "6")
    monkeypatch.setenv("RAG_ENABLE_RERANKER", "false")

    from backend.rag.hybrid_service import reset_rag_service_cache
    from backend.rag.observability_store import reset_rag_observability_store_cache

    reset_rag_service_cache()
    reset_rag_observability_store_cache()

    fake_store = _FakeObservabilityStore()
    monkeypatch.setattr(
        "backend.rag.observability_store.get_rag_observability_store",
        lambda: fake_store,
    )

    from backend.graph.nodes.execute_plan_stub import execute_plan_stub

    thread_id = "tenant1:userA:thread-rag-3layer"
    selection_payload = [
        {
            "id": "r1",
            "type": "research",
            "title": "Apple AI capital expenditure outlook",
            "snippet": "Capital expenditure is rising with AI infrastructure, services demand, and long-term product roadmap.",
            "source": "research",
            "url": "https://example.com/apple-research",
        },
        {
            "id": "n1",
            "type": "news",
            "title": "Apple services momentum remains strong",
            "snippet": "Services revenue and engagement improved after new AI features launched.",
            "source": "news",
            "url": "https://example.com/apple-news",
        },
    ]
    state = {
        "thread_id": thread_id,
        "query": "?? AI ????????????????",
        "memory_context": {
            "risk_tolerance": "high",
            "investment_style": "growth",
            "watchlist": ["AAPL", "MSFT"],
            "last_focus": {
                "ticker": "AAPL",
                "query": "Apple AI capital expenditure",
                "summary": "??????????????????",
                "sentiment": "bullish",
                "updated_at": "2026-03-01T00:00:00Z",
            },
            "recent_focuses": [
                {
                    "ticker": "AAPL",
                    "query": "Apple services demand",
                    "summary": "????????????",
                    "sentiment": "positive",
                    "updated_at": "2026-03-02T00:00:00Z",
                }
            ],
        },
        "plan_ir": {
            "goal": "x",
            "subject": {
                "subject_type": "company",
                "tickers": ["AAPL"],
                "selection_ids": ["r1", "n1"],
                "selection_types": ["research", "news"],
                "selection_payload": selection_payload,
            },
            "output_mode": "investment_report",
            "steps": [],
            "budget": {"max_rounds": 1, "max_tools": 1},
            "synthesis": {"style": "concise", "sections": []},
        },
        "policy": {"allowed_tools": [], "allowed_agents": [], "budget": {"max_rounds": 1, "max_tools": 1}},
        "subject": {
            "subject_type": "company",
            "tickers": ["AAPL"],
            "selection_payload": selection_payload,
        },
        "trace": {},
    }

    out = _run(execute_plan_stub(state))
    rag_trace = (out.get("trace") or {}).get("rag") or {}
    rag_stats = (out.get("artifacts") or {}).get("rag_stats") or {}

    scope_event = next(event for event in fake_store.events if event.event_type == "retrieval_scope_planned")
    search_collections = scope_event.payload_json.get("search_collections") or []
    assert len(search_collections) == 3
    assert search_collections[0].startswith("mem:thread:")
    assert search_collections[1].startswith("ws:thread:")
    assert search_collections[2].startswith("kb:stock:")

    breakdown = rag_trace.get("layer_hit_breakdown") or rag_stats.get("layer_hit_breakdown") or []
    layers = {item.get("layer") for item in breakdown}
    assert {"memory", "ws", "kb"}.issubset(layers)

    retrieval_done = next(event for event in fake_store.events if event.event_type == "retrieval_done")
    retrieval_breakdown = retrieval_done.payload_json.get("layer_hit_breakdown") or []
    assert {item.get("layer") for item in retrieval_breakdown} >= {"memory", "ws", "kb"}

    assert any(
        "kb" in (record.metadata_json.get("matched_layers") or [])
        for record in fake_store.retrieval_hits
        if isinstance(record.metadata_json, dict)
    )

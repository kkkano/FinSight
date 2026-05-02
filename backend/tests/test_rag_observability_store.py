# -*- coding: utf-8 -*-

from __future__ import annotations

import time
from datetime import datetime, timezone

from backend.rag.observability_models import PendingIngestBatch, QueryRunRecord, SearchRunContext
from backend.rag.hybrid_service import RAGDocument
from backend.rag.observability_store import (
    NoOpRAGObservabilityStore,
    SQLRAGObservabilityStore,
    install_rag_observability_hooks,
    suppress_rag_observability_hooks,
)


class _FakeResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def mappings(self):
        return self

    def __iter__(self):
        return iter(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None

    def all(self):
        return list(self._rows)


class _FakeConnection:
    def __init__(self, responses, executions=None):
        self._responses = list(responses)
        self._executions = executions if executions is not None else []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, _sql, _params=None):
        self._executions.append((str(_sql), dict(_params or {})))
        if not self._responses:
            raise AssertionError('unexpected SQL execution')
        return self._responses.pop(0)


class _FakeEngine:
    def __init__(self, responses):
        self._responses = list(responses)
        self.executions = []

    def connect(self):
        return _FakeConnection(self._responses, self.executions)


class _ProbeStore(SQLRAGObservabilityStore):
    def __init__(self):
        self.updated = []
        self.events = []

    def _materialize_pending_batch(self, context: SearchRunContext) -> None:
        context.source_doc_map = {'doc-1': 'source-doc-1', 'doc-2': 'source-doc-2'}
        context.primary_chunk_map = {'doc-1': 'chunk-primary-1', 'doc-2': 'chunk-primary-2'}
        context.materialized_source_doc_count = 2
        context.materialized_chunk_count = 7

    def _build_hit_records(self, context: SearchRunContext, hits):
        return []

    def append_retrieval_hits(self, records):
        return len(list(records))

    def append_fallback_event(self, record):
        return record.id

    def update_query_run(self, run_id: str, **fields):
        self.updated.append((run_id, fields))
        return 1

    def _append_event(self, run_id: str, event_type: str, stage: str, payload):
        self.events.append((run_id, event_type, stage, payload))


class _HookProbeStore(NoOpRAGObservabilityStore):
    def __init__(self):
        self.begin_calls = []
        self.cache_calls = []
        self.complete_calls = []

    def cache_ingest_batch(self, **kwargs):
        self.cache_calls.append(kwargs)
        return []

    def begin_search_run(self, **kwargs):
        self.begin_calls.append(kwargs)
        return super().begin_search_run(**kwargs)

    def complete_search_run(self, context, *, hits=None, error=None):
        self.complete_calls.append((context, hits, error))
        return super().complete_search_run(context, hits=hits, error=error)


def test_begin_search_run_redacts_sensitive_query_text():
    store = NoOpRAGObservabilityStore()

    context = store.begin_search_run(
        query="请分析 test@example.com token sk-1234567890abcdef1234567890 账号 6222021234567890123",
        collection="ws:thread:tenant:user:thread",
        top_k=3,
        backend_requested="memory",
        backend_actual="memory",
    )

    redacted = context.run.query_text_redacted or ""
    assert "test@example.com" not in redacted
    assert "sk-1234567890abcdef1234567890" not in redacted
    assert "6222021234567890123" not in redacted
    assert "[email]" in redacted
    assert "[secret]" in redacted
    assert "[number]" in redacted


def test_suppress_rag_observability_hooks_skips_service_side_runs(monkeypatch):
    from backend import rag as rag_pkg
    from backend.rag.hybrid_service import HybridRAGService

    probe = _HookProbeStore()
    monkeypatch.setattr("backend.rag.observability_store.get_rag_observability_store", lambda: probe)
    monkeypatch.setattr(rag_pkg, "get_rag_observability_store", lambda: probe)
    install_rag_observability_hooks()

    service = HybridRAGService.for_testing()

    with suppress_rag_observability_hooks():
        service.ingest_documents([
            RAGDocument(
                collection="ws:thread:tenant:user:thread",
                scope="ephemeral",
                source_id="doc-1",
                content="Apple revenue growth and services demand improved.",
                metadata={"source_id": "doc-1"},
            )
        ])
        hits = service.hybrid_search_many(
            "Apple services demand",
            collections=["ws:thread:tenant:user:thread"],
            top_k=3,
        )

    assert hits
    assert probe.cache_calls == []
    assert probe.begin_calls == []
    assert probe.complete_calls == []


def test_health_summary_returns_24h_counters_and_recent_lists():
    now = datetime(2026, 3, 7, tzinfo=timezone.utc)
    store = SQLRAGObservabilityStore.__new__(SQLRAGObservabilityStore)
    store._engine = _FakeEngine(
        [
            _FakeResult([
                {
                    'id': 'run-1',
                    'query_text': 'AAPL outlook',
                    'collection': 'session:test',
                    'backend_requested': 'postgres',
                    'backend_actual': 'postgres',
                    'status': 'completed',
                    'fallback_reason': None,
                    'retrieval_hit_count': 4,
                    'source_doc_count': 3,
                    'chunk_count': 9,
                    'started_at': now,
                    'finished_at': now,
                    'latency_ms': 12.3,
                }
            ]),
            _FakeResult([
                {
                    'reason_code': 'rag_backend_fallback',
                    'backend_before': 'auto',
                    'backend_after': 'memory',
                    'count': 2,
                    'latest_at': now,
                }
            ]),
            _FakeResult([
                {
                    'recent_run_count_24h': 7,
                    'recent_empty_hit_runs': 2,
                    'last_run_at': now,
                }
            ]),
            _FakeResult([
                {
                    'recent_fallback_count_24h': 3,
                    'last_fallback_at': now,
                }
            ]),
        ]
    )
    store.ensure_schema = lambda: True
    store._pending_batch_count = lambda: 0

    summary = store.health_summary(recent_limit=5, fallback_limit=5)

    assert summary['enabled'] is True
    assert summary['recent_run_count_24h'] == 7
    assert summary['recent_fallback_count_24h'] == 3
    assert abs(summary['recent_empty_hits_rate_24h'] - (2 / 7)) < 1e-9
    assert summary['recent_runs'][0]['id'] == 'run-1'
    assert summary['fallback_summary'][0]['reason_code'] == 'rag_backend_fallback'


def test_list_collections_returns_run_doc_chunk_summary():
    now = datetime(2026, 3, 7, tzinfo=timezone.utc)
    store = SQLRAGObservabilityStore.__new__(SQLRAGObservabilityStore)
    store._engine = _FakeEngine(
        [
            _FakeResult([
                {
                    'collection': 'session:deepsearch:aapl:test',
                    'run_count': 2,
                    'document_count': 19,
                    'chunk_count': 63,
                    'latest_run_at': now,
                    'latest_document_at': now,
                    'row_count': 19,
                    'last_run_at': now,
                    'last_created_at': now,
                    'synthetic_backfill_run_id': 'run-backfill-1',
                    'synthetic_backfill_started_at': now,
                }
            ])
        ]
    )
    store.ensure_schema = lambda: True

    summary = store.list_collections(limit=25)

    assert summary['items'][0]['collection'] == 'session:deepsearch:aapl:test'
    assert summary['items'][0]['run_count'] == 2
    assert summary['items'][0]['document_count'] == 19
    assert summary['items'][0]['chunk_count'] == 63
    assert summary['items'][0]['row_count'] == 19
    assert summary['items'][0]['latest_run_at'] == now
    assert summary['items'][0]['latest_document_at'] == now
    assert summary['items'][0]['synthetic_backfill_run_id'] == 'run-backfill-1'
    assert summary['items'][0]['synthetic_backfill_started_at'] == now


def test_browse_db_table_returns_page_payload_and_excludes_vector_columns():
    now = datetime(2026, 3, 7, tzinfo=timezone.utc)
    store = SQLRAGObservabilityStore.__new__(SQLRAGObservabilityStore)
    store._engine = _FakeEngine(
        [
            _FakeResult([
                {'column_name': 'id'},
                {'column_name': 'collection'},
                {'column_name': 'scope'},
                {'column_name': 'source_id'},
                {'column_name': 'title'},
                {'column_name': 'url'},
                {'column_name': 'source'},
                {'column_name': 'content'},
                {'column_name': 'metadata'},
                {'column_name': 'embedding'},
                {'column_name': 'search_vector'},
                {'column_name': 'created_at'},
                {'column_name': 'expires_at'},
            ]),
            _FakeResult([{'total': 3}]),
            _FakeResult([
                {
                    'id': 101,
                    'collection': 'local-test',
                    'scope': 'public',
                    'source_id': 'doc-1',
                    'title': 'Apple earnings call',
                    'url': 'https://example.com/apple',
                    'source': 'transcript',
                    'content': 'Revenue grew strongly.',
                    'metadata': {'run_id': 'run-1', 'source_doc_id': 'source-doc-1'},
                    'created_at': now,
                    'expires_at': None,
                },
                {
                    'id': 102,
                    'collection': 'local-test',
                    'scope': 'public',
                    'source_id': 'doc-2',
                    'title': 'Apple 10-K',
                    'url': 'https://example.com/10k',
                    'source': 'filing',
                    'content': 'Net sales increased.',
                    'metadata': {'run_id': 'run-1', 'source_doc_id': 'source-doc-2'},
                    'created_at': now,
                    'expires_at': None,
                },
            ]),
        ]
    )
    store.ensure_schema = lambda: True

    payload = store.browse_db_table(table_name='rag_documents_v2', limit=2, offset=0, q='apple', collection='local-test', run_id='run-1')

    assert payload['table'] == 'rag_documents_v2'
    assert payload['columns'] == ['id', 'collection', 'scope', 'source_id', 'title', 'url', 'source', 'content', 'metadata', 'created_at', 'expires_at', 'layer', 'collection_kind', 'entity_scope', 'entity_key']
    assert payload['total'] == 3
    assert payload['limit'] == 2
    assert payload['offset'] == 0
    assert payload['has_more'] is True
    assert payload['items'][0]['id'] == 101
    assert payload['items'][0]['metadata']['run_id'] == 'run-1'


def test_browse_db_table_filters_layer_from_metadata_json_without_collection_column():
    store = SQLRAGObservabilityStore.__new__(SQLRAGObservabilityStore)
    engine = _FakeEngine(
        [
            _FakeResult([
                {'column_name': 'id'},
                {'column_name': 'run_id'},
                {'column_name': 'source_id'},
                {'column_name': 'title'},
                {'column_name': 'metadata_json'},
                {'column_name': 'created_at'},
            ]),
            _FakeResult([{'total': 1}]),
            _FakeResult([
                {
                    'id': 'source-doc-1',
                    'run_id': 'run-1',
                    'source_id': 'doc-1',
                    'title': 'Apple knowledge base source',
                    'metadata_json': {'layer': 'kb'},
                    'created_at': datetime(2026, 3, 7, tzinfo=timezone.utc),
                }
            ]),
        ]
    )
    store._engine = engine
    store.ensure_schema = lambda: True

    payload = store.browse_db_table(table_name='rag_source_docs', limit=10, offset=0, layer='kb')

    count_sql, count_params = engine.executions[1]
    rows_sql, rows_params = engine.executions[2]
    assert payload['total'] == 1
    assert payload['items'][0]['metadata_json']['layer'] == 'kb'
    assert "metadata_json ->> 'layer' = :layer" in count_sql
    assert "metadata_json ->> 'layer' = :layer" in rows_sql
    assert count_params['layer'] == 'kb'
    assert rows_params['layer'] == 'kb'


def test_complete_search_run_uses_materialized_chunk_count_for_summary():
    store = _ProbeStore()
    context = SearchRunContext(
        run=QueryRunRecord(
            id='run-test',
            user_id='user-test',
            session_id='session-test',
            thread_id=None,
            query_text='AAPL deepsearch',
            query_hash='hash-test',
        ),
        pending_batch=PendingIngestBatch(
            id='batch-1',
            collection='session:deepsearch:aapl:test',
            backend_requested='postgres',
            backend_actual='postgres',
        ),
        started_monotonic=time.monotonic(),
    )

    result = store.complete_search_run(context, hits=[])

    assert result['status'] == 'completed'
    assert store.updated
    _, fields = store.updated[-1]
    assert fields['source_doc_count'] == 2
    assert fields['chunk_count'] == 7
    assert fields['retrieval_hit_count'] == 0
    assert store.events[-1][1] == 'search_completed'
    assert store.events[-1][3]['chunk_count'] == 7


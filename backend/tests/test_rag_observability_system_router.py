# -*- coding: utf-8 -*-

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.system_router import SystemRouterDeps, create_system_router


class _FakeRagStore:
    def __init__(self) -> None:
        self.last_runs_args: dict[str, object] | None = None
        self.last_db_browser_args: dict[str, object] | None = None

    def health_summary(self, recent_limit: int = 5, fallback_limit: int = 5) -> dict[str, object]:
        return {
            'enabled': True,
            'status': 'ok',
            'backend': 'postgres',
            'recent_run_count_24h': recent_limit,
            'recent_fallback_count_24h': fallback_limit,
            'recent_empty_hits_rate_24h': 0.0,
            'last_run_at': '2026-03-06T00:00:00Z',
            'last_fallback_at': None,
            'recent_runs': [],
            'fallback_summary': [],
        }

    def list_runs(self, *, limit: int = 20, cursor: str | None = None, q: str | None = None, fallback_only: bool = False) -> dict[str, object]:
        self.last_runs_args = {
            'limit': limit,
            'cursor': cursor,
            'q': q,
            'fallback_only': fallback_only,
        }
        return {
            'items': [
                {
                    'id': 'run-1',
                    'query_text': 'AAPL earnings outlook',
                    'status': 'success',
                    'backend_actual': 'postgres',
                    'retrieval_hit_count': 3,
                }
            ],
            'next_cursor': None,
        }

    def get_run_detail(self, run_id: str) -> dict[str, object] | None:
        if run_id != 'run-1':
            return None
        return {
            'id': 'run-1',
            'query_text': 'AAPL earnings outlook',
            'status': 'success',
            'backend_actual': 'postgres',
            'collection': 'finance-news',
        }

    def list_events(self, *, run_id: str, limit: int = 500) -> dict[str, object]:
        return {'items': [{'id': 'evt-1', 'run_id': run_id, 'seq_no': 1, 'event_type': 'query_received'}], 'next_cursor': None}

    def list_documents(self, **_: object) -> dict[str, object]:
        return {'items': [], 'next_cursor': None}

    def list_chunks(self, **_: object) -> dict[str, object]:
        return {'items': [], 'next_cursor': None}

    def list_hits(self, **_: object) -> dict[str, object]:
        return {'items': [], 'next_cursor': None}

    def list_collections(self, *, limit: int = 200) -> dict[str, object]:
        return {
            'items': [
                {
                    'collection': 'finance-news',
                    'run_count': 2,
                    'document_count': limit,
                    'chunk_count': 63,
                    'latest_run_at': '2026-03-07T00:00:00Z',
                    'latest_document_at': '2026-03-06T00:00:00Z',
                    'row_count': limit,
                    'last_run_at': '2026-03-07T00:00:00Z',
                    'last_created_at': '2026-03-06T00:00:00Z',
                    'synthetic_backfill_run_id': 'run-backfill-1',
                    'synthetic_backfill_started_at': '2026-03-07T01:45:32Z',
                }
            ]
        }

    def browse_db_table(self, *, table_name: str, limit: int = 50, offset: int = 0, q: str | None = None, collection: str | None = None, run_id: str | None = None, source_doc_id: str | None = None) -> dict[str, object]:
        self.last_db_browser_args = {
            'table_name': table_name,
            'limit': limit,
            'offset': offset,
            'q': q,
            'collection': collection,
            'run_id': run_id,
            'source_doc_id': source_doc_id,
        }
        return {
            'table': table_name,
            'columns': ['id', 'collection'],
            'items': [{'id': 'row-1', 'collection': collection or 'finance-news'}],
            'total': 1,
            'limit': limit,
            'offset': offset,
            'has_more': False,
        }

    def search_preview(self, *, query: str, collection: str, top_k: int = 10) -> list[dict[str, object]]:
        return [{'query': query, 'collection': collection, 'top_k': top_k}]

    def soft_delete_run(self, run_id: str, deleted_by: str = 'system', reason: str | None = None) -> dict[str, object] | None:
        return {'id': run_id, 'deleted_by': deleted_by, 'reason': reason}

    def soft_delete_source_doc(self, source_doc_id: str, deleted_by: str = 'system', reason: str | None = None) -> dict[str, object] | None:
        return {'id': source_doc_id, 'deleted_by': deleted_by, 'reason': reason}


def _build_client(store: _FakeRagStore) -> TestClient:
    app = FastAPI()
    app.include_router(
        create_system_router(
            SystemRouterDeps(
                metrics_enabled=False,
                metrics_payload=lambda: ('', 'text/plain'),
                graph_runner_ready=lambda: True,
                get_graph_checkpointer_info=lambda: {'backend': 'memory'},
                get_orchestrator_safe=lambda: None,
                get_planner_ab_metrics=lambda: {'enabled': False, 'split_percent': 0, 'variants': {'A': 0, 'B': 0}},
                get_rag_observability_store=lambda: store,
                require_rag_read_access=lambda _request: {'user_id': 'user-test', 'auth_type': 'test', 'role': 'reader'},
                require_rag_mutation_access=lambda _request: {'user_id': 'internal', 'auth_type': 'test', 'role': 'internal'},
                memory_service=object(),
                logger=None,
            )
        )
    )
    return TestClient(app)


def test_rag_status_endpoint_returns_health_summary():
    client = _build_client(_FakeRagStore())

    response = client.get('/diagnostics/rag/status')

    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'ok'
    assert payload['data']['enabled'] is True
    assert payload['data']['backend'] == 'postgres'


def test_rag_runs_endpoint_returns_items_and_passes_filters():
    store = _FakeRagStore()
    client = _build_client(store)

    response = client.get('/diagnostics/rag/runs', params={'limit': 15, 'q': 'AAPL', 'fallback_only': 'true'})

    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'ok'
    assert payload['data']['items'][0]['id'] == 'run-1'
    assert store.last_runs_args == {'limit': 15, 'cursor': None, 'q': 'AAPL', 'fallback_only': True}


def test_rag_run_detail_endpoint_returns_item_and_404_for_missing_run():
    client = _build_client(_FakeRagStore())

    ok_response = client.get('/diagnostics/rag/runs/run-1')
    missing_response = client.get('/diagnostics/rag/runs/run-missing')

    assert ok_response.status_code == 200
    assert ok_response.json()['data']['collection'] == 'finance-news'
    assert missing_response.status_code == 404
    assert missing_response.json()['detail'] == 'run not found'


def test_rag_collections_endpoint_returns_collection_summary():
    client = _build_client(_FakeRagStore())

    response = client.get('/diagnostics/rag/collections', params={'limit': 12})

    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'ok'
    assert payload['data']['items'][0]['collection'] == 'finance-news'
    assert payload['data']['items'][0]['run_count'] == 2
    assert payload['data']['items'][0]['document_count'] == 12
    assert payload['data']['items'][0]['chunk_count'] == 63
    assert payload['data']['items'][0]['row_count'] == 12
    assert payload['data']['items'][0]['synthetic_backfill_run_id'] == 'run-backfill-1'
    assert payload['data']['items'][0]['synthetic_backfill_started_at'] == '2026-03-07T01:45:32Z'


def test_rag_db_browser_endpoint_returns_rows_and_passes_filters():
    store = _FakeRagStore()
    client = _build_client(store)

    response = client.get(
        '/diagnostics/rag/db-browser/rag_chunks',
        params={
            'limit': 25,
            'offset': 50,
            'q': 'apple',
            'collection': 'local-test',
            'run_id': 'run-1',
            'source_doc_id': 'doc-1',
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'ok'
    assert payload['data']['table'] == 'rag_chunks'
    assert payload['data']['columns'] == ['id', 'collection']
    assert payload['data']['items'][0]['id'] == 'row-1'
    assert store.last_db_browser_args == {
        'table_name': 'rag_chunks',
        'limit': 25,
        'offset': 50,
        'q': 'apple',
        'collection': 'local-test',
        'run_id': 'run-1',
        'source_doc_id': 'doc-1',
    }


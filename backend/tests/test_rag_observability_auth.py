# -*- coding: utf-8 -*-

from __future__ import annotations

from fastapi.testclient import TestClient


class _FakeRagStore:
    def health_summary(self, recent_limit: int = 5, fallback_limit: int = 5) -> dict[str, object]:
        return {
            'enabled': True,
            'status': 'ok',
            'backend': 'postgres',
            'recent_run_count_24h': recent_limit,
            'recent_fallback_count_24h': fallback_limit,
            'recent_runs': [],
            'fallback_summary': [],
        }

    def soft_delete_run(self, run_id: str, deleted_by: str = 'system', reason: str | None = None) -> dict[str, object] | None:
        return {'id': run_id, 'deleted_by': deleted_by, 'reason': reason}

    def soft_delete_source_doc(self, source_doc_id: str, deleted_by: str = 'system', reason: str | None = None) -> dict[str, object] | None:
        return {'id': source_doc_id, 'deleted_by': deleted_by, 'reason': reason}


def _configure_auth(monkeypatch):
    from backend.api import main

    monkeypatch.setenv('VITE_SUPABASE_URL', 'https://supabase.test')
    monkeypatch.setenv('VITE_SUPABASE_PUBLISHABLE_KEY', 'sb_publishable_test')
    monkeypatch.setattr(main, '_rate_limiter', main.SimpleRateLimiter(limit_per_window=100, window_seconds=60, enabled=False))
    monkeypatch.setattr(main, 'get_rag_observability_store', lambda: _FakeRagStore())
    main._auth_identity_cache.clear()
    return main


def test_rag_diagnostics_read_requires_logged_in_user(monkeypatch):
    main = _configure_auth(monkeypatch)
    monkeypatch.setenv('API_AUTH_ENABLED', 'false')

    with TestClient(main.app) as client:
        response = client.get('/diagnostics/rag/status')

    assert response.status_code == 401
    assert response.json().get('detail') == 'Authentication required'


def test_rag_diagnostics_read_allows_bearer_user_even_when_api_auth_enabled(monkeypatch):
    main = _configure_auth(monkeypatch)
    monkeypatch.setenv('API_AUTH_ENABLED', 'true')
    monkeypatch.setenv('API_AUTH_KEYS', 'release-key-1')
    monkeypatch.setattr(
        main,
        '_fetch_supabase_user_identity',
        lambda token: {'user_id': f'user:{token}', 'email': 'reader@example.com', 'auth_type': 'supabase', 'role': 'reader'},
    )

    with TestClient(main.app) as client:
        response = client.get('/diagnostics/rag/status', headers={'Authorization': 'Bearer access-token-reader'})

    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'ok'
    assert payload['data']['enabled'] is True


def test_rag_diagnostics_soft_delete_is_read_only_for_logged_in_user(monkeypatch):
    main = _configure_auth(monkeypatch)
    monkeypatch.setenv('API_AUTH_ENABLED', 'false')
    monkeypatch.setattr(
        main,
        '_fetch_supabase_user_identity',
        lambda token: {'user_id': f'user:{token}', 'email': 'reader@example.com', 'auth_type': 'supabase', 'role': 'reader'},
    )

    with TestClient(main.app) as client:
        response = client.post(
            '/diagnostics/rag/runs/run-1/soft-delete',
            headers={'Authorization': 'Bearer access-token-readonly'},
            json={'deleted_by': 'reader'},
        )

    assert response.status_code == 403
    assert 'read-only' in str(response.json().get('detail', '')).lower()


def test_rag_diagnostics_soft_delete_allows_internal_api_key(monkeypatch):
    main = _configure_auth(monkeypatch)
    monkeypatch.setenv('API_AUTH_ENABLED', 'false')
    monkeypatch.setenv('API_AUTH_KEYS', 'release-key-1')

    with TestClient(main.app) as client:
        response = client.post(
            '/diagnostics/rag/runs/run-1/soft-delete',
            headers={'x-api-key': 'release-key-1'},
            json={'deleted_by': 'ops-user', 'reason': 'retention drill'},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'ok'
    assert payload['data']['id'] == 'run-1'
    assert payload['data']['deleted_by'] == 'ops-user'

def test_rag_diagnostics_read_allows_local_dev_bearer_without_supabase(monkeypatch):
    from backend.api import main

    monkeypatch.delenv('VITE_SUPABASE_URL', raising=False)
    monkeypatch.delenv('VITE_SUPABASE_PUBLISHABLE_KEY', raising=False)
    monkeypatch.delenv('SUPABASE_URL', raising=False)
    monkeypatch.delenv('SUPABASE_PUBLISHABLE_KEY', raising=False)
    monkeypatch.setenv('API_AUTH_ENABLED', 'false')
    monkeypatch.setenv('RAG_OBSERVABILITY_DEV_AUTH_ENABLED', 'true')
    monkeypatch.setenv('RAG_OBSERVABILITY_DEV_ACCESS_TOKEN', 'local-rag-dev-token')
    monkeypatch.setenv('RAG_OBSERVABILITY_DEV_USER_ID', 'dev-rag-user')
    monkeypatch.setenv('RAG_OBSERVABILITY_DEV_EMAIL', 'dev-rag@example.com')
    monkeypatch.setattr(main, '_rate_limiter', main.SimpleRateLimiter(limit_per_window=100, window_seconds=60, enabled=False))
    monkeypatch.setattr(main, 'get_rag_observability_store', lambda: _FakeRagStore())
    main._auth_identity_cache.clear()

    with TestClient(main.app) as client:
        response = client.get('/diagnostics/rag/status', headers={'Authorization': 'Bearer local-rag-dev-token'})

    assert response.status_code == 200
    payload = response.json()
    assert payload['status'] == 'ok'
    assert payload['data']['enabled'] is True
    assert payload['data']['backend'] == 'postgres'

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.requests import Request

from backend.api.client_recovery import router
from backend.api.security_gate import _is_public_request


def test_recovery_page_is_static_uncached_and_does_not_clear_user_storage():
    app=FastAPI();app.include_router(router)
    response=TestClient(app).get('/api/client-recovery')
    assert response.status_code==200
    assert 'no-store' in response.headers['cache-control']
    assert "frame-ancestors 'none'" in response.headers['content-security-policy']
    assert '修复页面并打开原会话' in response.text
    assert 'localStorage.clear' not in response.text and 'sessionStorage.clear' not in response.text
    assert 'document.cookie' not in response.text
    assert 'cloudflare' not in response.text


def test_only_exact_read_only_recovery_path_is_public(monkeypatch):
    monkeypatch.setenv('API_PUBLIC_PATHS','/health,/livez,/readyz')
    def request(path,method='GET'):
        return Request({'type':'http','method':method,'path':path,'headers':[],'scheme':'https','server':('example.invalid',443),'query_string':b''})
    assert _is_public_request(request('/api/client-recovery'))
    assert not _is_public_request(request('/api/client-recovery','POST'))
    assert not _is_public_request(request('/api/client-recovery/other'))

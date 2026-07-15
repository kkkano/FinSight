from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api import monitor_router as monitor_router_module


def _client(monkeypatch, *, lease_store=None, comment_store=None) -> TestClient:
    if lease_store is not None:
        monkeypatch.setattr(
            monitor_router_module,
            "get_monitor_lease_store",
            lambda: lease_store,
        )
    if comment_store is not None:
        monkeypatch.setattr(
            monitor_router_module,
            "get_monitor_comment_store",
            lambda: comment_store,
        )
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user_id = request.headers.get("x-test-user", "public")
        return await call_next(request)

    app.include_router(monitor_router_module.monitor_router)
    return TestClient(app)


def test_monitor_lease_api_enforces_auth_tenant_and_token(monkeypatch):
    class MemoryLeaseStore:
        def __init__(self):
            self.items = {}

        def acquire(self, *, user_id, session_id, symbol):
            item = {
                "id": str(uuid.uuid4()),
                "session_id": session_id,
                "symbol": symbol.upper(),
                "lease_token": f"token-{'x' * 24}",
                "expires_at": "2026-07-10T15:01:30Z",
            }
            self.items[(item["id"], user_id)] = item
            return item

        def renew(self, lease_id, *, user_id, lease_token):
            item = self.items.get((lease_id, user_id))
            return item["expires_at"] if item and item["lease_token"] == lease_token else None

        def release(self, lease_id, *, user_id, lease_token):
            item = self.items.get((lease_id, user_id))
            if not item or item["lease_token"] != lease_token:
                return False
            del self.items[(lease_id, user_id)]
            return True

    store = MemoryLeaseStore()
    client = _client(monkeypatch, lease_store=store)
    assert client.post(
        "/api/monitor/leases",
        json={"session_id": "s1", "symbol": "AAPL"},
    ).status_code == 401
    assert client.post(
        "/api/monitor/leases",
        headers={"x-test-user": "alice"},
        json={"session_id": "s1", "symbol": "AAPL;DROP TABLE leases"},
    ).status_code == 422

    response = client.post(
        "/api/monitor/leases",
        headers={"x-test-user": "alice"},
        json={"session_id": "s1", "symbol": "aapl"},
    )
    assert response.status_code == 201
    lease = response.json()["lease"]
    assert lease["symbol"] == "AAPL"
    assert client.put(
        f"/api/monitor/leases/{lease['id']}",
        headers={"x-test-user": "bob"},
        json={"lease_token": lease["lease_token"]},
    ).status_code == 404
    assert client.put(
        f"/api/monitor/leases/{lease['id']}",
        headers={"x-test-user": "alice"},
        json={"lease_token": lease["lease_token"]},
    ).status_code == 200
    assert client.request(
        "DELETE",
        f"/api/monitor/leases/{lease['id']}",
        headers={"x-test-user": "alice"},
        json={"lease_token": lease["lease_token"]},
    ).status_code == 200


def test_monitor_lease_api_fails_closed_when_store_unavailable(monkeypatch):
    class Down:
        def acquire(self, **_kwargs):
            raise RuntimeError("private database detail")

    response = _client(monkeypatch, lease_store=Down()).post(
        "/api/monitor/leases",
        headers={"x-test-user": "alice"},
        json={"session_id": "s1", "symbol": "AAPL"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "monitor lease store unavailable"


def test_comments_are_scoped_by_user_session_and_current_symbol(monkeypatch):
    calls = []
    prediction_id = "11111111-1111-1111-1111-111111111111"
    comment = SimpleNamespace(model_dump=lambda mode=None: {
        "id": str(uuid.uuid4()),
        "session_id": "s1",
        "symbol": "AAPL",
        "ts": "2026-07-11T00:00:00Z",
        "level": "alert",
        "text": "突破",
        "trigger": {
            "kind": "prediction_level_break",
            "detail": "突破",
            "observed_at": "now",
        },
        "source": "agent",
        "escalated": True,
        "prediction_id": prediction_id,
    })

    class Store:
        def list(self, **kwargs):
            calls.append(kwargs)
            return [comment], "next"

    client = _client(monkeypatch, comment_store=Store())
    path = "/api/monitor/comments?session_id=s1&symbol=aapl&day=2026-07-11&limit=20"
    assert client.get(path).status_code == 401
    assert client.get(
        "/api/monitor/comments?session_id=s1",
        headers={"x-test-user": "alice"},
    ).status_code == 422
    response = client.get(path, headers={"x-test-user": "alice"})
    assert response.status_code == 200
    assert calls[0]["user_id"] == "alice"
    assert calls[0]["session_id"] == "s1"
    assert calls[0]["symbol"] == "aapl"
    assert response.json()["comments"][0]["chart_url"] == (
        f"/dashboard/AAPL?analysis={prediction_id}"
    )


def test_comment_rest_and_stream_fail_before_200_when_store_unavailable(monkeypatch):
    class Down:
        def list(self, **_kwargs):
            raise RuntimeError("private database detail")

    client = _client(monkeypatch, comment_store=Down())
    headers = {"x-test-user": "alice"}
    query = "?session_id=s1&symbol=AAPL"
    rest = client.get(f"/api/monitor/comments{query}", headers=headers)
    stream = client.get(f"/api/monitor/comments/stream{query}", headers=headers)
    assert rest.status_code == stream.status_code == 503
    assert rest.json()["detail"] == stream.json()["detail"] == (
        "monitor comment store unavailable"
    )


def test_removed_monitor_product_endpoints_are_not_registered(monkeypatch):
    client = _client(monkeypatch)
    headers = {"x-test-user": "alice"}
    for path in (
        "/api/monitor/findings",
        "/api/monitor/targets",
        "/api/monitor/settings",
        "/api/monitor/macro-calendar",
        "/api/monitor/scan",
    ):
        assert client.get(path, headers=headers).status_code == 404

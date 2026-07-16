from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from backend.api.user_router import create_user_router


def _client() -> TestClient:
    app = FastAPI()

    @app.middleware("http")
    async def identity(request: Request, call_next):
        request.state.user_id = request.headers.get("x-test-user", "public")
        request.state.user_email = request.headers.get("x-test-email", "")
        return await call_next(request)

    app.include_router(create_user_router())
    return TestClient(app)


def test_user_profile_requires_authentication() -> None:
    response = _client().get("/api/user/profile")
    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "auth_required"


def test_user_profile_comes_only_from_authenticated_identity() -> None:
    response = _client().get(
        "/api/user/profile?user_id=ignored",
        headers={"x-test-user": "alice", "x-test-email": "alice@example.com"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "user": {"id": "alice", "email": "alice@example.com"}
    }

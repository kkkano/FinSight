from __future__ import annotations

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.requests import Request

from backend.security import supabase_auth
from backend.security.supabase_auth import (
    AuthConfigurationError,
    InvalidTokenError,
    ensure_auth_verifier_ready,
    resolve_request_user,
    verify_supabase_jwt,
)


SECRET = "test-secret-at-least-32-bytes-long"


def _make_token(
    *,
    sub: str | None = "user-1",
    exp_delta: int = 3600,
    secret: str = SECRET,
) -> str:
    payload: dict[str, object] = {
        "aud": "authenticated",
        "email": "a@b.c",
        "exp": int(time.time()) + exp_delta,
    }
    if sub is not None:
        payload["sub"] = sub
    return jwt.encode(payload, secret, algorithm="HS256")


def _request(authorization: str | None = None) -> Request:
    headers = []
    if authorization is not None:
        headers.append((b"authorization", authorization.encode("ascii")))
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers})


def _make_rs256_token() -> tuple[str, dict[str, object]]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(private_key.public_key()))
    public_jwk.update({"kid": "test-key", "alg": "RS256", "use": "sig"})
    token = jwt.encode(
        {
            "sub": "jwks-user",
            "aud": "authenticated",
            "exp": int(time.time()) + 3600,
        },
        private_key,
        algorithm="RS256",
        headers={"kid": "test-key"},
    )
    return token, public_jwk


@pytest.fixture(autouse=True)
def _clear_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    supabase_auth._jwks_cache.clear()


def test_valid_hs256_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)

    user = verify_supabase_jwt(_make_token())

    assert user.user_id == "user-1"
    assert user.email == "a@b.c"


@pytest.mark.parametrize(
    "token",
    [
        _make_token(exp_delta=-100),
        _make_token(secret="other-secret-at-least-32-bytes-long"),
        _make_token(sub=None),
    ],
    ids=["expired", "wrong-secret", "missing-sub"],
)
def test_invalid_hs256_token_rejected(
    monkeypatch: pytest.MonkeyPatch,
    token: str,
) -> None:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)

    with pytest.raises(InvalidTokenError):
        verify_supabase_jwt(token)


def test_missing_auth_configuration_rejected() -> None:
    with pytest.raises(AuthConfigurationError):
        verify_supabase_jwt(_make_token())


def test_auth_verifier_readiness_accepts_hs256_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    monkeypatch.setattr(
        supabase_auth,
        "_fetch_jwks",
        lambda _url: pytest.fail("HS256 配置不应访问 JWKS"),
    )

    ensure_auth_verifier_ready()


def test_auth_verifier_readiness_fetches_usable_jwks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co/")
    monkeypatch.setattr(
        supabase_auth,
        "_fetch_jwks",
        lambda url: {"keys": [{"kid": "active-key"}]}
        if url == "https://example.supabase.co/auth/v1/.well-known/jwks.json"
        else pytest.fail(f"意外的 JWKS URL: {url}"),
    )

    ensure_auth_verifier_ready()


def test_auth_verifier_readiness_rejects_jwks_without_signing_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(supabase_auth, "_fetch_jwks", lambda _url: {"keys": []})

    with pytest.raises(AuthConfigurationError, match="不包含可用签名密钥"):
        ensure_auth_verifier_ready()


def test_resolve_request_user_accepts_valid_bearer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)

    user = resolve_request_user(_request(f"Bearer {_make_token()}"))

    assert user is not None
    assert user.user_id == "user-1"


@pytest.mark.parametrize(
    "authorization",
    [None, "Basic abc", "Bearer", "Bearer invalid-token"],
)
def test_resolve_request_user_returns_none_for_missing_or_invalid_credentials(
    monkeypatch: pytest.MonkeyPatch,
    authorization: str | None,
) -> None:
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)

    assert resolve_request_user(_request(authorization)) is None


def test_rs256_jwks_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    token, public_jwk = _make_rs256_token()
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co/")
    fetch_count = 0

    def fake_fetch(url: str) -> dict[str, object]:
        nonlocal fetch_count
        fetch_count += 1
        assert url == "https://example.supabase.co/auth/v1/.well-known/jwks.json"
        return {"keys": [public_jwk]}

    monkeypatch.setattr(supabase_auth, "_fetch_jwks", fake_fetch)

    assert verify_supabase_jwt(token).user_id == "jwks-user"
    assert verify_supabase_jwt(token).user_id == "jwks-user"
    assert fetch_count == 1


def test_stale_jwks_is_used_when_refresh_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    token, public_jwk = _make_rs256_token()
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    url = "https://example.supabase.co/auth/v1/.well-known/jwks.json"
    supabase_auth._jwks_cache[url] = supabase_auth._JwksCacheEntry(
        payload={"keys": [public_jwk]},
        fetched_at=time.monotonic() - 601,
    )

    def failed_fetch(_url: str) -> dict[str, object]:
        raise OSError("network unavailable")

    monkeypatch.setattr(supabase_auth, "_fetch_jwks", failed_fetch)

    assert verify_supabase_jwt(token).user_id == "jwks-user"

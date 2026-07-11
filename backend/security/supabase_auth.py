"""Supabase JWT 校验与请求身份解析。"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any
from urllib import request as urllib_request

import jwt
from starlette.requests import Request


_AUDIENCE = "authenticated"
_LEEWAY_SECONDS = 30
_JWKS_TTL_SECONDS = 600
_JWKS_TIMEOUT_SECONDS = 5
_JWKS_ALGORITHMS = frozenset({"RS256", "ES256"})


class AuthConfigurationError(RuntimeError):
    """认证配置缺失或 JWKS 当前不可用。"""


class InvalidTokenError(ValueError):
    """JWT 无效、过期或缺少必要身份声明。"""


@dataclass(frozen=True)
class AuthenticatedUser:
    user_id: str
    email: str = ""


@dataclass
class _JwksCacheEntry:
    payload: dict[str, Any]
    fetched_at: float


_jwks_cache: dict[str, _JwksCacheEntry] = {}
_jwks_cache_lock = Lock()


def _jwks_url(supabase_url: str) -> str:
    return f"{supabase_url.rstrip('/')}/auth/v1/.well-known/jwks.json"


def _fetch_jwks(url: str) -> dict[str, Any]:
    request = urllib_request.Request(url, headers={"Accept": "application/json"})
    with urllib_request.urlopen(request, timeout=_JWKS_TIMEOUT_SECONDS) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
        raise ValueError("JWKS 响应缺少 keys 数组")
    return payload


def _get_jwks(url: str) -> dict[str, Any]:
    now = time.monotonic()
    with _jwks_cache_lock:
        cached = _jwks_cache.get(url)
        if cached is not None and now - cached.fetched_at < _JWKS_TTL_SECONDS:
            return cached.payload

    try:
        payload = _fetch_jwks(url)
    except Exception as exc:
        with _jwks_cache_lock:
            stale = _jwks_cache.get(url)
        if stale is not None:
            return stale.payload
        raise AuthConfigurationError("无法获取 Supabase JWKS") from exc

    with _jwks_cache_lock:
        _jwks_cache[url] = _JwksCacheEntry(payload=payload, fetched_at=now)
    return payload


def _select_jwk(jwks: dict[str, Any], kid: str) -> Any:
    for key_data in jwks.get("keys", []):
        if isinstance(key_data, dict) and key_data.get("kid") == kid:
            try:
                return jwt.PyJWK.from_dict(key_data).key
            except Exception as exc:
                raise InvalidTokenError("JWT 签名密钥无效") from exc
    raise InvalidTokenError("JWT 签名密钥不存在")


def _decode_token(token: str) -> dict[str, Any]:
    secret = os.getenv("SUPABASE_JWT_SECRET", "").strip()
    if secret:
        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=_AUDIENCE,
            leeway=_LEEWAY_SECONDS,
        )

    supabase_url = os.getenv("SUPABASE_URL", "").strip()
    if not supabase_url:
        raise AuthConfigurationError("缺少 SUPABASE_JWT_SECRET 或 SUPABASE_URL")

    header = jwt.get_unverified_header(token)
    algorithm = str(header.get("alg", ""))
    kid = str(header.get("kid", ""))
    if algorithm not in _JWKS_ALGORITHMS or not kid:
        raise InvalidTokenError("JWT 算法或 kid 不受支持")

    key = _select_jwk(_get_jwks(_jwks_url(supabase_url)), kid)
    return jwt.decode(
        token,
        key,
        algorithms=[algorithm],
        audience=_AUDIENCE,
        leeway=_LEEWAY_SECONDS,
    )


def verify_supabase_jwt(token: str) -> AuthenticatedUser:
    """校验 Supabase JWT，并返回稳定的用户身份。"""

    if not token or not token.strip():
        raise InvalidTokenError("JWT 不能为空")

    try:
        payload = _decode_token(token.strip())
    except AuthConfigurationError:
        raise
    except InvalidTokenError:
        raise
    except jwt.PyJWTError as exc:
        raise InvalidTokenError("JWT 无效或已过期") from exc
    except Exception as exc:
        raise InvalidTokenError("JWT 无法解析") from exc

    user_id = payload.get("sub")
    if not isinstance(user_id, str) or not user_id.strip():
        raise InvalidTokenError("JWT 缺少 sub")
    email = payload.get("email")
    return AuthenticatedUser(
        user_id=user_id.strip(),
        email=email.strip() if isinstance(email, str) else "",
    )


def resolve_request_user(request: Request) -> AuthenticatedUser | None:
    """解析 Bearer 身份；请求未携带或令牌无效时返回 ``None``。"""

    authorization = request.headers.get("Authorization", "").strip()
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token.strip():
        return None
    try:
        return verify_supabase_jwt(token)
    except (AuthConfigurationError, InvalidTokenError):
        return None


__all__ = [
    "AuthenticatedUser",
    "AuthConfigurationError",
    "InvalidTokenError",
    "resolve_request_user",
    "verify_supabase_jwt",
]

# -*- coding: utf-8 -*-
"""API 安全闸门（WP3 Task6 机械搬运自 backend/api/main.py，零行为变更）。

包含：security_gate 中间件、SimpleRateLimiter/并发限制器实例、客户端 IP 解析、
API key / Supabase / RAG 观测台鉴权全家（身份缓存含锁）。
注册方式：main/app_factory 侧 `app.middleware("http")(security_gate)`。
"""
from __future__ import annotations

import logging
import os
import time
from collections import deque
from threading import Lock
from typing import Any, Dict, Optional

from urllib import error as urllib_error
from urllib import request as urllib_request

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from backend.api.concurrency import ConcurrencyLimiter, is_generation_path

logger = logging.getLogger(__name__)

_AUTH_IDENTITY_CACHE_SENTINEL = object()

_auth_identity_cache: Dict[str, tuple[float, Optional[Dict[str, Any]]]] = {}

_auth_identity_lock = Lock()

def _env_bool(key: str, default: str = "false") -> bool:
    return os.getenv(key, default).lower() in ("true", "1", "yes", "on")

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, default))
    except Exception:
        return default

def _parse_csv_env(key: str, default: str) -> list[str]:
    raw = os.getenv(key, default)
    values = [item.strip() for item in str(raw or "").split(",") if item.strip()]
    return values

def _parse_api_keys() -> set[str]:
    raw = os.getenv("API_AUTH_KEYS") or os.getenv("API_AUTH_KEY") or ""
    return {item.strip() for item in raw.split(",") if item.strip()}

def _extract_api_key(request: Request) -> Optional[str]:
    header_key = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    if header_key:
        return header_key.strip()
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip()
    return None

def _extract_bearer_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth.split(" ", 1)[1].strip() or None
    return None

def _resolve_supabase_auth_config() -> tuple[str, str]:
    supabase_url = str(os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL") or "").strip().rstrip("/")
    publishable_key = str(os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("VITE_SUPABASE_PUBLISHABLE_KEY") or "").strip()
    return supabase_url, publishable_key

def _is_supabase_auth_configured() -> bool:
    supabase_url, publishable_key = _resolve_supabase_auth_config()
    return bool(supabase_url and publishable_key)

def _resolve_rag_observability_dev_auth_config() -> tuple[str, str, Optional[str]]:
    token = str(os.getenv("RAG_OBSERVABILITY_DEV_ACCESS_TOKEN") or "").strip()
    user_id = str(os.getenv("RAG_OBSERVABILITY_DEV_USER_ID") or "local-rag-inspector").strip() or "local-rag-inspector"
    email_raw = str(os.getenv("RAG_OBSERVABILITY_DEV_EMAIL") or "local-rag@example.com").strip()
    return token, user_id, email_raw or None

def _is_rag_observability_dev_auth_enabled() -> bool:
    token, _, _ = _resolve_rag_observability_dev_auth_config()
    return _env_bool("RAG_OBSERVABILITY_DEV_AUTH_ENABLED", "false") and bool(token)

def _resolve_rag_observability_dev_user_identity(token: str) -> Optional[Dict[str, Any]]:
    normalized = str(token or "").strip()
    if not normalized or not _is_rag_observability_dev_auth_enabled():
        return None

    dev_token, user_id, email = _resolve_rag_observability_dev_auth_config()
    if normalized != dev_token:
        return None

    return {
        "user_id": user_id,
        "email": email,
        "auth_type": "dev_bearer",
        "role": "reader",
    }

def _is_internal_api_key_authorized(request: Request) -> bool:
    api_key = _extract_api_key(request)
    return bool(api_key and api_key in _parse_api_keys())

def _auth_identity_cache_ttl_seconds() -> int:
    raw = str(os.getenv("RAG_OBSERVABILITY_AUTH_CACHE_SECONDS", "60") or "60").strip()
    try:
        value = int(raw)
    except Exception:
        value = 60
    return max(5, min(600, value))

def _fetch_supabase_user_identity(token: str) -> Optional[Dict[str, Any]]:
    normalized = str(token or "").strip()
    if not normalized:
        return None

    now = time.time()
    with _auth_identity_lock:
        cached = _auth_identity_cache.get(normalized)
        if cached and cached[0] > now:
            return cached[1]

    supabase_url, publishable_key = _resolve_supabase_auth_config()
    if not supabase_url or not publishable_key:
        raise RuntimeError("RAG diagnostics auth not configured")

    request_obj = urllib_request.Request(
        f"{supabase_url}/auth/v1/user",
        headers={
            "Authorization": f"Bearer {normalized}",
            "apikey": publishable_key,
            "Accept": "application/json",
        },
        method="GET",
    )

    user_identity: Optional[Dict[str, Any]] = None
    try:
        with urllib_request.urlopen(request_obj, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8") or "{}")
        user_id = str(payload.get("id") or "").strip() if isinstance(payload, dict) else ""
        if user_id:
            email = payload.get("email") if isinstance(payload, dict) else None
            user_identity = {
                "user_id": user_id,
                "email": str(email).strip() if email else None,
                "auth_type": "supabase",
                "role": "reader",
            }
    except urllib_error.HTTPError as exc:
        if exc.code not in (401, 403):
            raise RuntimeError(f"Supabase auth lookup failed with HTTP {exc.code}") from exc
    except urllib_error.URLError as exc:
        raise RuntimeError(f"Supabase auth lookup failed: {exc.reason}") from exc

    with _auth_identity_lock:
        _auth_identity_cache[normalized] = (now + _auth_identity_cache_ttl_seconds(), user_identity)
    return user_identity

def _resolve_request_user_identity(request: Request) -> Optional[Dict[str, Any]]:
    cached = getattr(request.state, "rag_authenticated_user", _AUTH_IDENTITY_CACHE_SENTINEL)
    if cached is not _AUTH_IDENTITY_CACHE_SENTINEL:
        return cached

    token = _extract_bearer_token(request)
    if not token:
        request.state.rag_authenticated_user = None
        return None

    dev_identity = _resolve_rag_observability_dev_user_identity(token)
    if dev_identity:
        request.state.rag_authenticated_user = dev_identity
        return dev_identity

    if not _is_supabase_auth_configured():
        request.state.rag_authenticated_user = None
        return None

    user_identity = _fetch_supabase_user_identity(token)
    request.state.rag_authenticated_user = user_identity
    return user_identity

def _require_rag_read_access(request: Request) -> Dict[str, Any]:
    if _is_internal_api_key_authorized(request):
        principal = {"user_id": "internal", "email": None, "auth_type": "api_key", "role": "internal"}
        request.state.rag_authenticated_user = principal
        return principal

    if not (_is_supabase_auth_configured() or _is_rag_observability_dev_auth_enabled()):
        raise HTTPException(status_code=503, detail="RAG diagnostics auth not configured")

    user_identity = _resolve_request_user_identity(request)
    if user_identity:
        return user_identity
    raise HTTPException(status_code=401, detail="Authentication required")

def _require_rag_mutation_access(request: Request) -> Dict[str, Any]:
    if _is_internal_api_key_authorized(request):
        principal = {"user_id": "internal", "email": None, "auth_type": "api_key", "role": "internal"}
        request.state.rag_authenticated_user = principal
        return principal
    raise HTTPException(status_code=403, detail="RAG diagnostics is read-only for logged-in users; mutation requires internal API key")

def _is_allowlisted_path(path: str) -> bool:
    defaults = "/health,/docs,/openapi.json,/redoc"
    configured = _parse_csv_env("API_PUBLIC_PATHS", defaults)
    exact_paths: set[str] = set()
    prefix_paths: list[str] = []

    for entry in configured:
        normalized = entry if entry.startswith("/") else f"/{entry}"
        if normalized.endswith("/*"):
            base = normalized[:-2]
            if base:
                prefix_paths.append(base)
        elif normalized in ("/docs", "/redoc"):
            exact_paths.add(normalized)
            prefix_paths.append(normalized)
        else:
            exact_paths.add(normalized)

    if path in exact_paths:
        return True
    return any(path.startswith(prefix + "/") or path == prefix for prefix in prefix_paths)

class SimpleRateLimiter:
    def __init__(self, limit_per_window: int, window_seconds: int, enabled: bool = True):
        self.enabled = enabled
        self.limit = max(1, int(limit_per_window))
        self.window_seconds = max(1, int(window_seconds))
        self._buckets: Dict[str, deque[float]] = {}
        self._last_cleanup = time.time()

    def _cleanup(self, now: float) -> None:
        if now - self._last_cleanup < self.window_seconds:
            return
        self._last_cleanup = now
        stale_keys = [
            key for key, bucket in self._buckets.items()
            if not bucket or (now - bucket[-1] >= self.window_seconds)
        ]
        for key in stale_keys:
            self._buckets.pop(key, None)

    @classmethod
    def from_env(cls) -> "SimpleRateLimiter":
        enabled = _env_bool("RATE_LIMIT_ENABLED", "true")  # P0-7: 公网产品限流默认开启
        # 默认 300/分钟：Dashboard/A股页一次加载就有 10-20 个数据请求 + 轮询，
        # 120 对单个真实用户太紧（修复真实 IP 识别后限流桶已按用户隔离）
        limit = int(os.getenv("RATE_LIMIT_PER_MINUTE", "300"))
        window_seconds = int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60"))
        return cls(limit_per_window=limit, window_seconds=window_seconds, enabled=enabled)

    def allow(self, key: str) -> tuple[bool, Optional[int]]:
        now = time.time()
        self._cleanup(now)
        bucket = self._buckets.setdefault(key, deque())
        while bucket and now - bucket[0] >= self.window_seconds:
            bucket.popleft()
        if len(bucket) >= self.limit:
            retry_after = int(self.window_seconds - (now - bucket[0])) if bucket else self.window_seconds
            return False, max(1, retry_after)
        bucket.append(now)
        return True, None

_rate_limiter = SimpleRateLimiter.from_env()

_concurrency_limiter = ConcurrencyLimiter.from_env()

def _trust_proxy_headers() -> bool:
    """是否信任反向代理注入的客户端 IP 头（CF-Connecting-IP / X-Forwarded-For 等）。

    ⚠️ 安全前提：这些头由请求方任意设置，只有当服务**确实部署在可信代理之后**
    （如线上的 Cloudflare Tunnel）时才能信任——可信代理会覆写/剥离伪造值。
    若服务直连公网（无可信代理），攻击者可随意伪造 CF-Connecting-IP 来给每个请求
    换一个「客户端 IP」，从而绕过基于 IP 的限流。此时应把开关关闭，回退到连接对端 IP。

    默认 true：保持线上 Cloudflare 部署行为不变（向后兼容）。
    直连公网部署应显式设置 TRUST_PROXY_HEADERS=false。
    """
    return _env_bool("TRUST_PROXY_HEADERS", "true")

def _resolve_client_ip(request: Request) -> str:
    """解析真实客户端 IP（Cloudflare Tunnel / 反向代理感知）。

    线上架构是 Cloudflare Tunnel -> cloudflared -> 容器，request.client.host
    拿到的是隧道/容器网络 IP——所有真实用户共享同一个值，会导致限流桶被
    全体用户共享（一个用户的正常浏览就能把全站打进限流）。
    优先级：CF-Connecting-IP > X-Forwarded-For 首个 > X-Real-IP > 连接对端。

    安全护栏：仅当 TRUST_PROXY_HEADERS=true（默认，线上在 Cloudflare 后）时才
    信任上述代理头；关闭时直接回退连接对端 IP，防止攻击者伪造头绕过限流。
    """
    if _trust_proxy_headers():
        cf_ip = str(request.headers.get("CF-Connecting-IP") or "").strip()
        if cf_ip:
            return cf_ip
        forwarded = str(request.headers.get("X-Forwarded-For") or "").strip()
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first
        real_ip = str(request.headers.get("X-Real-IP") or "").strip()
        if real_ip:
            return real_ip
    # 不信任代理头（或头缺失）：用真实连接对端 IP，攻击者无法靠换头绕过限流。
    return request.client.host if request.client else "anonymous"

async def security_gate(request: Request, call_next):
    if _is_allowlisted_path(request.url.path):
        return await call_next(request)

    api_key = None
    if _env_bool("API_AUTH_ENABLED", "false"):
        keys = _parse_api_keys()
        if not keys:
            return JSONResponse(status_code=503, content={"detail": "API auth enabled but no keys configured"})
        api_key = _extract_api_key(request)
        if not api_key or api_key not in keys:
            if request.url.path.startswith("/diagnostics/rag"):
                try:
                    user_identity = _require_rag_read_access(request)
                    request.state.rag_authenticated_user = user_identity
                except HTTPException as exc:
                    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
            else:
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

    # 解析客户端标识（限流 + 并发限制共用）——必须用真实 IP（Cloudflare/代理感知）
    request_identity = getattr(request.state, "rag_authenticated_user", None)
    if isinstance(request_identity, dict) and request_identity.get("user_id"):
        client_id = f"user:{request_identity['user_id']}"
    else:
        client_id = api_key or _resolve_client_ip(request)

    if _rate_limiter.enabled:
        allowed, retry_after = _rate_limiter.allow(client_id)
        if not allowed:
            headers = {"Retry-After": str(retry_after)}
            return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"}, headers=headers)

    # P1-6: 昂贵生成端点（Chat/报告执行）施加并发上限，防止少量长连接打满后端
    if _concurrency_limiter.enabled and is_generation_path(request.url.path):
        if not _concurrency_limiter.try_acquire(client_id):
            return JSONResponse(
                status_code=429,
                content={"detail": "并发请求数已达上限，请等待当前任务完成后再试"},
                headers={"Retry-After": "15"},
            )
        try:
            response = await call_next(request)
        except Exception:
            _concurrency_limiter.release(client_id)
            raise

        # 流式响应（SSE）：在 body 迭代完成后才释放并发槽
        body_iterator = getattr(response, "body_iterator", None)
        if body_iterator is not None:
            async def _release_after_stream(iterator=body_iterator, cid=client_id):
                try:
                    async for chunk in iterator:
                        yield chunk
                finally:
                    _concurrency_limiter.release(cid)

            response.body_iterator = _release_after_stream()
        else:
            _concurrency_limiter.release(client_id)
        return response

    return await call_next(request)

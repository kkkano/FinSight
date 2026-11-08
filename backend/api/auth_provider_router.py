"""登录页只读能力：从实际Supabase配置判断入口，不暴露provider凭据。"""
from __future__ import annotations

import asyncio
import time
import httpx
from fastapi import APIRouter

from backend.config.settings import security_settings

router = APIRouter(prefix="/api/auth", tags=["Authentication capabilities"])
_cache: tuple[tuple[str, str], float, dict] | None = None
_lock = asyncio.Lock()


@router.get("/providers")
async def auth_providers() -> dict:
    global _cache
    settings = security_settings()
    url = str(settings.supabase_url or settings.vite_supabase_url or "").rstrip("/")
    key = str(settings.supabase_publishable_key or settings.vite_supabase_publishable_key or "")
    identity = (url, key)
    if _cache and _cache[0] == identity and _cache[1] > time.monotonic():
        return dict(_cache[2])
    async with _lock:
        if _cache and _cache[0] == identity and _cache[1] > time.monotonic():
            return dict(_cache[2])
        result = {"github": False, "email": False, "status": "unconfigured"}
        if url and key:
            result["status"] = "unavailable"
            try:
                async with httpx.AsyncClient(timeout=6, follow_redirects=False) as client:
                    response = await client.get(url + "/auth/v1/settings", headers={"apikey": key})
                    response.raise_for_status()
                    external = response.json().get("external", {})
                    result = {"github": external.get("github") is True, "email": external.get("email") is True, "status": "ok"}
            except (httpx.HTTPError, ValueError, AttributeError):
                pass
        _cache = (identity, time.monotonic() + (60 if result["status"] == "ok" else 10), result)
        return dict(result)

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter


@dataclass(frozen=True)
class UserRouterDeps:
    memory_service: Any
    user_profile_cls: Any


def create_user_router(deps: UserRouterDeps) -> APIRouter:
    router = APIRouter(tags=["User"])

    @router.get("/api/user/profile")
    async def get_user_profile(user_id: str = "default_user"):
        if not deps.memory_service:
            return {"error": "MemoryService not initialized"}

        try:
            profile = deps.memory_service.get_user_profile(user_id)
            return {"success": True, "profile": profile.to_dict()}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @router.post("/api/user/profile")
    async def update_user_profile(request: dict):
        if not deps.memory_service:
            return {"error": "MemoryService not initialized"}

        try:
            user_id = request.get("user_id", "default_user")
            profile_data = request.get("profile", {})
            profile_data["user_id"] = user_id

            profile = deps.user_profile_cls.from_dict(profile_data)
            success = deps.memory_service.update_user_profile(profile)
            return {"success": success}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @router.post("/api/user/watchlist/add")
    async def add_watchlist(request: dict):
        if not deps.memory_service:
            return {"error": "MemoryService not initialized"}

        try:
            user_id = request.get("user_id", "default_user")
            ticker = request.get("ticker")
            if not ticker:
                return {"success": False, "error": "Ticker is required"}

            success = deps.memory_service.add_to_watchlist(user_id, ticker)
            return {"success": success}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    @router.post("/api/user/watchlist/remove")
    async def remove_watchlist(request: dict):
        if not deps.memory_service:
            return {"error": "MemoryService not initialized"}

        try:
            user_id = request.get("user_id", "default_user")
            ticker = request.get("ticker")
            if not ticker:
                return {"success": False, "error": "Ticker is required"}

            success = deps.memory_service.remove_from_watchlist(user_id, ticker)
            return {"success": success}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    return router


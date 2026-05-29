# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query


def create_skills_router() -> APIRouter:
    router = APIRouter(tags=["Skills"])

    @router.get("/api/skills")
    async def list_skills(
        query: str = Query("", description="Filter skills by name or description substring"),
        limit: int = Query(20, description="Max items", ge=1, le=50),
    ) -> dict[str, Any]:
        from backend.skills.registry import get_builtin_skill_registry

        registry = get_builtin_skill_registry()
        q = str(query or "").strip().lower()
        items: list[dict[str, Any]] = []
        for manifest in registry.all():
            if (
                q
                and q not in manifest.name.lower()
                and q not in manifest.description.lower()
                and q not in manifest.display_name.lower()
            ):
                continue
            items.append({
                "name": manifest.name,
                "display_name": manifest.display_name or manifest.name,
                "category": manifest.category,
                "description": manifest.description,
                "risk_level": manifest.risk_level,
                "required_facets": dict(manifest.required_facets),
                "preferred_tools": list(manifest.preferred_tools),
                "preferred_agents": list(manifest.preferred_agents),
                "optional_python_operations": list(manifest.optional_python_operations),
                "budget": dict(manifest.budget),
                "insert_text": f"/skill {manifest.name} ",
            })
            if len(items) >= limit:
                break
        return {"success": True, "query": q, "count": len(items), "items": items}

    return router

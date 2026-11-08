"""公开的研究技能目录，仅展示已安装技能的名称和用途。"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from backend.agent_runtime.skills import skill_catalog


class SkillCatalogEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str
    category: str


class SkillCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    skills: list[SkillCatalogEntry]


def create_skill_router() -> APIRouter:
    router = APIRouter(prefix="/api/skills", tags=["Skills"])

    @router.get("", response_model=SkillCatalogResponse)
    async def list_skills() -> dict:
        return {"skills": skill_catalog()}

    return router

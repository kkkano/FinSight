# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class A2ASkill(BaseModel):
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)


class A2AAgentCard(BaseModel):
    name: str
    description: str
    url: str = ""
    version: str = "0.1.0"
    enabled: bool = False
    capabilities: dict[str, Any] = Field(default_factory=dict)
    defaultInputModes: list[str] = Field(default_factory=list)
    defaultOutputModes: list[str] = Field(default_factory=list)
    skills: list[A2ASkill] = Field(default_factory=list)


class A2ATaskRecord(BaseModel):
    task_id: str
    status: str
    execute_request: dict[str, Any] = Field(default_factory=dict)
    artifacts: dict[str, Any] = Field(default_factory=dict)


__all__ = ["A2AAgentCard", "A2ASkill", "A2ATaskRecord"]

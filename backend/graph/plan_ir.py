# -*- coding: utf-8 -*-
"""
PlanIR schema + validation helpers (SSOT):
docs/06_LANGGRAPH_REFACTOR_GUIDE.md
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class PlanBudget(BaseModel):
    max_rounds: int = Field(ge=0, le=50)
    max_tools: int = Field(ge=0, le=50)

    model_config = {"extra": "forbid"}


class PlanSynthesis(BaseModel):
    style: Literal["concise", "structured"] = "concise"
    sections: list[str] = Field(default_factory=list)

    model_config = {"extra": "forbid"}


class PlanStep(BaseModel):
    id: str = Field(min_length=1)
    kind: Literal["tool", "agent", "llm"]
    name: str = Field(min_length=1)
    inputs: dict[str, Any] = Field(default_factory=dict)
    parallel_group: Optional[str] = None
    why: Optional[str] = None
    optional: bool = False

    model_config = {"extra": "forbid"}


class PlanSubject(BaseModel):
    subject_type: str = Field(min_length=1)
    tickers: list[str] = Field(default_factory=list)
    selection_ids: list[str] = Field(default_factory=list)
    selection_types: list[str] = Field(default_factory=list)
    selection_payload: list[dict] = Field(default_factory=list)
    binding_tier: str = Field(default="none")

    model_config = {"extra": "forbid"}


class PlanIR(BaseModel):
    goal: str = Field(min_length=1)
    subject: PlanSubject
    output_mode: Literal["chat", "brief", "investment_report"]
    steps: list[PlanStep] = Field(default_factory=list)
    synthesis: PlanSynthesis = Field(default_factory=PlanSynthesis)
    budget: PlanBudget

    model_config = {"extra": "forbid"}


def plan_ir_json_schema() -> dict[str, Any]:
    return PlanIR.model_json_schema()


def validate_plan_ir(payload: Any) -> PlanIR:
    return PlanIR.model_validate(payload)


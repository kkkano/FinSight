# -*- coding: utf-8 -*-
"""
Rebalance suggestion Pydantic schemas (Gate-6 + P3-6a).

Hard constraint HC-2: ``executable`` is always ``Literal[False]``,
``mode`` is always ``Literal["suggestion_only"]``.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"
    REDUCE = "reduce"
    INCREASE = "increase"


class RiskTier(str, Enum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class EvidenceSnapshot(BaseModel):
    """Immutable evidence captured at suggestion-generation time."""

    evidence_id: str
    source: str
    quote: str = Field(default="", max_length=200)
    report_id: str = ""
    captured_at: str = ""


class RebalanceConstraints(BaseModel):
    max_single_position_pct: float = Field(default=25.0, ge=1, le=100)
    max_turnover_pct: float = Field(default=30.0, ge=0, le=100)
    sector_concentration_limit: float = Field(default=40.0, ge=0, le=100)
    min_action_delta_pct: float = Field(default=1.0, ge=0)


class RebalanceAction(BaseModel):
    ticker: str
    action: ActionType
    current_weight: float
    target_weight: float
    delta_weight: float
    reason: str = ""
    priority: int = Field(default=3, ge=1, le=5)
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_snapshots: list[EvidenceSnapshot] = Field(default_factory=list)


class ExpectedImpact(BaseModel):
    diversification_delta: str = ""
    risk_delta: str = ""
    estimated_turnover_pct: float = 0.0


class RebalanceSuggestion(BaseModel):
    suggestion_id: str
    mode: Literal["suggestion_only"] = "suggestion_only"
    executable: Literal[False] = False
    risk_tier: RiskTier = RiskTier.MODERATE
    constraints: RebalanceConstraints = Field(default_factory=RebalanceConstraints)
    summary: str = ""
    actions: list[RebalanceAction] = Field(default_factory=list)
    expected_impact: ExpectedImpact = Field(default_factory=ExpectedImpact)
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str = "本建议仅供参考，不构成投资建议。请结合自身情况独立判断。"
    status: Literal["draft", "viewed", "dismissed", "sent_to_chat"] = "draft"
    created_at: str = ""
    degraded_mode: bool = False
    fallback_reason: str | None = None


class GenerateRebalanceRequest(BaseModel):
    session_id: str
    portfolio: list[dict] = Field(default_factory=list)
    risk_tier: RiskTier = RiskTier.MODERATE
    constraints: RebalanceConstraints = Field(default_factory=RebalanceConstraints)
    use_llm_enhancement: bool = False


class PatchSuggestionRequest(BaseModel):
    status: Literal["viewed", "dismissed", "sent_to_chat"]


__all__ = [
    "ActionType",
    "RiskTier",
    "EvidenceSnapshot",
    "RebalanceConstraints",
    "RebalanceAction",
    "ExpectedImpact",
    "RebalanceSuggestion",
    "GenerateRebalanceRequest",
    "PatchSuggestionRequest",
]

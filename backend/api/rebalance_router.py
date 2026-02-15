# -*- coding: utf-8 -*-
"""Rebalance suggestion API router.

Uses factory + DI pattern consistent with execution_router.py.
HC-2: all suggestions are non-executable (suggestion_only mode).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException

from backend.api.rebalance_schemas import (
    GenerateRebalanceRequest,
    PatchSuggestionRequest,
    RebalanceSuggestion,
)
from backend.services.portfolio_store import (
    get_positions,
    list_suggestions,
    patch_suggestion,
    save_suggestion,
)
from backend.services.rebalance_engine import RebalanceContext, RebalanceEngine

logger = logging.getLogger(__name__)


# ── Dependency injection ────────────────────────────────────


@dataclass(frozen=True)
class RebalanceRouterDeps:
    """Injected from main.py."""

    rebalance_engine: Any  # RebalanceEngine instance


# ── Router factory ──────────────────────────────────────────


def create_rebalance_router(deps: RebalanceRouterDeps) -> APIRouter:
    """Create and return the rebalance suggestion router."""
    router = APIRouter(tags=["Rebalance"])

    @router.post(
        "/api/rebalance/suggestions/generate",
        response_model=RebalanceSuggestion,
    )
    async def generate_suggestion(request: GenerateRebalanceRequest):
        """Generate a rebalance suggestion for the portfolio.

        HC-2: Forces suggestion_only mode and executable=False.
        """
        if not request.session_id:
            raise HTTPException(status_code=422, detail="session_id is required")

        # Build portfolio from request or fetch from store
        portfolio = request.portfolio
        if not portfolio:
            portfolio = get_positions(request.session_id)

        if not portfolio:
            raise HTTPException(
                status_code=400,
                detail="No portfolio positions found. Add positions first.",
            )

        ctx = RebalanceContext(
            session_id=request.session_id,
            portfolio=portfolio,
            risk_tier=request.risk_tier,
            constraints=request.constraints,
        )

        try:
            suggestion = await deps.rebalance_engine.generate(ctx)
        except Exception as exc:
            logger.exception("Rebalance engine failed: %s", exc)
            raise HTTPException(
                status_code=500, detail="Failed to generate rebalance suggestion"
            ) from exc

        # Persist to portfolio store
        try:
            save_suggestion(
                suggestion_id=suggestion.suggestion_id,
                session_id=request.session_id,
                data=suggestion.model_dump(),
            )
        except Exception as exc:
            logger.exception("Failed to save suggestion: %s", exc)
            # Non-fatal: return the suggestion even if persistence fails

        return suggestion

    @router.get("/api/rebalance/suggestions")
    async def list_suggestions_endpoint(
        session_id: str, limit: int = 10
    ):
        """List recent rebalance suggestions for a session."""
        if not session_id:
            raise HTTPException(status_code=422, detail="session_id is required")

        results = list_suggestions(session_id, limit=min(limit, 50))
        return {
            "success": True,
            "session_id": session_id,
            "suggestions": results,
            "count": len(results),
        }

    @router.patch("/api/rebalance/suggestions/{suggestion_id}")
    async def patch_suggestion_endpoint(
        suggestion_id: str, request: PatchSuggestionRequest
    ):
        """Update the status of a rebalance suggestion."""
        if not suggestion_id:
            raise HTTPException(status_code=422, detail="suggestion_id is required")

        updated = patch_suggestion(suggestion_id, status=request.status)
        if not updated:
            raise HTTPException(status_code=404, detail="Suggestion not found")

        return {
            "success": True,
            "suggestion_id": suggestion_id,
            "status": request.status,
        }

    return router


__all__ = ["RebalanceRouterDeps", "create_rebalance_router"]

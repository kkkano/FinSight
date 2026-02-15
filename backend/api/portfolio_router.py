# -*- coding: utf-8 -*-
"""Portfolio position management router.

CRUD operations for portfolio positions stored in the independent
portfolio.db (Gate-5). Supports sync (bulk replace), upsert, and delete.
"""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.services.portfolio_store import (
    get_positions,
    remove_position,
    sync_positions,
    update_position,
)

logger = logging.getLogger(__name__)

portfolio_router = APIRouter(tags=["Portfolio"])


# ── Request schemas ─────────────────────────────────────────


class SyncPositionsRequest(BaseModel):
    """Bulk-replace all positions for a session."""

    session_id: str
    positions: list[dict[str, Any]] = Field(default_factory=list)


class UpdatePositionRequest(BaseModel):
    """Upsert a single position."""

    shares: float = Field(..., ge=0)
    avg_cost: float | None = None


# ── Endpoints ───────────────────────────────────────────────


@portfolio_router.get("/api/portfolio/summary")
async def get_portfolio_summary(session_id: str):
    """Return all positions with calculated market values.

    Uses stored positions from portfolio_store. Live price
    enrichment is optional (falls back to avg_cost if unavailable).
    """
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")

    positions = get_positions(session_id)

    # Compute summary metrics
    total_value = 0.0
    total_cost = 0.0
    enriched: list[dict[str, Any]] = []

    for pos in positions:
        shares = float(pos.get("shares", 0))
        avg_cost = pos.get("avg_cost")

        # Use avg_cost as fallback price when live prices are unavailable
        estimated_price = float(avg_cost) if avg_cost else 0.0
        market_value = shares * estimated_price
        cost_basis = shares * (float(avg_cost) if avg_cost else 0.0)
        pnl = market_value - cost_basis

        enriched.append({
            **pos,
            "market_value": round(market_value, 2),
            "cost_basis": round(cost_basis, 2),
            "unrealized_pnl": round(pnl, 2),
        })

        total_value += market_value
        total_cost += cost_basis

    return {
        "success": True,
        "session_id": session_id,
        "positions": enriched,
        "count": len(enriched),
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_value - total_cost, 2),
    }


@portfolio_router.post("/api/portfolio/positions")
async def sync_positions_endpoint(request: SyncPositionsRequest):
    """Bulk-replace all positions for a session."""
    if not request.session_id:
        raise HTTPException(status_code=422, detail="session_id is required")

    count = sync_positions(request.session_id, request.positions)
    return {
        "success": True,
        "session_id": request.session_id,
        "synced_count": count,
    }


@portfolio_router.put("/api/portfolio/positions/{ticker}")
async def update_position_endpoint(
    ticker: str,
    session_id: str,
    request: UpdatePositionRequest,
):
    """Upsert a single position (create or update)."""
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")

    clean_ticker = ticker.strip().upper()
    if not clean_ticker:
        raise HTTPException(status_code=422, detail="ticker is required")

    update_position(
        session_id=session_id,
        ticker=clean_ticker,
        shares=request.shares,
        avg_cost=request.avg_cost,
    )
    return {
        "success": True,
        "session_id": session_id,
        "ticker": clean_ticker,
        "shares": request.shares,
        "avg_cost": request.avg_cost,
    }


@portfolio_router.delete("/api/portfolio/positions/{ticker}")
async def remove_position_endpoint(ticker: str, session_id: str):
    """Remove a single position from the portfolio."""
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")

    clean_ticker = ticker.strip().upper()
    if not clean_ticker:
        raise HTTPException(status_code=422, detail="ticker is required")

    remove_position(session_id=session_id, ticker=clean_ticker)
    return {
        "success": True,
        "session_id": session_id,
        "removed_ticker": clean_ticker,
    }


__all__ = ["portfolio_router"]

# -*- coding: utf-8 -*-
"""Portfolio position management router.

CRUD operations for positions stored in independent ``portfolio.db``.
"""

from __future__ import annotations

import asyncio
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
from backend.tools import get_stock_price
from backend.utils.quote import resolve_live_quote, safe_float

logger = logging.getLogger(__name__)

portfolio_router = APIRouter(tags=["Portfolio"])


class SyncPositionsRequest(BaseModel):
    """Bulk-replace all positions for a session."""

    session_id: str
    positions: list[dict[str, Any]] = Field(default_factory=list)


class UpdatePositionRequest(BaseModel):
    """Upsert a single position."""

    shares: float = Field(..., ge=0)
    avg_cost: float | None = None


@portfolio_router.get("/api/portfolio/summary")
async def get_portfolio_summary(session_id: str):
    """Return all positions with calculated market values."""
    if not session_id:
        raise HTTPException(status_code=422, detail="session_id is required")

    positions = get_positions(session_id)

    total_value = 0.0
    total_cost = 0.0
    total_day_change = 0.0
    priced_positions = 0
    enriched: list[dict[str, Any]] = []

    quote_tasks = [
        asyncio.to_thread(
            resolve_live_quote,
            str(pos.get("ticker", "")).strip().upper(),
            get_stock_price,
        )
        for pos in positions
    ]
    live_quotes = await asyncio.gather(*quote_tasks) if quote_tasks else []

    for pos, quote_result in zip(positions, live_quotes):
        quote = quote_result[0] if isinstance(quote_result, tuple) else None
        shares = float(pos.get("shares", 0))
        avg_cost = safe_float(pos.get("avg_cost"))
        live_price = safe_float((quote or {}).get("price")) if quote else None
        live_change = safe_float((quote or {}).get("change")) if quote else None
        live_change_pct = safe_float((quote or {}).get("change_percent")) if quote else None

        if live_price is not None:
            used_price = live_price
            price_source = str((quote or {}).get("source") or "live")
            priced_positions += 1
        elif avg_cost is not None:
            used_price = avg_cost
            price_source = "avg_cost_fallback"
        else:
            used_price = 0.0
            price_source = "unavailable"

        market_value = shares * used_price
        cost_basis = shares * (avg_cost or 0.0)
        unrealized_pnl = (market_value - cost_basis) if avg_cost is not None else None
        day_change = (shares * live_change) if live_change is not None else None

        enriched.append(
            {
                **pos,
                "live_price": round(live_price, 6) if live_price is not None else None,
                "live_change": round(live_change, 6) if live_change is not None else None,
                "live_change_percent": round(live_change_pct, 6) if live_change_pct is not None else None,
                "price_source": price_source,
                "market_value": round(market_value, 2),
                "cost_basis": round(cost_basis, 2),
                "unrealized_pnl": round(unrealized_pnl, 2) if unrealized_pnl is not None else None,
                "day_change": round(day_change, 2) if day_change is not None else None,
            }
        )

        total_value += market_value
        total_cost += cost_basis
        total_day_change += day_change or 0.0

    return {
        "success": True,
        "session_id": session_id,
        "positions": enriched,
        "count": len(enriched),
        "priced_count": priced_positions,
        "total_value": round(total_value, 2),
        "total_cost": round(total_cost, 2),
        "total_pnl": round(total_value - total_cost, 2),
        "total_day_change": round(total_day_change, 2),
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


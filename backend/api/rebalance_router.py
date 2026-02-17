# -*- coding: utf-8 -*-
"""Rebalance suggestion API router.

Uses factory + DI pattern consistent with execution_router.py.
HC-2: all suggestions are non-executable (suggestion_only mode).
"""
from __future__ import annotations

import asyncio
import logging
import re
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
from backend.utils.quote import parse_quote_payload, safe_float

logger = logging.getLogger(__name__)


# ── Dependency injection ────────────────────────────────────


@dataclass(frozen=True)
class RebalanceRouterDeps:
    """Injected from main.py."""

    rebalance_engine: Any  # RebalanceEngine instance
    get_stock_price: Any | None = None
    get_company_info: Any | None = None


def _extract_sector(raw: Any) -> str | None:
    if isinstance(raw, dict):
        for key in ("sector", "finnhubIndustry", "industry"):
            value = str(raw.get(key) or "").strip()
            if value:
                return value
        return None
    text = str(raw or "")
    if not text:
        return None
    match = re.search(r"(?im)^\s*-\s*Sector\s*:\s*(.+?)\s*$", text)
    if match:
        return match.group(1).strip()
    return None


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

        tickers = sorted(
            {
                str(item.get("ticker", "")).strip().upper()
                for item in portfolio
                if str(item.get("ticker", "")).strip()
            }
        )

        async def _fetch_live_price(ticker: str) -> tuple[str, float | None]:
            if deps.get_stock_price is None:
                return ticker, None
            try:
                raw_payload = await asyncio.to_thread(deps.get_stock_price, ticker)
                parsed = parse_quote_payload(raw_payload) or {}
                price = safe_float(parsed.get("price"))
                if price is None or price <= 0:
                    return ticker, None
                return ticker, price
            except Exception as exc:
                logger.warning("[rebalance] failed to load live price for %s: %s", ticker, exc)
                return ticker, None

        price_pairs = await asyncio.gather(*[_fetch_live_price(ticker) for ticker in tickers])
        live_prices = {ticker: price for ticker, price in price_pairs if price is not None}

        sector_map: dict[str, str] = {}
        for item in portfolio:
            ticker = str(item.get("ticker", "")).strip().upper()
            if not ticker:
                continue
            direct_sector = str(item.get("sector", "")).strip()
            if direct_sector:
                sector_map[ticker] = direct_sector

        missing_sector_tickers = [ticker for ticker in tickers if ticker not in sector_map]

        async def _fetch_sector(ticker: str) -> tuple[str, str | None]:
            if deps.get_company_info is None:
                return ticker, None
            try:
                info = await asyncio.to_thread(deps.get_company_info, ticker)
                return ticker, _extract_sector(info)
            except Exception as exc:
                logger.warning("[rebalance] failed to load sector for %s: %s", ticker, exc)
                return ticker, None

        if missing_sector_tickers:
            sector_pairs = await asyncio.gather(*[_fetch_sector(ticker) for ticker in missing_sector_tickers])
            for ticker, sector in sector_pairs:
                if sector:
                    sector_map[ticker] = sector

        missing_price_tickers = [ticker for ticker in tickers if ticker not in live_prices]
        missing_sector_tickers = [ticker for ticker in tickers if ticker not in sector_map]
        fallback_reasons: list[str] = []
        if missing_price_tickers:
            fallback_reasons.append(f"missing_live_prices:{','.join(missing_price_tickers)}")
        if missing_sector_tickers:
            fallback_reasons.append(f"missing_sector_map:{','.join(missing_sector_tickers)}")
        diagnostics_only = len(fallback_reasons) > 0

        ctx = RebalanceContext(
            session_id=request.session_id,
            portfolio=portfolio,
            risk_tier=request.risk_tier,
            constraints=request.constraints,
            live_prices=live_prices,
            sector_map=sector_map,
            diagnostics_only=diagnostics_only,
            fallback_reasons=fallback_reasons,
            use_llm_enhancement=bool(request.use_llm_enhancement),
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

# -*- coding: utf-8 -*-
"""Rebalance suggestion API router.

Uses factory + DI pattern consistent with execution_router.py.
HC-2: all suggestions are non-executable (suggestion_only mode).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

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

    @router.post("/api/rebalance/suggestions/generate-stream")
    async def generate_suggestion_stream(request: GenerateRebalanceRequest):
        """SSE streaming rebalance suggestion generation (P2).

        Streams progress events during diagnosis/generation/solving steps,
        then emits the final suggestion. HC-2 enforced.
        """
        if not request.session_id:
            raise HTTPException(status_code=422, detail="session_id is required")

        async def _event_stream():
            started_at = time.perf_counter()

            def _sse(event_type: str, data: dict) -> str:
                payload = json.dumps(data, ensure_ascii=False)
                return f"event: {event_type}\ndata: {payload}\n\n"

            yield _sse("progress", {"stage": "init", "message": "正在初始化调仓分析..."})

            # Build portfolio
            portfolio = request.portfolio
            if not portfolio:
                portfolio = get_positions(request.session_id)

            if not portfolio:
                yield _sse("error", {"message": "未找到持仓数据，请先添加持仓。"})
                return

            tickers = sorted(
                {
                    str(item.get("ticker", "")).strip().upper()
                    for item in portfolio
                    if str(item.get("ticker", "")).strip()
                }
            )

            yield _sse("progress", {
                "stage": "fetching_prices",
                "message": f"正在获取 {len(tickers)} 只标的实时价格...",
                "ticker_count": len(tickers),
            })

            # Fetch prices
            async def _fetch_live_price(ticker: str) -> tuple[str, float | None]:
                if deps.get_stock_price is None:
                    return ticker, None
                try:
                    raw_payload = await asyncio.to_thread(deps.get_stock_price, ticker)
                    parsed = parse_quote_payload(raw_payload) or {}
                    price = safe_float(parsed.get("price"))
                    return ticker, price if price and price > 0 else None
                except Exception:
                    return ticker, None

            price_pairs = await asyncio.gather(*[_fetch_live_price(t) for t in tickers])
            live_prices = {t: p for t, p in price_pairs if p is not None}

            yield _sse("progress", {
                "stage": "fetching_sectors",
                "message": "正在获取行业分类信息...",
                "priced_count": len(live_prices),
            })

            # Fetch sectors
            sector_map: dict[str, str] = {}
            for item in portfolio:
                ticker = str(item.get("ticker", "")).strip().upper()
                direct_sector = str(item.get("sector", "")).strip()
                if ticker and direct_sector:
                    sector_map[ticker] = direct_sector

            missing_sector_tickers = [t for t in tickers if t not in sector_map]
            if missing_sector_tickers and deps.get_company_info:
                async def _fetch_sector(ticker: str) -> tuple[str, str | None]:
                    try:
                        info = await asyncio.to_thread(deps.get_company_info, ticker)
                        return ticker, _extract_sector(info)
                    except Exception:
                        return ticker, None

                sector_pairs = await asyncio.gather(*[_fetch_sector(t) for t in missing_sector_tickers])
                for t, s in sector_pairs:
                    if s:
                        sector_map[t] = s

            yield _sse("progress", {"stage": "diagnosing", "message": "正在诊断持仓风险..."})

            # Build context
            missing_prices = [t for t in tickers if t not in live_prices]
            missing_sectors = [t for t in tickers if t not in sector_map]
            fallback_reasons: list[str] = []
            if missing_prices:
                fallback_reasons.append(f"missing_live_prices:{','.join(missing_prices)}")
            if missing_sectors:
                fallback_reasons.append(f"missing_sector_map:{','.join(missing_sectors)}")

            ctx = RebalanceContext(
                session_id=request.session_id,
                portfolio=portfolio,
                risk_tier=request.risk_tier,
                constraints=request.constraints,
                live_prices=live_prices,
                sector_map=sector_map,
                diagnostics_only=len(fallback_reasons) > 0,
                fallback_reasons=fallback_reasons,
                use_llm_enhancement=bool(request.use_llm_enhancement),
            )

            yield _sse("progress", {"stage": "generating", "message": "正在生成调仓建议..."})

            try:
                suggestion = await deps.rebalance_engine.generate(ctx)
            except Exception as exc:
                logger.exception("Rebalance engine failed: %s", exc)
                yield _sse("error", {"message": "调仓建议生成失败，请稍后重试。"})
                return

            # Persist
            try:
                save_suggestion(
                    suggestion_id=suggestion.suggestion_id,
                    session_id=request.session_id,
                    data=suggestion.model_dump(),
                )
            except Exception as exc:
                logger.warning("Failed to save suggestion: %s", exc)

            elapsed_ms = int((time.perf_counter() - started_at) * 1000)
            yield _sse("progress", {
                "stage": "done",
                "message": "调仓建议生成完成",
                "duration_ms": elapsed_ms,
            })

            yield _sse("result", suggestion.model_dump())

        return StreamingResponse(
            _event_stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return router


__all__ = ["RebalanceRouterDeps", "create_rebalance_router"]

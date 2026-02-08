from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from backend.api.schemas import KlineResponse


@dataclass(frozen=True)
class MarketRouterDeps:
    get_orchestrator_safe: Callable[[], Any]
    get_stock_price: Callable[[str], Any]
    get_company_news: Callable[[str], Any]
    get_financial_statements: Callable[[str], Any]
    get_financial_statements_summary: Callable[[str], Any]
    get_stock_historical_data: Callable[..., Any]
    logger: Any


def create_market_router(deps: MarketRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Market"])

    @router.get("/api/stock/price/{ticker}")
    def get_price(ticker: str):
        try:
            orchestrator = deps.get_orchestrator_safe()
            if orchestrator:
                cache_key = f"price:{ticker}"
                cached_data = orchestrator.cache.get(cache_key)
                if cached_data is not None:
                    deps.logger.info("[API] price cache hit %s", ticker)
                    return {"ticker": ticker, "data": cached_data, "cached": True}

            price_info = deps.get_stock_price(ticker)
            if orchestrator and price_info:
                orchestrator.cache.set(f"price:{ticker}", price_info, ttl=60)
            return {"ticker": ticker, "data": price_info}
        except Exception as exc:
            return {"error": str(exc)}

    @router.get("/api/stock/news/{ticker}")
    def get_news(ticker: str):
        try:
            news = deps.get_company_news(ticker)
            return {"ticker": ticker, "data": news}
        except Exception as exc:
            return {"error": str(exc)}

    @router.get("/api/financials/{ticker}")
    def get_financials(ticker: str):
        try:
            financials_data = deps.get_financial_statements(ticker)
            return financials_data
        except Exception as exc:
            return {"ticker": ticker, "error": str(exc)}

    @router.get("/api/financials/{ticker}/summary")
    def get_financials_summary(ticker: str):
        try:
            summary = deps.get_financial_statements_summary(ticker)
            return {"ticker": ticker, "summary": summary}
        except Exception as exc:
            return {"ticker": ticker, "error": str(exc)}

    @router.get("/api/stock/kline/{ticker}", response_model=KlineResponse)
    def get_kline_data(ticker: str, period: str = "1y", interval: str = "1d"):
        try:
            orchestrator = deps.get_orchestrator_safe()
            if orchestrator:
                cache_key = f"kline:{ticker}:{period}:{interval}"
                cached_data = orchestrator.cache.get(cache_key)
                if cached_data is not None:
                    deps.logger.info("[API] kline cache hit %s (%s,%s)", ticker, period, interval)
                    return {"ticker": ticker, "data": cached_data, "cached": True}

            kline_data = deps.get_stock_historical_data(ticker, period=period, interval=interval)
            if "error" not in kline_data and orchestrator:
                cache_key = f"kline:{ticker}:{period}:{interval}"
                orchestrator.cache.set(cache_key, kline_data, ttl=3600)

            return {"ticker": ticker, "data": kline_data, "cached": False}
        except Exception as exc:
            return {"ticker": ticker, "data": {"error": str(exc)}, "cached": False}

    @router.post("/api/export/pdf")
    async def export_pdf(request: dict):
        try:
            from datetime import datetime

            from fastapi.responses import Response

            from backend.services.pdf_export import get_pdf_service

            pdf_service = get_pdf_service()
            if not pdf_service:
                raise HTTPException(status_code=503, detail="PDF export service unavailable")

            messages = request.get("messages", [])
            charts = request.get("charts", [])
            title = request.get("title", "FinSight 对话记录")

            if not messages:
                raise HTTPException(status_code=400, detail="messages 不能为空")

            if charts:
                pdf_bytes = pdf_service.export_with_charts(messages, charts, title=title)
            else:
                pdf_bytes = pdf_service.export_conversation(messages, title=title)

            if not pdf_bytes:
                raise HTTPException(status_code=500, detail="PDF generation failed")

            return Response(
                content=pdf_bytes,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f"attachment; filename=finsight_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
                },
            )
        except HTTPException:
            raise
        except ImportError as exc:
            raise HTTPException(status_code=503, detail=f"PDF export unavailable: {str(exc)}") from exc
        except Exception as exc:
            traceback.print_exc()
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    return router


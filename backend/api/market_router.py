from __future__ import annotations

import re
import traceback
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import APIRouter, HTTPException

from backend.api.schemas import KlineResponse
from backend.utils.quote import parse_quote_payload, resolve_live_quote


@dataclass(frozen=True)
class MarketRouterDeps:
    get_orchestrator_safe: Callable[[], Any]
    get_stock_price: Callable[[str], Any]
    get_company_news: Callable[[str], Any]
    get_financial_statements: Callable[[str], Any]
    get_financial_statements_summary: Callable[[str], Any]
    get_stock_historical_data: Callable[..., Any]
    detect_chart_type: Callable[[str, str | None], dict[str, Any]] | None
    logger: Any


_TICKER_PATTERN = re.compile(r"^[A-Z0-9^][A-Z0-9.^=-]{0,19}$")


def _normalize_ticker(raw_ticker: str) -> str:
    return str(raw_ticker or "").strip().upper()


def _validate_ticker_or_400(raw_ticker: str) -> str:
    ticker = _normalize_ticker(raw_ticker)
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker 不能为空")
    if not _TICKER_PATTERN.fullmatch(ticker):
        raise HTTPException(status_code=400, detail=f"ticker 格式非法: {raw_ticker}")
    return ticker


def _extract_ticker_candidates(query: str, provided_ticker: str | None = None) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        ticker = _normalize_ticker(raw)
        if not ticker or ticker in seen:
            return
        if not _TICKER_PATTERN.fullmatch(ticker):
            return
        seen.add(ticker)
        candidates.append(ticker)

    if provided_ticker:
        _add(provided_ticker)

    try:
        from backend.config.ticker_mapping import extract_tickers as extract_tickers_from_query

        metadata = extract_tickers_from_query(query or "")
        for ticker in metadata.get("tickers") or []:
            _add(str(ticker))
    except Exception:
        pass

    return candidates

def create_market_router(deps: MarketRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Market"])

    @router.post("/api/chart/detect")
    def detect_chart(payload: dict[str, Any]):
        query = str(payload.get("query") or "").strip()
        ticker = payload.get("ticker")
        ticker_value = str(ticker).strip() if ticker is not None else None
        ticker_candidates = _extract_ticker_candidates(query, ticker_value)
        resolved_ticker = ticker_candidates[0] if ticker_candidates else None

        if not query:
            return {
                "success": False,
                "should_generate": False,
                "chart_type": None,
                "data_dimension": None,
                "confidence": 0.0,
                "reason": "empty_query",
                "ticker_candidates": ticker_candidates,
                "resolved_ticker": resolved_ticker,
            }

        if deps.detect_chart_type is None:
            return {
                "success": False,
                "should_generate": False,
                "chart_type": None,
                "data_dimension": None,
                "confidence": 0.0,
                "reason": "chart_detector_unavailable",
                "ticker_candidates": ticker_candidates,
                "resolved_ticker": resolved_ticker,
            }

        try:
            detected = deps.detect_chart_type(query, ticker_value or None)
            chart_type = detected.get("chart_type") if isinstance(detected, dict) else None
            data_dimension = detected.get("data_dimension") if isinstance(detected, dict) else None
            confidence_raw = detected.get("confidence") if isinstance(detected, dict) else 0.0
            try:
                confidence = float(confidence_raw)
            except Exception:
                confidence = 0.0
            confidence = max(0.0, min(1.0, confidence))
            reason = (
                str(detected.get("reason") or "")
                if isinstance(detected, dict)
                else "invalid_detector_response"
            )
            should_generate = bool(chart_type) and confidence >= 0.35
            return {
                "success": True,
                "should_generate": should_generate,
                "chart_type": chart_type,
                "data_dimension": data_dimension,
                "confidence": confidence,
                "reason": reason,
                "ticker_candidates": ticker_candidates,
                "resolved_ticker": resolved_ticker,
            }
        except Exception as exc:
            deps.logger.warning("[ChartDetect] failed: %s", exc)
            return {
                "success": False,
                "should_generate": False,
                "chart_type": None,
                "data_dimension": None,
                "confidence": 0.0,
                "reason": str(exc),
                "ticker_candidates": ticker_candidates,
                "resolved_ticker": resolved_ticker,
            }

    @router.get("/api/stock/price/{ticker}")
    def get_price(ticker: str):
        normalized_ticker = _validate_ticker_or_400(ticker)
        try:
            orchestrator = deps.get_orchestrator_safe()
            if orchestrator:
                cache_key = f"price:{normalized_ticker}"
                cached_data = orchestrator.cache.get(cache_key)
                if cached_data is not None:
                    deps.logger.info("[API] price cache hit %s", normalized_ticker)
                    normalized = parse_quote_payload(cached_data)
                    return {"ticker": normalized_ticker, "data": normalized or cached_data, "cached": True}

            quote, raw_payload = resolve_live_quote(normalized_ticker, deps.get_stock_price)
            if quote is not None:
                if orchestrator:
                    orchestrator.cache.set(f"price:{normalized_ticker}", quote, ttl=60)
                return {"ticker": normalized_ticker, "data": quote}

            if orchestrator and raw_payload:
                orchestrator.cache.set(f"price:{normalized_ticker}", raw_payload, ttl=60)
            return {"ticker": normalized_ticker, "data": raw_payload or {"error": "price unavailable"}}
        except Exception as exc:
            deps.logger.warning("[API] get_price failed for %s: %s", normalized_ticker, exc)
            raise HTTPException(status_code=502, detail=f"无法获取 {normalized_ticker} 价格数据") from exc

    @router.get("/api/stock/news/{ticker}")
    def get_news(ticker: str):
        normalized_ticker = _validate_ticker_or_400(ticker)
        try:
            news = deps.get_company_news(normalized_ticker)
            return {"ticker": normalized_ticker, "data": news}
        except Exception as exc:
            deps.logger.warning("[API] get_news failed for %s: %s", normalized_ticker, exc)
            raise HTTPException(status_code=502, detail=f"无法获取 {normalized_ticker} 新闻数据") from exc

    @router.get("/api/financials/{ticker}")
    def get_financials(ticker: str):
        normalized_ticker = _validate_ticker_or_400(ticker)
        try:
            financials_data = deps.get_financial_statements(normalized_ticker)
            return financials_data
        except Exception as exc:
            deps.logger.warning("[API] get_financials failed for %s: %s", normalized_ticker, exc)
            raise HTTPException(status_code=502, detail=f"无法获取 {normalized_ticker} 财务数据") from exc

    @router.get("/api/financials/{ticker}/summary")
    def get_financials_summary(ticker: str):
        normalized_ticker = _validate_ticker_or_400(ticker)
        try:
            summary = deps.get_financial_statements_summary(normalized_ticker)
            return {"ticker": normalized_ticker, "summary": summary}
        except Exception as exc:
            deps.logger.warning("[API] get_financials_summary failed for %s: %s", normalized_ticker, exc)
            raise HTTPException(status_code=502, detail=f"无法获取 {normalized_ticker} 财务摘要") from exc

    @router.get("/api/stock/kline/{ticker}", response_model=KlineResponse)
    def get_kline_data(ticker: str, period: str = "1y", interval: str = "1d"):
        normalized_ticker = _validate_ticker_or_400(ticker)
        try:
            orchestrator = deps.get_orchestrator_safe()
            if orchestrator:
                cache_key = f"kline:{normalized_ticker}:{period}:{interval}"
                cached_data = orchestrator.cache.get(cache_key)
                if cached_data is not None:
                    deps.logger.info("[API] kline cache hit %s (%s,%s)", normalized_ticker, period, interval)
                    return {"ticker": normalized_ticker, "data": cached_data, "cached": True}

            kline_data = deps.get_stock_historical_data(normalized_ticker, period=period, interval=interval)
            if "error" not in kline_data and orchestrator:
                cache_key = f"kline:{normalized_ticker}:{period}:{interval}"
                orchestrator.cache.set(cache_key, kline_data, ttl=3600)

            return {"ticker": normalized_ticker, "data": kline_data, "cached": False}
        except Exception as exc:
            return {"ticker": normalized_ticker, "data": {"error": str(exc)}, "cached": False}

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

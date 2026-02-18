from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Query

from backend.services.task_generator import TaskContext, TaskGenerator
from backend.utils.quote import parse_quote_payload, safe_float

logger = logging.getLogger(__name__)

_task_generator = TaskGenerator()


@dataclass(frozen=True)
class TaskRouterDeps:
    resolve_thread_id: Callable[[Optional[str]], str]
    get_report_index_store: Callable[[], Any]
    get_portfolio_positions: Callable[[str], list[dict[str, Any]]]
    get_stock_price: Callable[[str], Any]


def create_task_router(deps: TaskRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Tasks"])

    @router.get("/api/tasks/daily")
    async def get_daily_tasks(
        session_id: str,
        risk_preference: str = "balanced",
        news_count: int = 0,  # reserved for future weighting
        watchlist: str = Query("", description="Comma-separated ticker list"),
    ):
        try:
            normalized_session = deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        store = deps.get_report_index_store()
        reports = store.list_reports(session_id=normalized_session, limit=20)

        report_tickers = {str(item["ticker"]).strip().upper() for item in reports if item.get("ticker")}
        extra_tickers = {value.strip().upper() for value in (watchlist or "").split(",") if value.strip()}
        merged_watchlist = sorted(report_tickers | extra_tickers)

        recent_reports: dict[str, dict[str, Any]] = {}
        for report in reports:
            ticker = str(report.get("ticker", "")).strip().upper()
            if not ticker:
                continue

            generated_at = report.get("generated_at") or report.get("created_at", "")
            age_days = 999
            if generated_at:
                try:
                    generated_dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
                    age_days = (datetime.now(timezone.utc) - generated_dt).days
                except Exception:
                    pass

            recent_reports[ticker] = {
                "report_id": report.get("report_id", ""),
                "age_days": age_days,
                "confidence_score": report.get("confidence_score"),
            }

        try:
            stored_positions = deps.get_portfolio_positions(normalized_session) or []
        except Exception as exc:
            logger.warning("[Tasks] get_portfolio_positions failed: %s", exc)
            stored_positions = []

        positions_by_ticker: dict[str, dict[str, Any]] = {}
        for position in stored_positions:
            ticker = str(position.get("ticker", "")).strip().upper()
            shares = safe_float(position.get("shares")) or 0.0
            avg_cost = safe_float(position.get("avg_cost"))
            if not ticker:
                continue
            positions_by_ticker[ticker] = {
                "ticker": ticker,
                "shares": shares,
                "avg_cost": avg_cost,
            }

        for ticker in merged_watchlist:
            positions_by_ticker.setdefault(
                ticker,
                {
                    "ticker": ticker,
                    "shares": 0.0,
                    "avg_cost": None,
                },
            )

        portfolio = list(positions_by_ticker.values())

        async def _fetch_snapshot(ticker: str) -> tuple[str, dict[str, Any]]:
            try:
                raw_payload = await asyncio.to_thread(deps.get_stock_price, ticker)
                parsed = parse_quote_payload(raw_payload) or {}
                return ticker, parsed
            except Exception:
                return ticker, {}

        snapshot_tickers = list(positions_by_ticker.keys())
        snapshot_pairs = await asyncio.gather(*[_fetch_snapshot(ticker) for ticker in snapshot_tickers])
        snapshots = {ticker: payload for ticker, payload in snapshot_pairs if payload}

        context = TaskContext(
            portfolio=portfolio,
            recent_reports=recent_reports,
            snapshots=snapshots,
        )

        tasks = await _task_generator.generate(context)
        now = datetime.now(timezone.utc)
        serialized_tasks: list[dict[str, Any]] = []
        for task in tasks:
            payload = task.model_dump()
            expires_at_raw = payload.get("expires_at")
            if isinstance(expires_at_raw, str) and expires_at_raw:
                try:
                    expires_at_dt = datetime.fromisoformat(expires_at_raw.replace("Z", "+00:00"))
                    if now > expires_at_dt and payload.get("status") != "done":
                        payload["status"] = "expired"
                except Exception:
                    pass
            serialized_tasks.append(payload)

        return {
            "success": True,
            "session_id": normalized_session,
            "risk_preference": risk_preference,
            "watchlist": merged_watchlist,
            "tasks": serialized_tasks,
            "count": len(tasks),
        }

    return router

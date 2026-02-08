from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException

from backend.services.daily_tasks import generate_daily_tasks


@dataclass(frozen=True)
class TaskRouterDeps:
    resolve_thread_id: Callable[[Optional[str]], str]
    get_report_index_store: Callable[[], Any]


def create_task_router(deps: TaskRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Tasks"])

    @router.get("/api/tasks/daily")
    async def get_daily_tasks(
        session_id: str,
        risk_preference: str = "balanced",
        news_count: int = 0,
    ):
        """根据用户画像和数据状态生成每日个性化任务列表。"""
        try:
            normalized_session = deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        # 获取用户最近的研报
        store = deps.get_report_index_store()
        reports = store.list_reports(
            session_id=normalized_session,
            limit=20,
        )

        # 从研报中提取 watchlist tickers
        watchlist = list({r["ticker"] for r in reports if r.get("ticker")})

        tasks = generate_daily_tasks(
            watchlist=watchlist,
            reports=reports,
            news_count=news_count,
            risk_preference=risk_preference,
        )

        return {
            "success": True,
            "session_id": normalized_session,
            "risk_preference": risk_preference,
            "tasks": tasks,
            "count": len(tasks),
        }

    return router

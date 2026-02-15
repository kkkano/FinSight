from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Query

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
        watchlist: str = Query("", description="逗号分隔的 ticker 列表 (可选, 补充研报中缺失的 ticker)"),
    ):
        """根据用户画像和数据状态生成每日个性化任务列表。

        响应中每条任务包含 execution_params 字段（可执行任务）或 None（导航型任务）。
        前端可直接将 execution_params 传入 executeAgent() 就地执行。
        """
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

        # 合并 watchlist: 研报中的 tickers + 前端传入的 tickers
        report_tickers = {r["ticker"] for r in reports if r.get("ticker")}
        extra_tickers = {
            t.strip().upper()
            for t in (watchlist or "").split(",")
            if t.strip()
        }
        merged_watchlist = list(report_tickers | extra_tickers)

        tasks = generate_daily_tasks(
            watchlist=merged_watchlist,
            reports=reports,
            news_count=news_count,
            risk_preference=risk_preference,
        )

        return {
            "success": True,
            "session_id": normalized_session,
            "risk_preference": risk_preference,
            "watchlist": merged_watchlist,
            "tasks": tasks,
            "count": len(tasks),
        }

    return router

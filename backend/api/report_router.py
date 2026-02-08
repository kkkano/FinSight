from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException

# 防御性校验: report_id 仅允许安全字符
_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")


def _validate_report_id(report_id: str) -> str:
    """校验 report_id 格式，防止注入或路径穿越。"""
    if not report_id or not _SAFE_ID_PATTERN.fullmatch(report_id):
        raise HTTPException(status_code=422, detail="report_id format invalid")
    return report_id


@dataclass(frozen=True)
class ReportRouterDeps:
    resolve_thread_id: Callable[[Optional[str]], str]
    get_report_index_store: Callable[[], Any]


def create_report_router(deps: ReportRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Reports"])

    @router.get("/api/reports/index")
    async def list_report_index(
        session_id: str,
        ticker: Optional[str] = None,
        query: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        tag: Optional[str] = None,
        source_type: Optional[str] = None,
        favorite_only: bool = False,
        limit: int = 50,
    ):
        try:
            normalized_session = deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        store = deps.get_report_index_store()
        rows = store.list_reports(
            session_id=normalized_session,
            ticker=ticker,
            query=query,
            date_from=date_from,
            date_to=date_to,
            tag=tag,
            source_type=source_type,
            favorite_only=bool(favorite_only),
            limit=limit,
        )
        return {"success": True, "session_id": normalized_session, "items": rows, "count": len(rows)}

    @router.get("/api/reports/replay/{report_id}")
    async def get_report_replay(report_id: str, session_id: str):
        report_id = _validate_report_id(report_id)
        try:
            normalized_session = deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        store = deps.get_report_index_store()
        replay = store.get_report_replay(session_id=normalized_session, report_id=report_id)
        if not replay:
            raise HTTPException(status_code=404, detail="report not found")
        return {"success": True, "session_id": normalized_session, **replay}

    @router.get("/api/reports/citations")
    async def list_report_citations(
        session_id: str,
        report_id: Optional[str] = None,
        query: Optional[str] = None,
        source_id: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        limit: int = 100,
    ):
        try:
            normalized_session = deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        store = deps.get_report_index_store()
        rows = store.list_citations(
            session_id=normalized_session,
            report_id=report_id,
            query=query,
            source_id=source_id,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )
        return {
            "success": True,
            "session_id": normalized_session,
            "items": rows,
            "count": len(rows),
        }

    @router.post("/api/reports/{report_id}/favorite")
    async def set_report_favorite(report_id: str, request: dict):
        report_id = _validate_report_id(report_id)
        session_id = request.get("session_id")
        try:
            normalized_session = deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        is_favorite = bool(request.get("is_favorite", True))
        store = deps.get_report_index_store()
        ok = store.set_favorite(
            session_id=normalized_session,
            report_id=report_id,
            is_favorite=is_favorite,
        )
        if not ok:
            raise HTTPException(status_code=404, detail="report not found")

        return {
            "success": True,
            "session_id": normalized_session,
            "report_id": report_id,
            "is_favorite": is_favorite,
        }

    return router

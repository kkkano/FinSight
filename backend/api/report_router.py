from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request, Response


_REPORT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SHARE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
_SHARED_SENSITIVE_KEYS = {
    "user_id",
    "user_email",
    "session_id",
    "thread_id",
    "api_key",
    "authorization",
    "cookie",
    "cost",
    "tool_diagnostics",
    "trace",
    "token",
}


def _validate_report_id(report_id: str) -> str:
    normalized = str(report_id or "").strip()
    if not _REPORT_ID_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=404, detail="report not found")
    return normalized


def _strip_shared_sensitive(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_shared_sensitive(item)
            for key, item in value.items()
            if str(key).lower() not in _SHARED_SENSITIVE_KEYS
        }
    if isinstance(value, list):
        return [_strip_shared_sensitive(item) for item in value]
    return value


@dataclass(frozen=True)
class ReportRouterDeps:
    resolve_thread_id: Callable[[str | None], str]
    get_report_index_store: Callable[[], Any]


def create_report_router(deps: ReportRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Reports"])

    def authenticated_user(request: Request) -> str:
        user_id = str(getattr(request.state, "user_id", "public") or "public").strip()
        if not user_id or user_id == "public":
            raise HTTPException(
                status_code=401,
                detail={"code": "auth_required", "message": "登录后才能访问报告"},
            )
        return user_id

    def owned_session(session_id: str, request: Request) -> tuple[str, str]:
        try:
            normalized = deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        user_id = authenticated_user(request)
        parts = normalized.split(":")
        if len(parts) != 3 or parts[1] != user_id:
            raise HTTPException(status_code=404, detail="report not found")
        return normalized, user_id

    @router.get("/api/reports/index")
    async def list_report_index(
        request: Request,
        session_id: str,
        ticker: str | None = None,
        query: str | None = None,
        source_type: str | None = None,
        include_blocked: bool = False,
        limit: int = Query(default=50, ge=1, le=500),
    ):
        normalized, user_id = owned_session(session_id, request)
        rows = deps.get_report_index_store().list_reports(
            session_id=normalized,
            ticker=ticker,
            query=query,
            source_type=source_type,
            include_blocked=include_blocked,
            limit=limit,
            user_id=user_id,
        )
        return {"session_id": normalized, "items": rows, "count": len(rows)}

    @router.get("/api/reports/replay/{report_id}")
    async def get_report_replay(
        report_id: str,
        request: Request,
        session_id: str,
        include_blocked: bool = False,
    ):
        normalized, user_id = owned_session(session_id, request)
        replay = deps.get_report_index_store().get_report_replay(
            session_id=normalized,
            report_id=_validate_report_id(report_id),
            include_blocked=include_blocked,
            user_id=user_id,
        )
        if not replay:
            raise HTTPException(status_code=404, detail="report not found")
        return {"session_id": normalized, **replay}

    @router.post("/api/reports/{report_id}/share")
    async def create_report_share(report_id: str, request: Request):
        token = deps.get_report_index_store().create_share(
            report_id=_validate_report_id(report_id),
            user_id=authenticated_user(request),
        )
        if not token:
            raise HTTPException(status_code=404, detail="report not found")
        return {"share_url": f"/share/r/{token}"}

    @router.delete("/api/reports/{report_id}/share", status_code=204)
    async def revoke_report_share(report_id: str, request: Request):
        removed = deps.get_report_index_store().revoke_share(
            report_id=_validate_report_id(report_id),
            user_id=authenticated_user(request),
        )
        if not removed:
            raise HTTPException(status_code=404, detail="report not found")
        return Response(status_code=204)

    @router.get("/api/reports/shared/{token}")
    async def get_shared_report(token: str):
        normalized = str(token or "").strip()
        if not _SHARE_TOKEN_PATTERN.fullmatch(normalized):
            raise HTTPException(status_code=404, detail="shared report not found")
        report = deps.get_report_index_store().get_shared_report(token=normalized)
        if not report:
            raise HTTPException(status_code=404, detail="shared report not found")
        return {"report": _strip_shared_sensitive(report)}

    return router


__all__ = ["ReportRouterDeps", "create_report_router"]

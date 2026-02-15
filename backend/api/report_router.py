from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

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

    # ------------------------------------------------------------------
    # GET /api/reports/compare — structural diff between two reports
    # ------------------------------------------------------------------

    @router.get("/api/reports/compare")
    async def compare_reports(
        session_id: str,
        id1: str,
        id2: str,
    ):
        """Compare two reports and return structured differences."""
        id1 = _validate_report_id(id1)
        id2 = _validate_report_id(id2)
        try:
            normalized_session = deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        store = deps.get_report_index_store()
        report_a = store.get_report_replay(session_id=normalized_session, report_id=id1)
        report_b = store.get_report_replay(session_id=normalized_session, report_id=id2)
        if not report_a:
            raise HTTPException(status_code=404, detail=f"report {id1} not found")
        if not report_b:
            raise HTTPException(status_code=404, detail=f"report {id2} not found")

        # Build structured diff
        def _safe_get(d: dict, *keys: str, default: Any = None) -> Any:
            current = d
            for key in keys:
                if not isinstance(current, dict):
                    return default
                current = current.get(key, default)
            return current

        ra = report_a.get("report", {}) if isinstance(report_a.get("report"), dict) else {}
        rb = report_b.get("report", {}) if isinstance(report_b.get("report"), dict) else {}

        # Score changes
        score_a = _safe_get(ra, "confidence_score")
        score_b = _safe_get(rb, "confidence_score")
        score_delta = None
        if isinstance(score_a, (int, float)) and isinstance(score_b, (int, float)):
            score_delta = round(score_b - score_a, 4)

        # Sentiment changes
        sentiment_a = _safe_get(ra, "sentiment") or _safe_get(ra, "recommendation")
        sentiment_b = _safe_get(rb, "sentiment") or _safe_get(rb, "recommendation")

        # Risk changes
        risks_a = _safe_get(ra, "risks", default=[]) or []
        risks_b = _safe_get(rb, "risks", default=[]) or []
        risks_a_set = {str(r) for r in risks_a} if isinstance(risks_a, list) else set()
        risks_b_set = {str(r) for r in risks_b} if isinstance(risks_b, list) else set()

        # Summary / key metric changes
        summary_a = _safe_get(ra, "summary", default="")
        summary_b = _safe_get(rb, "summary", default="")

        return {
            "success": True,
            "session_id": normalized_session,
            "report_a": {"report_id": id1, "title": _safe_get(ra, "title"), "generated_at": _safe_get(ra, "generated_at")},
            "report_b": {"report_id": id2, "title": _safe_get(rb, "title"), "generated_at": _safe_get(rb, "generated_at")},
            "diff": {
                "confidence_score": {"a": score_a, "b": score_b, "delta": score_delta},
                "sentiment": {"a": sentiment_a, "b": sentiment_b, "changed": sentiment_a != sentiment_b},
                "risks": {
                    "added": sorted(risks_b_set - risks_a_set),
                    "removed": sorted(risks_a_set - risks_b_set),
                    "unchanged_count": len(risks_a_set & risks_b_set),
                },
                "summary": {"a": summary_a, "b": summary_b},
            },
        }

    return router

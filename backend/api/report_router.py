from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query, Request, Response


_REPORT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_SHARE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
_PUBLIC_REPORT_SCALARS = (
    "report_id",
    "ticker",
    "company_name",
    "title",
    "summary",
    "sentiment",
    "confidence_score",
    "grounding_rate",
    "generated_at",
    "recommendation",
    "conflict_disclosure",
    "synthesis_report",
)


def _validate_report_id(report_id: str) -> str:
    normalized = str(report_id or "").strip()
    if not _REPORT_ID_PATTERN.fullmatch(normalized):
        raise HTTPException(status_code=404, detail="report not found")
    return normalized


def _project_fields(value: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {field: value[field] for field in fields if field in value}


def _public_report_section(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    section = _project_fields(
        value,
        (
            "title",
            "order",
            "confidence",
            "agent_name",
            "data_sources",
            "is_collapsible",
            "default_collapsed",
        ),
    )
    section["contents"] = []
    for item in (value.get("contents") or []):
        if not isinstance(item, dict):
            continue
        content = _project_fields(item, ("type", "content", "citation_refs"))
        section["contents"].append(content)
    section["subsections"] = [
        projected
        for item in (value.get("subsections") or [])
        if (projected := _public_report_section(item)) is not None
    ]
    return section


def _public_citation(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    citation = _project_fields(
        value,
        (
            "source_id",
            "title",
            "url",
            "snippet",
            "published_date",
            "confidence",
            "freshness_hours",
        ),
    )
    url = str(citation.get("url") or "").strip()
    if url and urlparse(url).scheme.lower() not in {"http", "https"}:
        citation["url"] = ""
    return citation


def _public_report_quality(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    quality = _project_fields(value, ("schema_version", "state", "evaluated_at", "content_contract_version",
                                      "content_status", "answer_status", "has_supported_content", "publishable", "conclusion_status"))
    quality["reasons"] = [
        _project_fields(item, ("code", "severity", "metric", "message"))
        for item in (value.get("reasons") or [])
        if isinstance(item, dict)
    ]
    return quality


def _public_shared_report(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    report = _project_fields(value, _PUBLIC_REPORT_SCALARS)
    report["sections"] = [
        projected
        for item in (value.get("sections") or [])
        if (projected := _public_report_section(item)) is not None
    ]
    report["citations"] = [
        projected
        for item in (value.get("citations") or [])
        if (projected := _public_citation(item)) is not None
    ]
    for field in ("risks", "tags"):
        if isinstance(value.get(field), list):
            report[field] = list(value[field])
    if isinstance(value.get("core_viewpoints"), list):
        report["core_viewpoints"] = [
            _project_fields(
                item,
                (
                    "agent_name",
                    "title",
                    "headline",
                    "detail",
                    "confidence",
                    "data_sources",
                    "evidence_count",
                    "status",
                ),
            )
            for item in value["core_viewpoints"]
            if isinstance(item, dict)
        ]
    if isinstance(value.get("report_hints"), dict):
        report["report_hints"] = _project_fields(
            value["report_hints"],
            ("is_compare", "has_conflict", "compare_basis", "conflict_agents"),
        )
    quality = _public_report_quality(value.get("report_quality"))
    if quality is not None:
        report["report_quality"] = quality
    if isinstance(value.get("fact_check"), dict):
        fact_check = _project_fields(
            value["fact_check"],
            ("redaction_count", "verified_at", "enabled", "checked"),
        )
        fact_check["verifier_claims"] = [
            _project_fields(item, ("claim", "reason"))
            for item in (value["fact_check"].get("verifier_claims") or [])
            if isinstance(item, dict)
        ]
        report["fact_check"] = fact_check
    return report


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
        session_id: str | None = None,
        ticker: str | None = None,
        query: str | None = None,
        source_type: str | None = None,
        include_blocked: bool = False,
        limit: int = Query(default=50, ge=1, le=500),
    ):
        normalized, user_id = owned_session(session_id, request) if session_id else (None, authenticated_user(request))
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
        session_id: str | None = None,
        include_blocked: bool = False,
    ):
        normalized, user_id = owned_session(session_id, request) if session_id else (None, authenticated_user(request))
        replay = deps.get_report_index_store().get_report_replay(
            session_id=normalized,
            report_id=_validate_report_id(report_id),
            include_blocked=include_blocked,
            user_id=user_id,
        )
        if not replay:
            raise HTTPException(status_code=404, detail="report not found")
        return {"session_id": replay.get("session_id", normalized), **replay}

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
    async def get_shared_report(token: str, response: Response):
        normalized = str(token or "").strip()
        if not _SHARE_TOKEN_PATTERN.fullmatch(normalized):
            raise HTTPException(status_code=404, detail="shared report not found")
        report = deps.get_report_index_store().get_shared_report(token=normalized)
        if not report:
            raise HTTPException(status_code=404, detail="shared report not found")
        response.headers["Cache-Control"] = "private, no-store"
        return {"report": _public_shared_report(report)}

    return router


__all__ = ["ReportRouterDeps", "create_report_router"]

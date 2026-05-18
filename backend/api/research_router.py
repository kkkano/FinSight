# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field


_SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._\-]{1,128}$")
_SAFE_TICKER_PATTERN = re.compile(r"^[A-Za-z0-9.\-]{1,24}$")


def _validate_safe_id(value: str, field_name: str) -> str:
    text = str(value or "").strip()
    if not text or not _SAFE_ID_PATTERN.fullmatch(text):
        raise HTTPException(status_code=422, detail=f"{field_name} format invalid")
    return text


def _validate_ticker(value: str) -> str:
    text = str(value or "").strip().upper()
    if not text or not _SAFE_TICKER_PATTERN.fullmatch(text):
        raise HTTPException(status_code=422, detail="ticker format invalid")
    return text


def _bounded_limit(value: int, *, default: int = 50, minimum: int = 1, maximum: int = 200) -> int:
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    return max(minimum, min(maximum, parsed))


def _extract_ledger(report: dict[str, Any], citations: list[dict[str, Any]]) -> dict[str, Any]:
    candidates = [
        report.get("evidence_ledger"),
        (report.get("meta") or {}).get("evidence_ledger") if isinstance(report.get("meta"), dict) else None,
        (report.get("report_hints") or {}).get("evidence_ledger") if isinstance(report.get("report_hints"), dict) else None,
    ]
    meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
    hints = meta.get("report_hints") if isinstance(meta.get("report_hints"), dict) else {}
    candidates.append(hints.get("evidence_ledger"))
    for item in candidates:
        if isinstance(item, dict) and item:
            return item

    report_id = str(report.get("report_id") or "").strip()
    source_ids = [
        str(item.get("source_id") or "").strip()
        for item in citations
        if isinstance(item, dict) and str(item.get("source_id") or "").strip()
    ]
    return {
        "ledger_id": f"report:{report_id}:citations",
        "query": str(report.get("title") or report.get("ticker") or "").strip(),
        "subject": {"ticker": str(report.get("ticker") or "").strip()},
        "claims": [
            {
                "claim_id": f"report:{report_id}:summary",
                "claim": str(report.get("summary") or "报告未保存结构化证据账本。").strip(),
                "stance": "unknown",
                "evidence_ids": source_ids,
                "confidence": report.get("confidence_score") or 0.5,
                "agent_name": "report_index",
                "task_ids": [],
                "limitations": ["Structured evidence ledger was not stored with this report."],
            }
        ],
        "sources": [
            {
                "source_id": str(item.get("source_id") or "").strip(),
                "title": str(item.get("title") or "").strip(),
                "url": item.get("url"),
                "source": str(item.get("source") or item.get("source_type") or "report_citation"),
                "published_date": item.get("published_date"),
                "reliability": item.get("confidence") or 0.5,
            }
            for item in citations
            if isinstance(item, dict) and str(item.get("source_id") or "").strip()
        ],
        "uncertainties": [],
        "contradictions": [],
        "coverage_targets": [],
    }


def _extract_debate(report: dict[str, Any], ledger: dict[str, Any], query: str) -> dict[str, Any]:
    candidates = [
        report.get("debate"),
        (report.get("meta") or {}).get("debate") if isinstance(report.get("meta"), dict) else None,
        (report.get("report_hints") or {}).get("debate") if isinstance(report.get("report_hints"), dict) else None,
    ]
    for item in candidates:
        if isinstance(item, dict) and item:
            return item

    from backend.research.debate import build_debate_artifact

    return build_debate_artifact(ledger, query=query)


@dataclass(frozen=True)
class ResearchRouterDeps:
    resolve_thread_id: Callable[[Optional[str]], str]
    get_report_index_store: Callable[[], Any]


class RunDebateRequest(BaseModel):
    ledger: dict[str, Any] = Field(..., description="Evidence ledger payload")
    query: str = Field(default="", description="Research question")


def create_research_router(deps: ResearchRouterDeps) -> APIRouter:
    router = APIRouter(tags=["Research"])

    def _load_replay(report_id: str, session_id: str, include_blocked: bool) -> tuple[str, dict[str, Any]]:
        safe_report_id = _validate_safe_id(report_id, "report_id")
        try:
            normalized_session = deps.resolve_thread_id(session_id)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        replay = deps.get_report_index_store().get_report_replay(
            session_id=normalized_session,
            report_id=safe_report_id,
            include_blocked=bool(include_blocked),
        )
        if not replay:
            raise HTTPException(status_code=404, detail="report not found")
        return normalized_session, replay

    @router.get("/api/research/ledger/{report_id}")
    async def get_research_ledger(report_id: str, session_id: str, include_blocked: bool = False):
        normalized_session, replay = _load_replay(report_id, session_id, include_blocked)
        report = replay.get("report") if isinstance(replay.get("report"), dict) else {}
        citations = replay.get("citations") if isinstance(replay.get("citations"), list) else []
        ledger = _extract_ledger(report, [item for item in citations if isinstance(item, dict)])
        return {
            "success": True,
            "session_id": normalized_session,
            "report_id": report_id,
            "ledger": ledger,
        }

    @router.get("/api/research/debate/{report_id}")
    async def get_research_debate(report_id: str, session_id: str, include_blocked: bool = False):
        normalized_session, replay = _load_replay(report_id, session_id, include_blocked)
        report = replay.get("report") if isinstance(replay.get("report"), dict) else {}
        citations = replay.get("citations") if isinstance(replay.get("citations"), list) else []
        ledger = _extract_ledger(report, [item for item in citations if isinstance(item, dict)])
        debate = _extract_debate(report, ledger, query=str(report.get("title") or report.get("summary") or ""))
        return {
            "success": True,
            "session_id": normalized_session,
            "report_id": report_id,
            "debate": debate,
        }

    @router.get("/api/research/holdings/{ticker}")
    async def get_research_holdings(
        ticker: str,
        limit: int = Query(default=50, ge=1, le=200),
    ):
        normalized = _validate_ticker(ticker)
        from backend.tools.sec_holdings import get_institution_holdings_by_ticker

        payload = get_institution_holdings_by_ticker(normalized, limit=_bounded_limit(limit, maximum=200))
        return {
            "success": True,
            "ticker": normalized,
            "holdings": payload,
        }

    @router.post("/api/research/run-debate")
    async def run_research_debate(request: RunDebateRequest):
        from backend.research.debate import build_debate_artifact

        return {
            "success": True,
            "debate": build_debate_artifact(request.ledger, query=request.query),
        }

    return router


__all__ = ["ResearchRouterDeps", "RunDebateRequest", "create_research_router"]

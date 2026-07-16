from __future__ import annotations

import hashlib
import json
import secrets
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text

from backend.report.quality_engine import apply_quality_to_report
from backend.services.database import create_core_engine, resolve_core_postgres_dsn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _derive_source_id(item: dict[str, Any]) -> str:
    url = _clean_text(item.get("url"))
    title = _clean_text(item.get("title"))
    snippet = _clean_text(item.get("snippet"))
    published_date = _clean_text(item.get("published_date"))
    material = "|".join([url, title, snippet, published_date]) or json.dumps(item, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha1(material.encode("utf-8")).hexdigest()[:16]
    return f"src_{digest}"


def _normalize_citation_item(item: Any) -> dict[str, Any] | None:
    if not isinstance(item, dict):
        return None

    normalized = dict(item)
    normalized["title"] = _clean_text(item.get("title")) or None
    normalized["url"] = _clean_text(item.get("url")) or None
    normalized["snippet"] = _clean_text(item.get("snippet")) or None
    normalized["published_date"] = _clean_text(item.get("published_date")) or None

    if not (normalized["title"] or normalized["url"] or normalized["snippet"]):
        return None

    provided_source_id = _clean_text(item.get("source_id"))
    derived_source_id = _derive_source_id(normalized)
    normalized["source_id"] = derived_source_id
    normalized["source_id_consistent"] = (not provided_source_id) or provided_source_id == derived_source_id
    if provided_source_id and provided_source_id != derived_source_id:
        normalized["source_id_original"] = provided_source_id

    confidence = item.get("confidence")
    try:
        normalized["confidence"] = float(confidence) if confidence is not None else None
    except Exception:
        normalized["confidence"] = None

    return normalized


def _extract_report_meta(report_json: str | None) -> dict[str, Any]:
    if not report_json:
        return {}
    try:
        payload = json.loads(report_json)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    meta = payload.get("meta")
    return meta if isinstance(meta, dict) else {}


def _derive_analysis_depth(
    *,
    source_trigger: str | None,
    report_meta: dict[str, Any],
) -> str | None:
    normalized = str(report_meta.get("analysis_depth") or "").strip().lower()
    if normalized in {"quick", "report", "deep_research"}:
        return normalized

    ui_context = report_meta.get("ui_context")
    if isinstance(ui_context, dict):
        context_depth = str(ui_context.get("analysis_depth") or "").strip().lower()
        if context_depth in {"quick", "report", "deep_research"}:
            return context_depth

    trigger = str(source_trigger or "").strip().lower()
    if not trigger:
        return None
    if "deep" in trigger and ("search" in trigger or "research" in trigger):
        return "deep_research"
    if "quick" in trigger:
        return "quick"
    return "report"


def _derive_quality_fields(report: dict[str, Any]) -> tuple[str, int, str]:
    quality, blocked = apply_quality_to_report(report)
    state = str(quality.get("state") or "pass").strip().lower() or "pass"
    publishable = 0 if blocked else 1
    reasons_json = json.dumps(quality.get("reasons") or [], ensure_ascii=False)
    return state, publishable, reasons_json


class ReportIndexStoreUnavailable(RuntimeError):
    pass


def _session_owner_id(session_id: str) -> str:
    parts = str(session_id or "").strip().split(":")
    if len(parts) != 3 or not parts[1] or parts[1] in {"public", "anonymous"}:
        raise ReportIndexStoreUnavailable("report store requires authenticated tenant session")
    return parts[1]


def _report_owner(session_id: str, user_id: str | None) -> str:
    session_owner = _session_owner_id(session_id)
    explicit = str(user_id or "").strip()
    if explicit and explicit != session_owner:
        raise ReportIndexStoreUnavailable("report session does not belong to authenticated user")
    return explicit or session_owner


def _json_value(value: Any, fallback: Any) -> Any:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _iso_value(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)


class UnavailableReportIndexStore:
    def __getattr__(self, _name: str):
        def unavailable(*_args, **_kwargs):
            raise ReportIndexStoreUnavailable("report postgres unavailable")

        return unavailable


class ReportIndexStore:
    """报告、引用与分享的 PostgreSQL 租户存储。"""

    def __init__(self, *, dsn: str | None = None, engine: Any | None = None) -> None:
        self._engine = engine if engine is not None else create_core_engine(dsn=dsn)

    def upsert_report(
        self,
        *,
        session_id: str,
        report: dict[str, Any],
        trace_digest: dict[str, Any] | None = None,
        include_blocked: bool = False,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        owner = _report_owner(session_id, user_id)
        report_id = str(report.get("report_id") or "").strip()
        if not report_id:
            raise ValueError("report.report_id is required")
        quality_state, publishable_raw, quality_reasons = _derive_quality_fields(report)
        publishable = bool(publishable_raw)
        if quality_state == "block" and not include_blocked:
            return {
                "report_id": report_id,
                "session_id": session_id,
                "quality_state": quality_state,
                "publishable": False,
                "skipped": "quality_blocked",
            }
        confidence = report.get("confidence_score")
        try:
            confidence_value = float(confidence) if confidence is not None else None
        except (TypeError, ValueError):
            confidence_value = None
        meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
        params = {
            "report_id": report_id,
            "user_id": owner,
            "session_id": session_id,
            "ticker": str(report.get("ticker") or "").strip() or None,
            "title": str(report.get("title") or "").strip() or None,
            "summary": str(report.get("summary") or "").strip() or None,
            "tags": json.dumps(report.get("tags") if isinstance(report.get("tags"), list) else [], ensure_ascii=False),
            "generated_at": str(report.get("generated_at") or "").strip() or _now_iso(),
            "confidence_score": confidence_value,
            "trace_digest": json.dumps(trace_digest or {}, ensure_ascii=False),
            "report": json.dumps(report, ensure_ascii=False),
            "quality_state": quality_state,
            "publishable": publishable,
            "quality_reasons": quality_reasons,
            "source_type": str(report.get("source_type") or meta.get("source_type") or "ai_generated").strip() or "ai_generated",
            "filing_type": str(report.get("filing_type") or "").strip() or None,
            "publisher": str(report.get("publisher") or "").strip() or None,
        }
        with self._engine.begin() as conn:
            upserted_owner = conn.execute(
                text(
                    "INSERT INTO reports(report_id,user_id,session_id,ticker,title,summary,tags,generated_at,"
                    "confidence_score,trace_digest,report,quality_state,publishable,quality_reasons,"
                    "source_type,filing_type,publisher) VALUES (:report_id,:user_id,:session_id,:ticker,"
                    ":title,:summary,CAST(:tags AS jsonb),CAST(:generated_at AS timestamptz),:confidence_score,"
                    "CAST(:trace_digest AS jsonb),CAST(:report AS jsonb),:quality_state,:publishable,"
                    "CAST(:quality_reasons AS jsonb),:source_type,:filing_type,:publisher) "
                    "ON CONFLICT(report_id) DO UPDATE SET session_id=excluded.session_id,"
                    "ticker=excluded.ticker,title=excluded.title,summary=excluded.summary,tags=excluded.tags,"
                    "generated_at=excluded.generated_at,confidence_score=excluded.confidence_score,"
                    "trace_digest=excluded.trace_digest,report=excluded.report,quality_state=excluded.quality_state,"
                    "publishable=excluded.publishable,quality_reasons=excluded.quality_reasons,"
                    "source_type=excluded.source_type,filing_type=excluded.filing_type,publisher=excluded.publisher,"
                    "updated_at=now() WHERE reports.user_id=excluded.user_id RETURNING user_id"
                ),
                params,
            ).scalar_one_or_none()
            if upserted_owner is None:
                raise ReportIndexStoreUnavailable("report_id belongs to another authenticated user")
            conn.execute(
                text("DELETE FROM report_citations WHERE report_id=:report_id AND user_id=:user_id"),
                {"report_id": report_id, "user_id": owner},
            )
            seen: set[str] = set()
            for item in report.get("citations") or []:
                citation = _normalize_citation_item(item)
                if not citation:
                    continue
                source_id = _clean_text(citation.get("source_id"))
                if source_id in seen:
                    continue
                seen.add(source_id)
                conn.execute(
                    text(
                        "INSERT INTO report_citations(report_id,user_id,session_id,source_id,title,url,snippet,"
                        "published_date,confidence,citation) VALUES (:report_id,:user_id,:session_id,:source_id,"
                        ":title,:url,:snippet,:published_date,:confidence,CAST(:citation AS jsonb))"
                    ),
                    {
                        "report_id": report_id,
                        "user_id": owner,
                        "session_id": session_id,
                        "source_id": source_id,
                        "title": citation.get("title"),
                        "url": citation.get("url"),
                        "snippet": citation.get("snippet"),
                        "published_date": citation.get("published_date"),
                        "confidence": citation.get("confidence"),
                        "citation": json.dumps(citation, ensure_ascii=False),
                    },
                )
        return {"report_id": report_id, "session_id": session_id}

    def list_reports(
        self,
        *,
        session_id: str,
        ticker: str | None = None,
        query: str | None = None,
        source_type: str | None = None,
        include_blocked: bool = False,
        limit: int = 50,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        owner = _report_owner(session_id, user_id)
        where = ["user_id=:user_id", "session_id=:session_id"]
        params: dict[str, Any] = {"user_id": owner, "session_id": session_id}
        if ticker:
            where.append("ticker=:ticker")
            params["ticker"] = ticker
        if query:
            where.append("(title ILIKE :query OR summary ILIKE :query OR ticker ILIKE :query)")
            params["query"] = f"%{query.strip()}%"
        if source_type:
            where.append("source_type=:source_type")
            params["source_type"] = source_type.strip()
        if not include_blocked:
            where.append("publishable=true")
        params["limit"] = max(1, min(500, int(limit)))
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM reports WHERE " + " AND ".join(where) +
                    " ORDER BY generated_at DESC NULLS LAST,created_at DESC LIMIT :limit"
                ),
                params,
            ).mappings().all()
        result: list[dict[str, Any]] = []
        for row in rows:
            data = dict(row)
            report_payload = _json_value(data.get("report"), {})
            report_meta = report_payload.get("meta") if isinstance(report_payload.get("meta"), dict) else {}
            source_trigger = str(report_meta.get("source_trigger") or "").strip() or None
            result.append(
                {
                    "report_id": data["report_id"],
                    "session_id": data["session_id"],
                    "ticker": data.get("ticker"),
                    "title": data.get("title"),
                    "summary": data.get("summary"),
                    "generated_at": _iso_value(data.get("generated_at")),
                    "confidence_score": data.get("confidence_score"),
                    "tags": _json_value(data.get("tags"), []),
                    "source_type": data.get("source_type"),
                    "quality_state": data.get("quality_state") or "pass",
                    "publishable": bool(data.get("publishable")),
                    "quality_reasons": _json_value(data.get("quality_reasons"), []),
                    "source_trigger": source_trigger,
                    "analysis_depth": _derive_analysis_depth(source_trigger=source_trigger, report_meta=report_meta),
                    "filing_type": data.get("filing_type"),
                    "publisher": data.get("publisher"),
                    "created_at": _iso_value(data.get("created_at")),
                    "updated_at": _iso_value(data.get("updated_at")),
                }
            )
        return result

    def get_report_replay(
        self,
        *,
        session_id: str,
        report_id: str,
        include_blocked: bool = False,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        owner = _report_owner(session_id, user_id)
        publishable = "" if include_blocked else " AND publishable=true"
        with self._engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT report,trace_digest FROM reports WHERE user_id=:user_id "
                    "AND session_id=:session_id AND report_id=:report_id" + publishable
                ),
                {"user_id": owner, "session_id": session_id, "report_id": report_id},
            ).mappings().first()
            if not row:
                return None
            citations = conn.execute(
                text(
                    "SELECT citation FROM report_citations WHERE user_id=:user_id "
                    "AND session_id=:session_id AND report_id=:report_id ORDER BY id"
                ),
                {"user_id": owner, "session_id": session_id, "report_id": report_id},
            ).scalars().all()
        report_payload = _json_value(row["report"], {})
        citation_items = [_json_value(item, {}) for item in citations]
        report_payload["citations"] = citation_items
        return {
            "report": report_payload,
            "trace_digest": _json_value(row["trace_digest"], {}),
            "citations": citation_items,
        }

    def get_report_by_id(
        self,
        *,
        report_id: str,
        include_blocked: bool = False,
        user_id: str | None = None,
    ) -> dict[str, Any] | None:
        owner = str(user_id or "").strip()
        if not owner or owner == "public":
            raise ReportIndexStoreUnavailable("report lookup requires authenticated user")
        where = ["report_id=:report_id", "user_id=:user_id"]
        params: dict[str, Any] = {"report_id": report_id, "user_id": owner}
        if not include_blocked:
            where.append("publishable=true")
        with self._engine.connect() as conn:
            value = conn.execute(
                text("SELECT report FROM reports WHERE " + " AND ".join(where)), params
            ).scalar()
        return _json_value(value, {}) if value is not None else None

    def list_citations(
        self,
        *,
        session_id: str,
        report_id: str | None = None,
        query: str | None = None,
        source_id: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 100,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        owner = _report_owner(session_id, user_id)
        where = ["user_id=:user_id", "session_id=:session_id"]
        params: dict[str, Any] = {"user_id": owner, "session_id": session_id}
        if report_id:
            where.append("report_id=:report_id")
            params["report_id"] = report_id
        if source_id:
            where.append("source_id=:source_id")
            params["source_id"] = source_id.strip()
        if date_from:
            where.append("published_date>=:date_from")
            params["date_from"] = date_from.strip()
        if date_to:
            where.append("published_date<=:date_to")
            params["date_to"] = date_to.strip()
        if query:
            where.append("(title ILIKE :query OR snippet ILIKE :query OR url ILIKE :query OR source_id ILIKE :query)")
            params["query"] = f"%{query.strip()}%"
        params["limit"] = max(1, min(500, int(limit)))
        with self._engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT * FROM report_citations WHERE " + " AND ".join(where) +
                    " ORDER BY id DESC LIMIT :limit"
                ),
                params,
            ).mappings().all()
        return [
            {
                "row_id": row["id"], "report_id": row["report_id"], "session_id": row["session_id"],
                "source_id": row["source_id"], "title": row["title"], "url": row["url"],
                "snippet": row["snippet"], "published_date": row["published_date"],
                "confidence": row["confidence"], "created_at": _iso_value(row["created_at"]),
                "citation": _json_value(row["citation"], {}),
            }
            for row in rows
        ]

    def create_share(self, *, report_id: str, user_id: str | None = None) -> str | None:
        if not user_id:
            raise ReportIndexStoreUnavailable("share creation requires authenticated user")
        with self._engine.begin() as conn:
            existing = conn.execute(
                text(
                    "SELECT share_token FROM reports WHERE report_id=:report_id "
                    "AND user_id=:user_id AND publishable=true"
                ),
                {"report_id": report_id, "user_id": user_id},
            ).scalar()
            if existing:
                return str(existing)
            token = secrets.token_urlsafe(24)
            result = conn.execute(
                text(
                    "UPDATE reports SET share_token=:token,shared_at=now(),updated_at=now() "
                    "WHERE report_id=:report_id AND user_id=:user_id AND publishable=true"
                ),
                {"token": token, "report_id": report_id, "user_id": user_id},
            )
        return token if result.rowcount else None

    def revoke_share(self, *, report_id: str, user_id: str | None = None) -> bool:
        if not user_id:
            raise ReportIndexStoreUnavailable("share revoke requires authenticated user")
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "UPDATE reports SET share_token=NULL,shared_at=NULL,updated_at=now() "
                    "WHERE report_id=:report_id AND user_id=:user_id"
                ),
                {"report_id": report_id, "user_id": user_id},
            )
        return bool(result.rowcount)

    def get_shared_report(self, *, token: str) -> dict[str, Any] | None:
        with self._engine.connect() as conn:
            value = conn.execute(
                text("SELECT report FROM reports WHERE share_token=:token AND publishable=true"),
                {"token": token},
            ).scalar()
        return _json_value(value, {}) if value is not None else None

    def delete_session(self, *, session_id: str, user_id: str | None = None) -> dict[str, int]:
        owner = _report_owner(session_id, user_id)
        with self._engine.begin() as conn:
            citations = conn.execute(
                text("DELETE FROM report_citations WHERE user_id=:user_id AND session_id=:session_id"),
                {"user_id": owner, "session_id": session_id},
            )
            reports = conn.execute(
                text("DELETE FROM reports WHERE user_id=:user_id AND session_id=:session_id"),
                {"user_id": owner, "session_id": session_id},
            )
        return {"reports": int(reports.rowcount or 0), "citations": int(citations.rowcount or 0)}


_REPORT_INDEX_STORE: ReportIndexStore | UnavailableReportIndexStore | None = None


def get_report_index_store() -> ReportIndexStore | UnavailableReportIndexStore:
    global _REPORT_INDEX_STORE
    if _REPORT_INDEX_STORE is None:
        dsn = resolve_core_postgres_dsn(required=False)
        try:
            _REPORT_INDEX_STORE = ReportIndexStore(dsn=dsn) if dsn else UnavailableReportIndexStore()
        except Exception:
            _REPORT_INDEX_STORE = UnavailableReportIndexStore()
    return _REPORT_INDEX_STORE


def reset_report_index_store_cache() -> None:
    global _REPORT_INDEX_STORE
    _REPORT_INDEX_STORE = None


__all__ = [
    "ReportIndexStore",
    "ReportIndexStoreUnavailable",
    "get_report_index_store",
    "reset_report_index_store_cache",
]

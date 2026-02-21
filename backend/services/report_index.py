from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from backend.report.quality_engine import apply_quality_to_report


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


class ReportIndexStore:
    def __init__(self) -> None:
        path = os.getenv("REPORT_INDEX_SQLITE_PATH", "backend/data/report_index.sqlite")
        self._path = os.path.abspath(path)
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        self._lock = threading.Lock()
        self._init_db()

    @property
    def path(self) -> str:
        return self._path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _column_exists(self, conn: sqlite3.Connection, table: str, column: str) -> bool:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        for row in rows:
            try:
                if str(row["name"]).strip().lower() == column.lower():
                    return True
            except Exception:
                if len(row) > 1 and str(row[1]).strip().lower() == column.lower():
                    return True
        return False

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        if self._column_exists(conn, table, column):
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS report_index (
                    report_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    ticker TEXT,
                    title TEXT,
                    summary TEXT,
                    tags_json TEXT,
                    generated_at TEXT,
                    confidence_score REAL,
                    is_favorite INTEGER NOT NULL DEFAULT 0,
                    trace_digest_json TEXT,
                    report_json TEXT NOT NULL,
                    quality_state TEXT NOT NULL DEFAULT 'pass',
                    publishable INTEGER NOT NULL DEFAULT 1,
                    quality_reasons_json TEXT,
                    source_type TEXT NOT NULL DEFAULT 'ai_generated',
                    filing_type TEXT,
                    publisher TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_report_index_session ON report_index(session_id);
                CREATE INDEX IF NOT EXISTS idx_report_index_ticker ON report_index(ticker);
                CREATE INDEX IF NOT EXISTS idx_report_index_generated_at ON report_index(generated_at);
                CREATE INDEX IF NOT EXISTS idx_report_index_source_type ON report_index(source_type);
                CREATE INDEX IF NOT EXISTS idx_report_index_quality_state ON report_index(quality_state);
                CREATE INDEX IF NOT EXISTS idx_report_index_publishable ON report_index(publishable);

                CREATE TABLE IF NOT EXISTS citation_index (
                    row_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    source_id TEXT,
                    title TEXT,
                    url TEXT,
                    snippet TEXT,
                    published_date TEXT,
                    confidence REAL,
                    citation_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(report_id) REFERENCES report_index(report_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_citation_index_report ON citation_index(report_id);
                CREATE INDEX IF NOT EXISTS idx_citation_index_session ON citation_index(session_id);
                CREATE INDEX IF NOT EXISTS idx_citation_index_url ON citation_index(url);
                """
            )
            self._ensure_column(conn, "report_index", "quality_state", "TEXT NOT NULL DEFAULT 'pass'")
            self._ensure_column(conn, "report_index", "publishable", "INTEGER NOT NULL DEFAULT 1")
            self._ensure_column(conn, "report_index", "quality_reasons_json", "TEXT")

    def upsert_report(
        self,
        *,
        session_id: str,
        report: dict[str, Any],
        trace_digest: dict[str, Any] | None = None,
        include_blocked: bool = False,
    ) -> dict[str, Any]:
        report_id = str(report.get("report_id") or "").strip()
        if not report_id:
            raise ValueError("report.report_id is required")

        ticker = str(report.get("ticker") or "").strip() or None
        title = str(report.get("title") or "").strip() or None
        summary = str(report.get("summary") or "").strip() or None
        confidence = report.get("confidence_score")
        try:
            confidence_value = float(confidence) if confidence is not None else None
        except Exception:
            confidence_value = None

        tags = report.get("tags")
        tags_json = json.dumps(tags, ensure_ascii=False) if isinstance(tags, list) else None
        report_json = json.dumps(report, ensure_ascii=False)
        trace_digest_json = json.dumps(trace_digest or {}, ensure_ascii=False)
        quality_state, publishable, quality_reasons_json = _derive_quality_fields(report)
        if quality_state == "block" and not include_blocked:
            return {
                "report_id": report_id,
                "session_id": session_id,
                "quality_state": quality_state,
                "publishable": False,
                "skipped": "quality_blocked",
            }
        generated_at = str(report.get("generated_at") or "").strip() or _now_iso()
        meta = report.get("meta") if isinstance(report.get("meta"), dict) else {}
        source_type = str(report.get("source_type") or meta.get("source_type") or "ai_generated").strip() or "ai_generated"
        filing_type = str(report.get("filing_type") or "").strip() or None
        publisher = str(report.get("publisher") or "").strip() or None
        now = _now_iso()

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO report_index(
                        report_id, session_id, ticker, title, summary, tags_json,
                        generated_at, confidence_score, trace_digest_json, report_json,
                        quality_state, publishable, quality_reasons_json,
                        source_type, filing_type, publisher,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(report_id) DO UPDATE SET
                        session_id=excluded.session_id,
                        ticker=excluded.ticker,
                        title=excluded.title,
                        summary=excluded.summary,
                        tags_json=excluded.tags_json,
                        generated_at=excluded.generated_at,
                        confidence_score=excluded.confidence_score,
                        trace_digest_json=excluded.trace_digest_json,
                        report_json=excluded.report_json,
                        quality_state=excluded.quality_state,
                        publishable=excluded.publishable,
                        quality_reasons_json=excluded.quality_reasons_json,
                        source_type=excluded.source_type,
                        filing_type=excluded.filing_type,
                        publisher=excluded.publisher,
                        updated_at=excluded.updated_at
                    """,
                    (
                        report_id,
                        session_id,
                        ticker,
                        title,
                        summary,
                        tags_json,
                        generated_at,
                        confidence_value,
                        trace_digest_json,
                        report_json,
                        quality_state,
                        publishable,
                        quality_reasons_json,
                        source_type,
                        filing_type,
                        publisher,
                        now,
                        now,
                    ),
                )

                conn.execute("DELETE FROM citation_index WHERE report_id = ?", (report_id,))
                seen_source_ids: set[str] = set()
                for item in report.get("citations") or []:
                    normalized_citation = _normalize_citation_item(item)
                    if not normalized_citation:
                        continue
                    source_id = _clean_text(normalized_citation.get("source_id"))
                    if source_id in seen_source_ids:
                        continue
                    seen_source_ids.add(source_id)
                    conn.execute(
                        """
                        INSERT INTO citation_index(
                            report_id, session_id, source_id, title, url, snippet,
                            published_date, confidence, citation_json, created_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            report_id,
                            session_id,
                            source_id,
                            normalized_citation.get("title"),
                            normalized_citation.get("url"),
                            normalized_citation.get("snippet"),
                            normalized_citation.get("published_date"),
                            normalized_citation.get("confidence"),
                            json.dumps(normalized_citation, ensure_ascii=False),
                            now,
                        ),
                    )

        return {"report_id": report_id, "session_id": session_id}

    def list_reports(
        self,
        *,
        session_id: str,
        ticker: str | None = None,
        query: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        tag: str | None = None,
        favorite_only: bool = False,
        source_type: str | None = None,
        include_blocked: bool = False,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT report_id, session_id, ticker, title, summary, generated_at,
                   confidence_score, is_favorite, tags_json, source_type, report_json,
                   quality_state, publishable, quality_reasons_json,
                   filing_type, publisher, created_at, updated_at
            FROM report_index
            WHERE session_id = ?
        """
        args: list[Any] = [session_id]
        if ticker:
            sql += " AND ticker = ?"
            args.append(ticker)
        if favorite_only:
            sql += " AND is_favorite = 1"
        if query:
            like = f"%{query.strip()}%"
            sql += " AND (title LIKE ? OR summary LIKE ? OR ticker LIKE ?)"
            args.extend([like, like, like])
        if date_from:
            sql += " AND generated_at >= ?"
            args.append(date_from.strip())
        if date_to:
            sql += " AND generated_at <= ?"
            args.append(date_to.strip())
        if tag:
            sql += " AND tags_json LIKE ?"
            args.append(f'%"{tag.strip()}"%')
        if source_type:
            sql += " AND source_type = ?"
            args.append(source_type.strip())
        if not include_blocked:
            sql += " AND publishable = 1"
        sql += " ORDER BY generated_at DESC LIMIT ?"
        args.append(max(1, min(500, int(limit))))

        with self._connect() as conn:
            rows = conn.execute(sql, args).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                tags = []
                if row["tags_json"]:
                    try:
                        parsed = json.loads(row["tags_json"])
                        if isinstance(parsed, list):
                            tags = parsed
                    except Exception:
                        tags = []
                report_meta = _extract_report_meta(row["report_json"])
                source_trigger = str(report_meta.get("source_trigger") or "").strip() or None
                analysis_depth = _derive_analysis_depth(
                    source_trigger=source_trigger,
                    report_meta=report_meta,
                )
                quality_reasons: list[dict[str, Any]] = []
                try:
                    parsed_reasons = json.loads(row["quality_reasons_json"] or "[]")
                    if isinstance(parsed_reasons, list):
                        quality_reasons = [item for item in parsed_reasons if isinstance(item, dict)]
                except Exception:
                    quality_reasons = []
                result.append(
                    {
                        "report_id": row["report_id"],
                        "session_id": row["session_id"],
                        "ticker": row["ticker"],
                        "title": row["title"],
                        "summary": row["summary"],
                        "generated_at": row["generated_at"],
                        "confidence_score": row["confidence_score"],
                        "is_favorite": bool(row["is_favorite"]),
                        "tags": tags,
                        "source_type": row["source_type"],
                        "quality_state": row["quality_state"] or "pass",
                        "publishable": bool(row["publishable"]),
                        "quality_reasons": quality_reasons,
                        "source_trigger": source_trigger,
                        "analysis_depth": analysis_depth,
                        "filing_type": row["filing_type"],
                        "publisher": row["publisher"],
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    }
                )
            return result

    def get_report_replay(
        self,
        *,
        session_id: str,
        report_id: str,
        include_blocked: bool = False,
    ) -> dict[str, Any] | None:
        with self._connect() as conn:
            where_clause = "WHERE session_id = ? AND report_id = ?"
            if not include_blocked:
                where_clause += " AND publishable = 1"
            row = conn.execute(
                """
                SELECT report_json, trace_digest_json
                FROM report_index
                """
                + where_clause,
                (
                    session_id,
                    report_id,
                ),
            ).fetchone()
            if not row:
                return None
            citations = conn.execute(
                """
                SELECT citation_json
                FROM citation_index
                WHERE session_id = ? AND report_id = ?
                ORDER BY row_id ASC
                """,
                (session_id, report_id),
            ).fetchall()

        report_payload = json.loads(row["report_json"])
        citation_items = []
        for item in citations:
            try:
                citation_items.append(json.loads(item["citation_json"]))
            except Exception:
                continue
        report_payload["citations"] = citation_items
        trace_digest = {}
        try:
            trace_digest = json.loads(row["trace_digest_json"] or "{}")
        except Exception:
            trace_digest = {}
        return {
            "report": report_payload,
            "trace_digest": trace_digest,
            "citations": citation_items,
        }

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
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT row_id, report_id, session_id, source_id, title, url, snippet,
                   published_date, confidence, citation_json, created_at
            FROM citation_index
            WHERE session_id = ?
        """
        args: list[Any] = [session_id]

        if report_id:
            sql += " AND report_id = ?"
            args.append(report_id)
        if source_id:
            sql += " AND source_id = ?"
            args.append(source_id.strip())
        if date_from:
            sql += " AND published_date >= ?"
            args.append(date_from.strip())
        if date_to:
            sql += " AND published_date <= ?"
            args.append(date_to.strip())
        if query:
            like = f"%{query.strip()}%"
            sql += " AND (title LIKE ? OR snippet LIKE ? OR url LIKE ? OR source_id LIKE ?)"
            args.extend([like, like, like, like])

        sql += " ORDER BY row_id DESC LIMIT ?"
        args.append(max(1, min(500, int(limit))))

        with self._connect() as conn:
            rows = conn.execute(sql, args).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                citation_payload: dict[str, Any] = {}
                try:
                    parsed = json.loads(row["citation_json"] or "{}")
                    if isinstance(parsed, dict):
                        citation_payload = parsed
                except Exception:
                    citation_payload = {}

                result.append(
                    {
                        "row_id": row["row_id"],
                        "report_id": row["report_id"],
                        "session_id": row["session_id"],
                        "source_id": row["source_id"],
                        "title": row["title"],
                        "url": row["url"],
                        "snippet": row["snippet"],
                        "published_date": row["published_date"],
                        "confidence": row["confidence"],
                        "created_at": row["created_at"],
                        "citation": citation_payload,
                    }
                )
            return result

    def set_favorite(self, *, session_id: str, report_id: str, is_favorite: bool) -> bool:
        with self._lock:
            with self._connect() as conn:
                cur = conn.execute(
                    """
                    UPDATE report_index
                    SET is_favorite = ?, updated_at = ?
                    WHERE session_id = ? AND report_id = ?
                    """,
                    (1 if is_favorite else 0, _now_iso(), session_id, report_id),
                )
                return cur.rowcount > 0


_REPORT_INDEX_STORE: ReportIndexStore | None = None


def get_report_index_store() -> ReportIndexStore:
    global _REPORT_INDEX_STORE
    if _REPORT_INDEX_STORE is None:
        _REPORT_INDEX_STORE = ReportIndexStore()
    return _REPORT_INDEX_STORE

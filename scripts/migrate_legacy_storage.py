# -*- coding: utf-8 -*-
"""把 conversation/watchlist/report 旧存储一次性迁入核心 PostgreSQL。

命令严格分离读取、导出、写入、校验和回滚。应用运行时不会导入本模块，
也不会自动触碰旧文件。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote
from uuid import UUID, uuid4

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config.ticker_mapping import normalize_ticker
from backend.services.database import (
    assert_core_schema_current,
    create_core_engine,
    resolve_core_postgres_dsn,
)


EXPORT_SCHEMA_VERSION = 1
DEFAULT_DATA_DIR = Path(os.getenv("FINSIGHT_DATA_DIR") or PROJECT_ROOT / "data")
MIGRATED_TABLES = (
    "conversation_threads",
    "watchlist_items",
    "reports",
    "report_citations",
)


class LegacyMigrationError(RuntimeError):
    """迁移输入、schema 或校验不满足安全条件。"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest_rows(rows: dict[str, list[dict[str, Any]]]) -> str:
    payload = {"schema_version": EXPORT_SCHEMA_VERSION, "rows": rows}
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


def _json_object(value: Any, fallback: Any) -> Any:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return fallback
    return value if isinstance(value, type(fallback)) else fallback


def _iso_timestamp(value: Any, *, fallback: str | None = None) -> str | None:
    if value in (None, ""):
        return fallback
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(float(value), timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return fallback
    raw = str(value).strip()
    if not raw:
        return fallback
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return fallback
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _session_owner(session_id: str) -> str | None:
    parts = str(session_id or "").strip().split(":")
    if len(parts) != 3:
        return None
    owner = parts[1].strip()
    return owner if owner and owner not in {"public", "anonymous"} else None


def _resolve_owner(raw_user: Any, session_id: str, public_user_id: str | None) -> str | None:
    owner = str(raw_user or "").strip()
    if owner and owner not in {"public", "anonymous"}:
        return owner
    return _session_owner(session_id) or (str(public_user_id or "").strip() or None)


def _owned_report_session(session_id: str, owner: str) -> str:
    parts = str(session_id or "").strip().split(":")
    if len(parts) == 3:
        parts[1] = owner
        return ":".join(parts)
    suffix = hashlib.sha256(str(session_id).encode("utf-8")).hexdigest()[:20]
    return f"legacy:{owner}:{suffix}"


def _issue(issues: list[dict[str, str]], severity: str, source: str, message: str) -> None:
    issues.append({"severity": severity, "source": source, "message": message})


def _read_conversations(
    path: Path,
    *,
    public_user_id: str | None,
    issues: list[dict[str, str]],
) -> list[dict[str, Any]]:
    if not path.exists():
        _issue(issues, "warning", "conversations", f"旧文件不存在: {path}")
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _issue(issues, "blocker", "conversations", f"旧 JSON 无法读取: {exc}")
        return []
    records = payload.get("conversations") if isinstance(payload, dict) else None
    if not isinstance(records, dict):
        _issue(issues, "blocker", "conversations", "缺少 conversations 对象")
        return []

    now = _utc_now()
    result: list[dict[str, Any]] = []
    for source_key, raw in records.items():
        if not isinstance(raw, dict):
            _issue(issues, "warning", "conversations", f"跳过非对象记录: {source_key}")
            continue
        session_id = str(raw.get("session_id") or source_key).split("\x1f")[-1].strip()
        owner = _resolve_owner(raw.get("user_id"), session_id, public_user_id)
        if not session_id or not owner:
            _issue(
                issues,
                "blocker",
                "conversations",
                f"记录 {source_key} 无法确定认证 user_id；请提供 --public-user-id",
            )
            continue
        messages = [item for item in raw.get("messages") or [] if isinstance(item, dict)][-200:]
        created_at = _iso_timestamp(raw.get("created_at"), fallback=now) or now
        updated_at = _iso_timestamp(raw.get("updated_at"), fallback=created_at) or created_at
        result.append(
            {
                "user_id": owner,
                "session_id": session_id,
                "title": str(raw.get("title") or "新对话").strip()[:80] or "新对话",
                "messages": messages,
                "message_count": len(messages),
                "last_message_preview": str(raw.get("last_message_preview") or "")[:90],
                "pinned": bool(raw.get("pinned")),
                "archived": bool(raw.get("archived")),
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )
    return result


def _sqlite_rows(path: Path, table: str, issues: list[dict[str, str]]) -> list[dict[str, Any]]:
    if not path.exists():
        _issue(issues, "warning", table, f"旧数据库不存在: {path}")
        return []
    try:
        with sqlite3.connect(str(path)) as conn:
            conn.row_factory = sqlite3.Row
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
            ).fetchone()
            if not exists:
                _issue(issues, "warning", table, f"旧数据库中不存在表 {table}")
                return []
            return [dict(row) for row in conn.execute(f'SELECT * FROM "{table}"').fetchall()]
    except sqlite3.Error as exc:
        _issue(issues, "blocker", table, f"旧 SQLite 无法读取: {exc}")
        return []


def _read_watchlist(
    path: Path,
    *,
    public_user_id: str | None,
    issues: list[dict[str, str]],
) -> list[dict[str, Any]]:
    now = _utc_now()
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(_sqlite_rows(path, "watchlist", issues), start=1):
        owner = _resolve_owner(raw.get("user_id"), "", public_user_id)
        ticker = normalize_ticker(str(raw.get("ticker") or "").strip())
        if not owner:
            _issue(
                issues,
                "blocker",
                "watchlist",
                f"第 {index} 行无法确定认证 user_id；请提供 --public-user-id",
            )
            continue
        if not ticker:
            _issue(issues, "warning", "watchlist", f"第 {index} 行 ticker 无效，已跳过")
            continue
        result.append(
            {
                "user_id": owner,
                "ticker": ticker,
                "note": str(raw.get("note") or "").strip(),
                "added_at": _iso_timestamp(raw.get("added_at"), fallback=now) or now,
            }
        )
    return result


def _citation_source_id(citation: dict[str, Any]) -> str:
    existing = str(citation.get("source_id") or "").strip()
    if existing:
        return existing[:256]
    seed = "|".join(
        str(citation.get(key) or "").strip()
        for key in ("url", "title", "published_date", "snippet")
    )
    return "legacy-" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _read_reports(
    path: Path,
    *,
    public_user_id: str | None,
    issues: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    now = _utc_now()
    reports: list[dict[str, Any]] = []
    owners: dict[str, tuple[str, str]] = {}
    for index, raw in enumerate(_sqlite_rows(path, "report_index", issues), start=1):
        report_id = str(raw.get("report_id") or "").strip()
        original_session = str(raw.get("session_id") or "").strip()
        owner = _resolve_owner(None, original_session, public_user_id)
        if not report_id or not owner:
            reason = "report_id 缺失" if not report_id else "无法确定认证 user_id"
            _issue(issues, "blocker", "report_index", f"第 {index} 行{reason}，已跳过")
            continue
        session_id = _owned_report_session(original_session, owner)
        report = _json_object(raw.get("report_json"), {})
        trace_digest = _json_object(raw.get("trace_digest_json"), {})
        tags = _json_object(raw.get("tags_json"), [])
        quality_reasons = _json_object(raw.get("quality_reasons_json"), [])
        generated_at = _iso_timestamp(raw.get("generated_at"), fallback=None)
        created_at = _iso_timestamp(raw.get("created_at"), fallback=now) or now
        updated_at = _iso_timestamp(raw.get("updated_at"), fallback=created_at) or created_at
        reports.append(
            {
                "report_id": report_id,
                "user_id": owner,
                "session_id": session_id,
                "ticker": str(raw.get("ticker") or "").strip() or None,
                "title": str(raw.get("title") or "").strip() or None,
                "summary": str(raw.get("summary") or "").strip() or None,
                "tags": tags,
                "generated_at": generated_at,
                "confidence_score": raw.get("confidence_score"),
                "is_favorite": bool(raw.get("is_favorite")),
                "trace_digest": trace_digest,
                "report": report,
                "quality_state": str(raw.get("quality_state") or "pass"),
                "publishable": bool(raw.get("publishable", 1)),
                "quality_reasons": quality_reasons,
                "source_type": str(raw.get("source_type") or "ai_generated"),
                "filing_type": str(raw.get("filing_type") or "").strip() or None,
                "publisher": str(raw.get("publisher") or "").strip() or None,
                "share_token": str(raw.get("share_token") or "").strip() or None,
                "shared_at": _iso_timestamp(raw.get("shared_at"), fallback=None),
                "created_at": created_at,
                "updated_at": updated_at,
            }
        )
        owners[report_id] = (owner, session_id)

    citations: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for raw in _sqlite_rows(path, "citation_index", issues):
        report_id = str(raw.get("report_id") or "").strip()
        owner_info = owners.get(report_id)
        if owner_info is None:
            _issue(issues, "warning", "citation_index", f"引用所属报告不存在: {report_id}")
            continue
        citation = _json_object(raw.get("citation_json"), {})
        source_id = _citation_source_id({**citation, **raw})
        key = (report_id, source_id)
        if key in seen:
            continue
        seen.add(key)
        owner, session_id = owner_info
        citations.append(
            {
                "report_id": report_id,
                "user_id": owner,
                "session_id": session_id,
                "source_id": source_id,
                "title": str(raw.get("title") or citation.get("title") or "").strip() or None,
                "url": str(raw.get("url") or citation.get("url") or "").strip() or None,
                "snippet": str(raw.get("snippet") or citation.get("snippet") or "").strip() or None,
                "published_date": str(
                    raw.get("published_date") or citation.get("published_date") or ""
                ).strip() or None,
                "confidence": raw.get("confidence"),
                "citation": citation,
                "created_at": _iso_timestamp(raw.get("created_at"), fallback=now) or now,
            }
        )
    return reports, citations


def build_snapshot(
    *,
    conversation_path: Path,
    watchlist_path: Path,
    report_path: Path,
    public_user_id: str | None = None,
) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    reports, citations = _read_reports(
        report_path,
        public_user_id=public_user_id,
        issues=issues,
    )
    rows = {
        "conversation_threads": _read_conversations(
            conversation_path,
            public_user_id=public_user_id,
            issues=issues,
        ),
        "watchlist_items": _read_watchlist(
            watchlist_path,
            public_user_id=public_user_id,
            issues=issues,
        ),
        "reports": reports,
        "report_citations": citations,
    }
    return {
        "schema_version": EXPORT_SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "source_digest": _digest_rows(rows),
        "counts": {name: len(items) for name, items in rows.items()},
        "issues": issues,
        "rows": rows,
    }


def _validate_snapshot(snapshot: dict[str, Any], *, allow_skips: bool = False) -> None:
    if snapshot.get("schema_version") != EXPORT_SCHEMA_VERSION:
        raise LegacyMigrationError("不支持的导出 schema_version")
    rows = snapshot.get("rows")
    if not isinstance(rows, dict) or any(
        not isinstance(rows.get(name), list) for name in MIGRATED_TABLES
    ):
        raise LegacyMigrationError("导出文件缺少完整 rows")
    digest = _digest_rows({name: rows[name] for name in MIGRATED_TABLES})
    if digest != snapshot.get("source_digest"):
        raise LegacyMigrationError("导出文件摘要不匹配，文件可能被修改")
    blockers = [
        item
        for item in snapshot.get("issues") or []
        if isinstance(item, dict) and item.get("severity") == "blocker"
    ]
    if blockers and not allow_skips:
        raise LegacyMigrationError("导出包含未解决 blocker；请修复来源或显式使用 --allow-skips")


def write_snapshot(snapshot: dict[str, Any], output: Path, *, allow_skips: bool = False) -> None:
    _validate_snapshot(snapshot, allow_skips=allow_skips)
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_suffix(output.suffix + ".tmp")
    temp.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, output)


def read_snapshot(path: Path, *, allow_skips: bool = False) -> dict[str, Any]:
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LegacyMigrationError(f"无法读取导出文件: {exc}") from exc
    if not isinstance(snapshot, dict):
        raise LegacyMigrationError("导出文件根节点必须是对象")
    _validate_snapshot(snapshot, allow_skips=allow_skips)
    return snapshot


def _rowcount(result: Any) -> int:
    return max(0, int(getattr(result, "rowcount", 0) or 0))


def import_snapshot(
    snapshot: dict[str, Any],
    *,
    engine: Any,
    allow_skips: bool = False,
) -> dict[str, Any]:
    _validate_snapshot(snapshot, allow_skips=allow_skips)
    assert_core_schema_current(engine=engine)
    digest = str(snapshot["source_digest"])
    batch_id = str(uuid4())
    inserted = {name: 0 for name in MIGRATED_TABLES}
    with engine.begin() as conn:
        existing = conn.execute(
            text(
                "SELECT id,status,row_counts FROM legacy_import_batches "
                "WHERE source_digest=:source_digest"
            ),
            {"source_digest": digest},
        ).mappings().first()
        if existing and str(existing["status"]) == "imported":
            return {
                "batch_id": str(existing["id"]),
                "source_digest": digest,
                "status": "imported",
                "idempotent": True,
                "row_counts": _json_object(existing.get("row_counts"), {}),
            }
        if existing:
            batch_id = str(existing["id"])
            conn.execute(
                text(
                    "UPDATE legacy_import_batches SET status='importing',completed_at=NULL "
                    "WHERE id=CAST(:batch_id AS uuid)"
                ),
                {"batch_id": batch_id},
            )
        else:
            conn.execute(
                text(
                    "INSERT INTO legacy_import_batches(id,source_digest,status,row_counts) "
                    "VALUES (CAST(:batch_id AS uuid),:source_digest,'importing','{}'::jsonb)"
                ),
                {"batch_id": batch_id, "source_digest": digest},
            )

        for row in snapshot["rows"]["conversation_threads"]:
            result = conn.execute(
                text(
                    "INSERT INTO conversation_threads(user_id,session_id,title,messages,message_count,"
                    "last_message_preview,pinned,archived,migration_batch_id,created_at,updated_at) "
                    "VALUES (:user_id,:session_id,:title,CAST(:messages AS jsonb),:message_count,"
                    ":last_message_preview,:pinned,:archived,CAST(:batch_id AS uuid),"
                    "CAST(:created_at AS timestamptz),CAST(:updated_at AS timestamptz)) "
                    "ON CONFLICT(user_id,session_id) DO NOTHING"
                ),
                {**row, "messages": _canonical_json(row["messages"]), "batch_id": batch_id},
            )
            inserted["conversation_threads"] += _rowcount(result)

        for row in snapshot["rows"]["watchlist_items"]:
            result = conn.execute(
                text(
                    "INSERT INTO watchlist_items(user_id,ticker,note,migration_batch_id,added_at) "
                    "VALUES (:user_id,:ticker,:note,CAST(:batch_id AS uuid),CAST(:added_at AS timestamptz)) "
                    "ON CONFLICT(user_id,ticker) DO NOTHING"
                ),
                {**row, "batch_id": batch_id},
            )
            inserted["watchlist_items"] += _rowcount(result)

        for row in snapshot["rows"]["reports"]:
            params = {
                **row,
                "tags": _canonical_json(row["tags"]),
                "trace_digest": _canonical_json(row["trace_digest"]),
                "report": _canonical_json(row["report"]),
                "quality_reasons": _canonical_json(row["quality_reasons"]),
                "batch_id": batch_id,
            }
            result = conn.execute(
                text(
                    "INSERT INTO reports(report_id,user_id,session_id,ticker,title,summary,tags,generated_at,"
                    "confidence_score,is_favorite,trace_digest,report,quality_state,publishable,quality_reasons,"
                    "source_type,filing_type,publisher,share_token,shared_at,migration_batch_id,created_at,updated_at) "
                    "VALUES (:report_id,:user_id,:session_id,:ticker,:title,:summary,CAST(:tags AS jsonb),"
                    "CAST(:generated_at AS timestamptz),:confidence_score,:is_favorite,CAST(:trace_digest AS jsonb),"
                    "CAST(:report AS jsonb),:quality_state,:publishable,CAST(:quality_reasons AS jsonb),:source_type,"
                    ":filing_type,:publisher,:share_token,CAST(:shared_at AS timestamptz),CAST(:batch_id AS uuid),"
                    "CAST(:created_at AS timestamptz),CAST(:updated_at AS timestamptz)) "
                    "ON CONFLICT(report_id) DO NOTHING"
                ),
                params,
            )
            inserted["reports"] += _rowcount(result)

        for row in snapshot["rows"]["report_citations"]:
            result = conn.execute(
                text(
                    "INSERT INTO report_citations(report_id,user_id,session_id,source_id,title,url,snippet,"
                    "published_date,confidence,citation,migration_batch_id,created_at) "
                    "SELECT :report_id,:user_id,:session_id,:source_id,:title,:url,:snippet,:published_date,"
                    ":confidence,CAST(:citation AS jsonb),CAST(:batch_id AS uuid),CAST(:created_at AS timestamptz) "
                    "WHERE EXISTS (SELECT 1 FROM reports WHERE report_id=:report_id AND user_id=:user_id) "
                    "ON CONFLICT(report_id,source_id) DO NOTHING"
                ),
                {**row, "citation": _canonical_json(row["citation"]), "batch_id": batch_id},
            )
            inserted["report_citations"] += _rowcount(result)

        row_counts = {"source": snapshot["counts"], "inserted": inserted}
        conn.execute(
            text(
                "UPDATE legacy_import_batches SET status='imported',row_counts=CAST(:row_counts AS jsonb),"
                "completed_at=now() WHERE id=CAST(:batch_id AS uuid)"
            ),
            {"row_counts": _canonical_json(row_counts), "batch_id": batch_id},
        )
    return {
        "batch_id": batch_id,
        "source_digest": digest,
        "status": "imported",
        "idempotent": False,
        "row_counts": {"source": snapshot["counts"], "inserted": inserted},
    }


def _batch_row(conn: Any, batch_id: str) -> dict[str, Any]:
    try:
        UUID(batch_id)
    except ValueError as exc:
        raise LegacyMigrationError("batch id 必须是 UUID") from exc
    row = conn.execute(
        text(
            "SELECT id,source_digest,status,row_counts,created_at,completed_at "
            "FROM legacy_import_batches WHERE id=CAST(:batch_id AS uuid)"
        ),
        {"batch_id": batch_id},
    ).mappings().first()
    if not row:
        raise LegacyMigrationError("迁移批次不存在")
    return dict(row)


def verify_batch(*, engine: Any, batch_id: str) -> dict[str, Any]:
    assert_core_schema_current(engine=engine)
    with engine.connect() as conn:
        batch = _batch_row(conn, batch_id)
        row_counts = _json_object(batch.get("row_counts"), {})
        expected = row_counts.get("inserted") if isinstance(row_counts, dict) else {}
        actual: dict[str, int] = {}
        for table in MIGRATED_TABLES:
            actual[table] = int(
                conn.execute(
                    text(
                        f"SELECT COUNT(*) FROM {table} "
                        "WHERE migration_batch_id=CAST(:batch_id AS uuid)"
                    ),
                    {"batch_id": batch_id},
                ).scalar_one()
            )
    verified = str(batch["status"]) == "imported" and expected == actual
    return {
        "batch_id": batch_id,
        "source_digest": batch["source_digest"],
        "status": batch["status"],
        "expected_inserted": expected,
        "actual_inserted": actual,
        "verified": verified,
    }


def rollback_batch(*, engine: Any, batch_id: str) -> dict[str, Any]:
    assert_core_schema_current(engine=engine)
    deleted: dict[str, int] = {}
    with engine.begin() as conn:
        batch = _batch_row(conn, batch_id)
        if str(batch["status"]) == "rolled_back":
            return {
                "batch_id": batch_id,
                "status": "rolled_back",
                "idempotent": True,
                "deleted": _json_object(batch.get("row_counts"), {}).get("rolled_back", {}),
            }
        for table in ("report_citations", "reports", "watchlist_items", "conversation_threads"):
            result = conn.execute(
                text(f"DELETE FROM {table} WHERE migration_batch_id=CAST(:batch_id AS uuid)"),
                {"batch_id": batch_id},
            )
            deleted[table] = _rowcount(result)
        row_counts = _json_object(batch.get("row_counts"), {})
        row_counts["rolled_back"] = deleted
        conn.execute(
            text(
                "UPDATE legacy_import_batches SET status='rolled_back',"
                "row_counts=CAST(:row_counts AS jsonb),completed_at=now() "
                "WHERE id=CAST(:batch_id AS uuid)"
            ),
            {"batch_id": batch_id, "row_counts": _canonical_json(row_counts)},
        )
    return {"batch_id": batch_id, "status": "rolled_back", "idempotent": False, "deleted": deleted}


def _print_json(value: Any) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _source_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--conversation-path",
        type=Path,
        default=Path(os.getenv("CONVERSATION_STORE_PATH") or DEFAULT_DATA_DIR / "conversations.json"),
    )
    parser.add_argument(
        "--watchlist-path",
        type=Path,
        default=DEFAULT_DATA_DIR / "watchlist.db",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=Path(os.getenv("REPORT_INDEX_SQLITE_PATH") or DEFAULT_DATA_DIR / "report_index.sqlite"),
    )
    parser.add_argument(
        "--public-user-id",
        help="把旧 public/anonymous 行明确归属到该认证用户；不提供时将其列为 blocker",
    )
    parser.add_argument("--allow-skips", action="store_true", help="显式允许跳过无法归属的旧行")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    dry_run = commands.add_parser("dry-run", help="只读扫描旧存储并输出摘要")
    _source_arguments(dry_run)
    export = commands.add_parser("export", help="把旧存储导出为带摘要的 JSON")
    _source_arguments(export)
    export.add_argument("--output", type=Path, required=True)
    import_cmd = commands.add_parser("import", help="把导出 JSON 幂等写入已迁移的 PostgreSQL")
    import_cmd.add_argument("--input", type=Path, required=True)
    import_cmd.add_argument("--allow-skips", action="store_true")
    import_cmd.add_argument("--dsn", help="覆盖 FINSIGHT_POSTGRES_DSN")
    verify = commands.add_parser("verify", help="校验迁移批次实际行数")
    verify.add_argument("--batch-id", required=True)
    verify.add_argument("--dsn", help="覆盖 FINSIGHT_POSTGRES_DSN")
    rollback = commands.add_parser("rollback", help="只回滚指定批次插入的数据")
    rollback.add_argument("--batch-id", required=True)
    rollback.add_argument("--dsn", help="覆盖 FINSIGHT_POSTGRES_DSN")
    return parser


def _snapshot_from_args(args: argparse.Namespace) -> dict[str, Any]:
    return build_snapshot(
        conversation_path=args.conversation_path,
        watchlist_path=args.watchlist_path,
        report_path=args.report_path,
        public_user_id=args.public_user_id,
    )


def _engine(dsn: str | None) -> Any:
    value = dsn or resolve_core_postgres_dsn(required=False)
    if not value:
        user = str(os.getenv("PGUSER") or "").strip()
        password = os.getenv("PGPASSWORD") or ""
        host = str(os.getenv("PGHOST") or "").strip()
        port = str(os.getenv("PGPORT") or "5432").strip()
        database = str(os.getenv("PGDATABASE") or "").strip()
        if user and host and database:
            value = (
                f"postgresql+psycopg://{quote(user, safe='')}:{quote(password, safe='')}"
                f"@{host}:{port}/{quote(database, safe='')}"
            )
    if not value:
        value = resolve_core_postgres_dsn(required=True)
    return create_core_engine(dsn=value)


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        if args.command == "dry-run":
            snapshot = _snapshot_from_args(args)
            _print_json({key: snapshot[key] for key in ("source_digest", "counts", "issues")})
            blockers = any(item.get("severity") == "blocker" for item in snapshot["issues"])
            return 0 if not blockers or args.allow_skips else 2
        if args.command == "export":
            snapshot = _snapshot_from_args(args)
            write_snapshot(snapshot, args.output, allow_skips=args.allow_skips)
            _print_json(
                {
                    "output": str(args.output.resolve()),
                    "source_digest": snapshot["source_digest"],
                    "counts": snapshot["counts"],
                    "issues": snapshot["issues"],
                }
            )
            return 0
        if args.command == "import":
            snapshot = read_snapshot(args.input, allow_skips=args.allow_skips)
            _print_json(
                import_snapshot(
                    snapshot,
                    engine=_engine(args.dsn),
                    allow_skips=args.allow_skips,
                )
            )
            return 0
        if args.command == "verify":
            result = verify_batch(engine=_engine(args.dsn), batch_id=args.batch_id)
            _print_json(result)
            return 0 if result["verified"] else 3
        if args.command == "rollback":
            _print_json(rollback_batch(engine=_engine(args.dsn), batch_id=args.batch_id))
            return 0
    except LegacyMigrationError as exc:
        print(f"legacy migration error: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

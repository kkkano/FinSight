# -*- coding: utf-8 -*-
"""
工作台 Phase 1：盯盘数据层存储（Finding + MonitorTarget）。

使用独立 SQLite 库 ``data/monitor.db``，与 portfolio.db / checkpointer 库分离，
避免锁竞争与迁移耦合。模式与 portfolio_store 一致：WAL + 主键 + session 隔离。

数据形态：
  Finding        —— 一条盯盘发现（价格异动 / 集中度 / 预留情绪/财报/宏观）
  MonitorTarget  —— 盯盘标的及其阈值配置（持仓 / 关注 / 自定义）

JSON 字段（trigger_detail / actions / config / agent_analysis）以 TEXT 落库。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DEFAULT_DB_DIR = Path(os.getenv("FINSIGHT_DATA_DIR", "data"))
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "monitor.db"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _loads(raw: str | None, fallback: Any) -> Any:
    """安全解析 JSON TEXT 列，失败回退默认值。"""
    if raw is None:
        return fallback
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return fallback


class MonitorStore:
    """Finding + MonitorTarget 的 SQLite 存储。

    支持注入 ``db_path``（测试用 tmp_path），默认落 ``data/monitor.db``。
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = Path(db_path) if db_path else _DEFAULT_DB_PATH
        self._conn: sqlite3.Connection | None = None

    # ── 连接管理 ──────────────────────────────────────────────

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._conn = conn
            self._ensure_tables(conn)
        return self._conn

    @staticmethod
    def _ensure_tables(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS findings (
                id              TEXT PRIMARY KEY,
                session_id      TEXT NOT NULL,
                created_at      TEXT NOT NULL,
                target          TEXT NOT NULL,
                trigger_type    TEXT NOT NULL,
                trigger_detail  TEXT,
                title           TEXT,
                summary         TEXT,
                agent_analysis  TEXT,
                actions         TEXT,
                status          TEXT NOT NULL DEFAULT 'new'
            );

            CREATE INDEX IF NOT EXISTS idx_findings_session
                ON findings(session_id, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_findings_dedup
                ON findings(session_id, target, trigger_type, created_at DESC);

            CREATE TABLE IF NOT EXISTS monitor_targets (
                id          TEXT PRIMARY KEY,
                session_id  TEXT NOT NULL,
                type        TEXT NOT NULL,
                ticker      TEXT,
                config      TEXT,
                enabled     INTEGER NOT NULL DEFAULT 1,
                created_at  TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_targets_session
                ON monitor_targets(session_id);
            """
        )
        conn.commit()

    # ── Finding ───────────────────────────────────────────────

    def insert_finding(self, finding: dict[str, Any]) -> None:
        """插入一条 Finding（id 由调用方提供，uuid4 hex）。"""
        self._db().execute(
            """INSERT INTO findings
               (id, session_id, created_at, target, trigger_type, trigger_detail,
                title, summary, agent_analysis, actions, status)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                finding["id"],
                finding["session_id"],
                finding.get("created_at") or _now_iso(),
                finding["target"],
                finding["trigger_type"],
                json.dumps(finding.get("trigger_detail") or {}, ensure_ascii=False),
                finding.get("title", ""),
                finding.get("summary", ""),
                json.dumps(finding["agent_analysis"], ensure_ascii=False)
                if finding.get("agent_analysis") is not None
                else None,
                json.dumps(finding.get("actions") or [], ensure_ascii=False),
                finding.get("status", "new"),
            ),
        )
        self._db().commit()

    def list_findings(
        self, session_id: str, status: str | None = None, limit: int = 50
    ) -> list[dict[str, Any]]:
        """按 created_at 倒序返回 session 的 findings，可按 status 过滤。"""
        sql = (
            "SELECT id, session_id, created_at, target, trigger_type, trigger_detail, "
            "title, summary, agent_analysis, actions, status FROM findings WHERE session_id = ?"
        )
        params: list[Any] = [session_id]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        rows = self._db().execute(sql, params).fetchall()
        return [self._row_to_finding(r) for r in rows]

    @staticmethod
    def _row_to_finding(r: tuple) -> dict[str, Any]:
        return {
            "id": r[0],
            "session_id": r[1],
            "created_at": r[2],
            "target": r[3],
            "trigger_type": r[4],
            "trigger_detail": _loads(r[5], {}),
            "title": r[6],
            "summary": r[7],
            "agent_analysis": _loads(r[8], None),
            "actions": _loads(r[9], []),
            "status": r[10],
        }

    def update_finding_status(self, session_id: str, finding_id: str, status: str) -> bool:
        """更新指定 finding 的状态；session 隔离，跨 session 不可改。"""
        cursor = self._db().execute(
            "UPDATE findings SET status = ? WHERE id = ? AND session_id = ?",
            (status, finding_id, session_id),
        )
        self._db().commit()
        return cursor.rowcount > 0

    def has_recent_finding(
        self, session_id: str, target: str, trigger_type: str, within_hours: int = 4
    ) -> bool:
        """去重：同 session 同标的同类型在 within_hours 窗口内是否已有 finding。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=within_hours)).isoformat()
        row = self._db().execute(
            """SELECT 1 FROM findings
               WHERE session_id = ? AND target = ? AND trigger_type = ? AND created_at >= ?
               LIMIT 1""",
            (session_id, target, trigger_type, cutoff),
        ).fetchone()
        return row is not None

    def cleanup_old_findings(self, days: int = 30) -> int:
        """清理超过 days 天的 findings，返回删除条数。"""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        cursor = self._db().execute(
            "DELETE FROM findings WHERE created_at < ?", (cutoff,)
        )
        self._db().commit()
        return cursor.rowcount

    # ── MonitorTarget ─────────────────────────────────────────

    def list_targets(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._db().execute(
            """SELECT id, session_id, type, ticker, config, enabled, created_at
               FROM monitor_targets WHERE session_id = ? ORDER BY created_at""",
            (session_id,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "session_id": r[1],
                "type": r[2],
                "ticker": r[3],
                "config": _loads(r[4], {}),
                "enabled": bool(r[5]),
                "created_at": r[6],
            }
            for r in rows
        ]

    def upsert_target(self, target: dict[str, Any]) -> None:
        """按 id upsert 一个 MonitorTarget。"""
        self._db().execute(
            """INSERT INTO monitor_targets (id, session_id, type, ticker, config, enabled, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(id) DO UPDATE SET
                   type=excluded.type,
                   ticker=excluded.ticker,
                   config=excluded.config,
                   enabled=excluded.enabled""",
            (
                target["id"],
                target["session_id"],
                target.get("type", "custom"),
                target.get("ticker"),
                json.dumps(target.get("config") or {}, ensure_ascii=False),
                1 if target.get("enabled", True) else 0,
                target.get("created_at") or _now_iso(),
            ),
        )
        self._db().commit()

    def delete_target(self, session_id: str, target_id: str) -> bool:
        """删除 target；session 隔离。返回是否实际删除。"""
        cursor = self._db().execute(
            "DELETE FROM monitor_targets WHERE id = ? AND session_id = ?",
            (target_id, session_id),
        )
        self._db().commit()
        return cursor.rowcount > 0


# ── 全局单例 ──────────────────────────────────────────────────

_STORE: MonitorStore | None = None


def get_monitor_store() -> MonitorStore:
    """返回进程级单例。路径优先读 MONITOR_DB_PATH 环境变量（测试用）。"""
    global _STORE
    if _STORE is None:
        _STORE = MonitorStore(db_path=os.getenv("MONITOR_DB_PATH"))
    return _STORE


__all__ = ["MonitorStore", "get_monitor_store"]

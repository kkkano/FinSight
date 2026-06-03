# -*- coding: utf-8 -*-
"""
P2-7：LLM 调用成本审计存储。

公网部署每次报告生成都消耗 LLM token，此前成本只有内存计数（``TokenUsageAccumulator``），
请求结束即丢失，滥用发生后无法回溯审计。本模块将每次请求的 token/成本汇总持久化到
独立 SQLite 库 ``data/cost_audit.db``（与 portfolio.db / monitor.db / checkpointer 分离，
避免锁竞争），并提供按天汇总 / Top 消耗查询 / 过期清理。

模式与 ``monitor_store`` 一致：WAL + 单例 getter + 构造函数支持注入 db_path（测试 tmp）。

数据来源：``TokenUsageAccumulator.summary()``，形如::

    {
        "total_prompt_tokens": int,
        "total_completion_tokens": int,
        "total_tokens": int,
        "llm_token_calls": int,
        "total_cost_usd": float,
        "tokens_by_model": {model: {"prompt", "completion", "calls"}},
    }

设计原则：审计写入失败绝不能影响主请求流程（调用方用 try/except 包裹）。
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
_DEFAULT_DB_PATH = _DEFAULT_DB_DIR / "cost_audit.db"

# 允许的来源枚举（未知来源归一为 other，避免脏数据污染分组统计）。
_KNOWN_SOURCES = {"chat", "report", "monitor_l2", "dashboard", "execute_run", "execute_resume", "other"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_source(source: str | None) -> str:
    raw = str(source or "").strip().lower()
    if not raw:
        return "other"
    return raw if raw in _KNOWN_SOURCES else "other"


def _safe_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


class CostAuditStore:
    """LLM 调用成本审计存储（SQLite ``data/cost_audit.db``）。

    表 ``cost_records``::

        id              自增主键
        created_at      ISO8601（UTC）落库时间
        session_id      请求 / 线程标识
        source          chat | report | monitor_l2 | dashboard | other
        total_tokens / prompt_tokens / completion_tokens
        llm_calls       本次请求的 LLM 调用次数
        cost_usd        估算成本（USD）
        model_breakdown 按模型明细（JSON TEXT）

    支持注入 ``db_path``（测试用 tmp_path），默认落 ``data/cost_audit.db``。
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
            self._conn = conn
            self._ensure_tables(conn)
        return self._conn

    @staticmethod
    def _ensure_tables(conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cost_records (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at        TEXT NOT NULL,
                session_id        TEXT NOT NULL,
                source            TEXT NOT NULL DEFAULT 'other',
                total_tokens      INTEGER NOT NULL DEFAULT 0,
                prompt_tokens     INTEGER NOT NULL DEFAULT 0,
                completion_tokens INTEGER NOT NULL DEFAULT 0,
                llm_calls         INTEGER NOT NULL DEFAULT 0,
                cost_usd          REAL NOT NULL DEFAULT 0.0,
                model_breakdown   TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_cost_created
                ON cost_records(created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_cost_source
                ON cost_records(source, created_at DESC);
            """
        )
        conn.commit()

    # ── 写入 ──────────────────────────────────────────────────

    def record(self, *, session_id: str, source: str | None, summary: dict[str, Any]) -> None:
        """记录一次请求的成本汇总。

        ``summary`` 来自 ``TokenUsageAccumulator.summary()``。空请求（0 token 且 0 调用）
        跳过不落库，避免噪声。本方法在调用方已用 try/except 包裹，但内部仍做防御。
        """
        total_tokens = _safe_int(summary.get("total_tokens"))
        llm_calls = _safe_int(summary.get("llm_token_calls"))
        if total_tokens <= 0 and llm_calls <= 0:
            return

        prompt_tokens = _safe_int(summary.get("total_prompt_tokens"))
        completion_tokens = _safe_int(summary.get("total_completion_tokens"))
        cost_usd = _safe_float(summary.get("total_cost_usd"))
        breakdown = summary.get("tokens_by_model") or {}

        self._db().execute(
            """INSERT INTO cost_records
               (created_at, session_id, source, total_tokens, prompt_tokens,
                completion_tokens, llm_calls, cost_usd, model_breakdown)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                _now_iso(),
                str(session_id or "unknown"),
                _normalize_source(source),
                total_tokens,
                prompt_tokens,
                completion_tokens,
                llm_calls,
                round(cost_usd, 6),
                json.dumps(breakdown, ensure_ascii=False) if breakdown else None,
            ),
        )
        self._db().commit()

    # ── 查询 ──────────────────────────────────────────────────

    def _window_cutoff(self, days: int) -> str:
        safe_days = max(1, _safe_int(days) or 7)
        return (datetime.now(timezone.utc) - timedelta(days=safe_days)).isoformat()

    def daily_summary(self, days: int = 7) -> list[dict[str, Any]]:
        """按天汇总最近 ``days`` 天的成本。

        返回按日期升序的列表::

            [{"date", "total_tokens", "total_cost_usd", "request_count",
              "by_source": {source: {"tokens", "cost_usd", "count"}}}]
        """
        cutoff = self._window_cutoff(days)
        rows = self._db().execute(
            """SELECT substr(created_at, 1, 10) AS day, source,
                      SUM(total_tokens), SUM(cost_usd), COUNT(*)
               FROM cost_records
               WHERE created_at >= ?
               GROUP BY day, source
               ORDER BY day ASC""",
            (cutoff,),
        ).fetchall()

        by_day: dict[str, dict[str, Any]] = {}
        for day, source, tokens, cost, count in rows:
            entry = by_day.setdefault(
                day,
                {
                    "date": day,
                    "total_tokens": 0,
                    "total_cost_usd": 0.0,
                    "request_count": 0,
                    "by_source": {},
                },
            )
            tokens_i = _safe_int(tokens)
            cost_f = _safe_float(cost)
            count_i = _safe_int(count)
            entry["total_tokens"] += tokens_i
            entry["total_cost_usd"] = round(entry["total_cost_usd"] + cost_f, 6)
            entry["request_count"] += count_i
            entry["by_source"][source] = {
                "tokens": tokens_i,
                "cost_usd": round(cost_f, 6),
                "count": count_i,
            }

        return [by_day[day] for day in sorted(by_day.keys())]

    def top_requests(self, days: int = 7, limit: int = 20) -> list[dict[str, Any]]:
        """返回最近 ``days`` 天内 token 消耗最高的请求（降序）。"""
        cutoff = self._window_cutoff(days)
        safe_limit = max(1, min(_safe_int(limit) or 20, 200))
        rows = self._db().execute(
            """SELECT id, created_at, session_id, source, total_tokens,
                      prompt_tokens, completion_tokens, llm_calls, cost_usd, model_breakdown
               FROM cost_records
               WHERE created_at >= ?
               ORDER BY total_tokens DESC, id DESC
               LIMIT ?""",
            (cutoff, safe_limit),
        ).fetchall()
        return [self._row_to_request(r) for r in rows]

    def totals(self, days: int = 7) -> dict[str, Any]:
        """返回最近 ``days`` 天的总成本 / 总 token / 请求数汇总卡片数据。"""
        cutoff = self._window_cutoff(days)
        row = self._db().execute(
            """SELECT COALESCE(SUM(total_tokens), 0), COALESCE(SUM(cost_usd), 0.0), COUNT(*)
               FROM cost_records WHERE created_at >= ?""",
            (cutoff,),
        ).fetchone()
        return {
            "total_tokens": _safe_int(row[0]),
            "total_cost_usd": round(_safe_float(row[1]), 6),
            "request_count": _safe_int(row[2]),
        }

    @staticmethod
    def _row_to_request(r: tuple) -> dict[str, Any]:
        breakdown: Any = {}
        if r[9]:
            try:
                breakdown = json.loads(r[9])
            except (json.JSONDecodeError, TypeError):
                breakdown = {}
        return {
            "id": r[0],
            "created_at": r[1],
            "session_id": r[2],
            "source": r[3],
            "total_tokens": _safe_int(r[4]),
            "prompt_tokens": _safe_int(r[5]),
            "completion_tokens": _safe_int(r[6]),
            "llm_calls": _safe_int(r[7]),
            "cost_usd": round(_safe_float(r[8]), 6),
            "model_breakdown": breakdown,
        }

    # ── 维护 ──────────────────────────────────────────────────

    def cleanup(self, keep_days: int = 90) -> int:
        """删除超过 ``keep_days`` 天的记录，返回删除条数。"""
        safe_keep = max(1, _safe_int(keep_days) or 90)
        cutoff = (datetime.now(timezone.utc) - timedelta(days=safe_keep)).isoformat()
        cursor = self._db().execute(
            "DELETE FROM cost_records WHERE created_at < ?", (cutoff,)
        )
        self._db().commit()
        return cursor.rowcount


# ── 全局单例 ──────────────────────────────────────────────────

_STORE: CostAuditStore | None = None


def get_cost_audit_store() -> CostAuditStore:
    """返回进程级单例。路径优先读 COST_AUDIT_DB_PATH 环境变量（测试用）。"""
    global _STORE
    if _STORE is None:
        _STORE = CostAuditStore(db_path=os.getenv("COST_AUDIT_DB_PATH"))
    return _STORE


__all__ = ["CostAuditStore", "get_cost_audit_store"]

"""Immutable forecast records and persisted collection budgets in local SQLite."""
from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from contextlib import contextmanager
from dataclasses import asdict
from datetime import date, datetime
from functools import lru_cache
from pathlib import Path

from backend.services.prediction_calendar import NY, PredictionWindow, iso, timestamp, utc_now
from backend.services.prediction_market import SOURCE

UNIVERSE_VERSION = "us20-v1"
TICKERS = ("AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "JPM",
           "BAC", "V", "UNH", "JNJ", "LLY", "XOM", "CVX", "CAT", "WMT", "COST")
STRATEGY_VERSION = "forecast-v1"


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


class PredictionStore:
    def __init__(self, db_path: str | Path | None = None):
        root = Path(__file__).resolve().parents[2]
        self.path = Path(db_path) if db_path else Path(os.getenv("FINSIGHT_CONFIG_DIR") or root / "data") / "prediction_ledger.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS prediction_collection_state (
                    universe_version TEXT PRIMARY KEY, start_date TEXT NOT NULL,
                    first_enabled_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS prediction_batches (
                    id TEXT PRIMARY KEY, batch_date TEXT NOT NULL, universe_version TEXT NOT NULL,
                    window_json TEXT NOT NULL, created_at TEXT NOT NULL, last_update TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS prediction_opportunities (
                    id TEXT PRIMARY KEY, batch_id TEXT NOT NULL REFERENCES prediction_batches(id),
                    ticker TEXT NOT NULL, agent TEXT NOT NULL, prediction_type TEXT NOT NULL,
                    context_json TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
                    attempts INTEGER NOT NULL DEFAULT 0, retryable INTEGER NOT NULL DEFAULT 0,
                    error_code TEXT, UNIQUE(batch_id, ticker, agent)
                );
                CREATE TABLE IF NOT EXISTS prediction_snapshots (
                    batch_id TEXT NOT NULL REFERENCES prediction_batches(id), ticker TEXT NOT NULL,
                    payload TEXT NOT NULL, PRIMARY KEY(batch_id, ticker)
                );
                CREATE TABLE IF NOT EXISTS prediction_attempts (
                    opportunity_id TEXT NOT NULL REFERENCES prediction_opportunities(id),
                    attempt_no INTEGER NOT NULL, started_at TEXT NOT NULL, completed_at TEXT,
                    status TEXT NOT NULL DEFAULT 'running', error_code TEXT, audit_json TEXT,
                    PRIMARY KEY(opportunity_id, attempt_no)
                );
                CREATE TABLE IF NOT EXISTS prediction_records (
                    opportunity_id TEXT PRIMARY KEY REFERENCES prediction_opportunities(id),
                    issued_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS prediction_settlements (
                    opportunity_id TEXT PRIMARY KEY REFERENCES prediction_records(opportunity_id),
                    settled_at TEXT NOT NULL, outcome_json TEXT NOT NULL, market_json TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS prediction_batch_opportunities ON prediction_opportunities(batch_id);
            """)

    @contextmanager
    def connection(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def ensure_batch(self, window: PredictionWindow, *, tickers=TICKERS, now=None) -> str:
        batch_id = UNIVERSE_VERSION + ":" + window.batch_date
        now = iso(now or utc_now())
        with self.connection() as conn:
            inserted = conn.execute("INSERT OR IGNORE INTO prediction_batches VALUES (?, ?, ?, ?, ?, ?)",
                                    (batch_id, window.batch_date, UNIVERSE_VERSION, encode(asdict(window)), now, now))
            if not inserted.rowcount:
                return batch_id
            for ticker in tickers:
                for agent, kind in (("technical", "direction"), ("risk", "drawdown")):
                    identity = f"{batch_id}:{ticker}:{agent}"
                    conn.execute("""INSERT OR IGNORE INTO prediction_opportunities
                        (id,batch_id,ticker,agent,prediction_type,context_json) VALUES (?,?,?,?,?,?)""",
                        (identity, batch_id, ticker, agent, kind, encode(window.context(ticker))))
        return batch_id

    def register_collection_start(self, now: datetime) -> date:
        """Freeze the accountable range when collection first runs, not on a health read."""
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            earliest = conn.execute(
                "SELECT MIN(batch_date) FROM prediction_batches WHERE universe_version=?",
                (UNIVERSE_VERSION,),
            ).fetchone()[0]
            conn.execute("INSERT OR IGNORE INTO prediction_collection_state VALUES (?,?,?)",
                         (UNIVERSE_VERSION, earliest or now.astimezone(NY).date().isoformat(), iso(now)))
            row = conn.execute("SELECT start_date FROM prediction_collection_state WHERE universe_version=?",
                               (UNIVERSE_VERSION,)).fetchone()
        return date.fromisoformat(row[0])

    def registered_batch_dates(self) -> set[str]:
        with self.connection() as conn:
            return {row[0] for row in conn.execute(
                "SELECT batch_date FROM prediction_batches WHERE universe_version=?", (UNIVERSE_VERSION,))}

    def opportunities(self, batch_id: str) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM prediction_opportunities WHERE batch_id=? ORDER BY id", (batch_id,))]

    def snapshot(self, batch_id: str, ticker: str) -> dict | None:
        with self.connection() as conn:
            row = conn.execute("SELECT payload FROM prediction_snapshots WHERE batch_id=? AND ticker=?", (batch_id, ticker)).fetchone()
            return json.loads(row[0]) if row else None

    def freeze_snapshot(self, batch_id: str, ticker: str, snapshot: dict) -> dict:
        with self.connection() as conn:
            conn.execute("INSERT OR IGNORE INTO prediction_snapshots VALUES (?,?,?)", (batch_id, ticker, encode(snapshot)))
        return self.snapshot(batch_id, ticker)

    def reserve_attempt(self, identity: str, *, now: datetime, daily_limit=60) -> int | None:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM prediction_opportunities WHERE id=?", (identity,)).fetchone()
            if not row or row["status"] not in ("queued", "failed", "interrupted"):
                return None
            context = json.loads(row["context_json"])
            if (timestamp(context["deadline_at"]) - now).total_seconds() < 65:
                return None
            if row["attempts"] >= 2 or (row["attempts"] and not row["retryable"]):
                return None
            budget = min(60, daily_limit)
            usage = conn.execute("""SELECT COALESCE(SUM(attempts),0) AS used, COUNT(*) AS opportunities,
                COALESCE(SUM(CASE WHEN attempts > 1 THEN attempts - 1 ELSE 0 END),0) AS retries
                FROM prediction_opportunities WHERE batch_id=?""", (row["batch_id"],)).fetchone()
            if usage["used"] >= budget:
                return None
            if row["attempts"]:
                # Reserve one slot for every opportunity, including tickers still waiting
                # for prices. Missing data must not block the remaining retry allowance.
                retry_limit = min(20, max(0, budget - usage["opportunities"]))
                if usage["retries"] >= retry_limit:
                    return None
                ready_first = conn.execute("""SELECT 1 FROM prediction_opportunities o
                    JOIN prediction_snapshots s ON s.batch_id=o.batch_id AND s.ticker=o.ticker
                    WHERE o.batch_id=? AND o.status='queued' AND o.attempts=0 LIMIT 1""",
                    (row["batch_id"],),
                ).fetchone()
                if ready_first:
                    return None
            number = row["attempts"] + 1
            conn.execute("UPDATE prediction_opportunities SET status='running',attempts=?,retryable=0,error_code=NULL WHERE id=?", (number, identity))
            conn.execute("INSERT INTO prediction_attempts(opportunity_id,attempt_no,started_at) VALUES (?,?,?)", (identity, number, iso(now)))
            conn.execute("UPDATE prediction_batches SET last_update=? WHERE id=?", (iso(now), row["batch_id"]))
            return number

    def finish_attempt(self, identity: str, number: int, result: dict, *, now: datetime) -> None:
        with self.connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM prediction_opportunities WHERE id=?", (identity,)).fetchone()
            attempt = conn.execute("SELECT completed_at FROM prediction_attempts WHERE opportunity_id=? AND attempt_no=?", (identity, number)).fetchone()
            if not row or not attempt or attempt[0] is not None:
                return
            context = json.loads(row["context_json"])
            status = result["status"]
            error = result.get("error_code")
            if now >= timestamp(context["deadline_at"]):
                status, error = "missed", "deadline_elapsed"
            if status == "predicted":
                issued = timestamp(result["issued_at"])
                if not timestamp(context["knowledge_cutoff"]) < issued <= now:
                    status, error = "failed", "invalid_issuance_time"
            if status == "predicted":
                if result["prediction_type"] != row["prediction_type"]:
                    raise ValueError("forecast type differs from registered opportunity")
                conn.execute("INSERT OR IGNORE INTO prediction_records VALUES (?,?,?)", (identity, result["issued_at"], encode({**result, "strategy_version": STRATEGY_VERSION})))
                status = "pending"
            conn.execute("UPDATE prediction_attempts SET completed_at=?,status=?,error_code=?,audit_json=? WHERE opportunity_id=? AND attempt_no=?",
                         (iso(now), status, error, encode(result), identity, number))
            conn.execute("UPDATE prediction_opportunities SET status=?,error_code=?,retryable=? WHERE id=?",
                         (status, error, int(status == "failed" and bool(result.get("retryable"))), identity))
            conn.execute("UPDATE prediction_batches SET last_update=? WHERE id=?", (iso(now), row["batch_id"]))

    def fail_data(self, identity: str, error="market_data_unavailable", *, now=None) -> None:
        with self.connection() as conn:
            # No model request happened. Keep the opportunity eligible for the next poll;
            # retryable belongs to charged LLM attempts, not market-data acquisition.
            cursor = conn.execute("UPDATE prediction_opportunities SET retryable=0,error_code=? WHERE id=? AND status='queued' AND attempts=0", (error, identity))
            if cursor.rowcount:
                conn.execute("UPDATE prediction_batches SET last_update=? WHERE id=(SELECT batch_id FROM prediction_opportunities WHERE id=?)", (iso(now or utc_now()), identity))

    def recover_interrupted(self) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE prediction_opportunities SET status='interrupted',retryable=1,error_code='process_interrupted' WHERE status='running'")
            conn.execute("UPDATE prediction_attempts SET completed_at=?,status='interrupted',error_code='process_interrupted' WHERE completed_at IS NULL", (iso(utc_now()),))

    def expire_queued(self, batch_id: str, now: datetime) -> None:
        with self.connection() as conn:
            row = conn.execute("SELECT window_json FROM prediction_batches WHERE id=?", (batch_id,)).fetchone()
            if row and now >= timestamp(json.loads(row[0])["deadline_at"]):
                changed = conn.execute("UPDATE prediction_opportunities SET status='missed',retryable=0,error_code='not_collected_before_deadline' WHERE batch_id=? AND status IN ('queued','interrupted')", (batch_id,))
                if changed.rowcount:
                    conn.execute("UPDATE prediction_batches SET last_update=? WHERE id=?", (iso(now), batch_id))

    def expire_uncollected(self, now: datetime) -> None:
        with self.connection() as conn:
            batches = conn.execute("SELECT DISTINCT batch_id FROM prediction_opportunities WHERE status IN ('queued','interrupted')").fetchall()
        for row in batches:
            self.expire_queued(row[0], now)

    def _rows(self) -> list[dict]:
        with self.connection() as conn:
            return [dict(row) for row in conn.execute("""
                SELECT o.*, b.batch_date, b.window_json, p.payload, p.issued_at, s.outcome_json,
                    (SELECT a.audit_json FROM prediction_attempts a WHERE a.opportunity_id=o.id ORDER BY a.attempt_no DESC LIMIT 1) AS last_attempt_json
                FROM prediction_opportunities o JOIN prediction_batches b ON b.id=o.batch_id
                LEFT JOIN prediction_records p ON p.opportunity_id=o.id
                LEFT JOIN prediction_settlements s ON s.opportunity_id=o.id
                ORDER BY b.batch_date DESC, o.id
            """)]

    def due_records(self, cutoff: str) -> list[dict]:
        result = []
        for row in self._rows():
            context = json.loads(row["context_json"])
            if row["payload"] and not row["outcome_json"] and timestamp(context["window_end"]) <= timestamp(cutoff):
                result.append({"id": row["id"], "ticker": row["ticker"], "batch_id": row["batch_id"],
                               "prediction": json.loads(row["payload"]),
                               "sessions": json.loads(row["window_json"])["sessions"]})
        return result

    def settled_market(self, batch_id: str, ticker: str) -> list[dict] | None:
        with self.connection() as conn:
            row = conn.execute("""SELECT s.market_json FROM prediction_settlements s
                JOIN prediction_opportunities o ON o.id=s.opportunity_id
                WHERE o.batch_id=? AND o.ticker=? LIMIT 1""", (batch_id, ticker)).fetchone()
            return json.loads(row[0]) if row else None

    def settle(self, identity: str, outcome: dict, bars: list[dict]) -> bool:
        with self.connection() as conn:
            cursor = conn.execute("INSERT OR IGNORE INTO prediction_settlements VALUES (?,?,?,?)",
                                  (identity, outcome["settled_at"], encode(outcome), encode(bars)))
            if cursor.rowcount:
                conn.execute("UPDATE prediction_opportunities SET status='settled',error_code=NULL WHERE id=?", (identity,))
            return bool(cursor.rowcount)

    def mark_awaiting_data(self, identity: str, error: str) -> None:
        with self.connection() as conn:
            conn.execute("UPDATE prediction_opportunities SET status='awaiting_data',error_code=? WHERE id=? AND status IN ('pending','awaiting_data')", (error, identity))

    def coverage(self, batch_date: str | None = None) -> dict:
        with self.connection() as conn:
            batch = conn.execute("SELECT * FROM prediction_batches WHERE batch_date=? ORDER BY id DESC LIMIT 1", (batch_date,)).fetchone() if batch_date else conn.execute("SELECT * FROM prediction_batches ORDER BY batch_date DESC LIMIT 1").fetchone()
            if not batch:
                return {"batch_date": batch_date, "exists": False, "expected": 40, "accepted": 0, "counts": {}, "attempts": 0, "last_update": None}
            rows = conn.execute("SELECT o.status,o.attempts,p.opportunity_id FROM prediction_opportunities o LEFT JOIN prediction_records p ON p.opportunity_id=o.id WHERE o.batch_id=?", (batch["id"],)).fetchall()
            return {"batch_date": batch["batch_date"], "exists": True, "expected": len(rows),
                    "accepted": sum(row[2] is not None for row in rows), "counts": dict(Counter(row[0] for row in rows)),
                    "attempts": sum(row[1] for row in rows), "last_update": batch["last_update"]}

    def public_report(self, *, enabled=False, limit=50, offset=0) -> dict:
        rows = self._rows()
        counts = Counter(row["status"] for row in rows)
        groups = {}
        public_rows = []
        for index, row in enumerate(rows):
            context = json.loads(row["context_json"])
            prediction = json.loads(row["payload"]) if row["payload"] else json.loads(row["last_attempt_json"] or "{}")
            audit = prediction.get("metadata", {})
            actual_model = str(audit.get("actual_model") or "unknown")
            confirmed = bool(audit.get("model_confirmed"))
            outcome = json.loads(row["outcome_json"]) if row["outcome_json"] else None
            prompt = prediction.get("prompt_version", "")
            if outcome:
                strategy = prediction.get("strategy_version", "forecast-v1")
                key = (row["agent"], row["prediction_type"], actual_model, confirmed, prompt, strategy, context["scorer_version"])
                if key not in groups:
                    groups[key] = {"agent": key[0], "prediction_type": key[1], "actual_model": key[2], "model_confirmed": key[3],
                                   "prompt_version": prompt, "strategy_version": strategy,
                                   "scorer_version": context["scorer_version"], "n": 0, "hits": 0, "baseline_hits": 0,
                                   "tp": 0, "fp": 0, "tn": 0, "fn": 0}
                group = groups[key]
                group["n"] += 1
                group["hits"] += int(outcome["hit"])
                group["baseline_hits"] += int(outcome["baseline_hit"])
                if row["prediction_type"] == "drawdown":
                    label = ("t" if outcome["hit"] else "f") + ("p" if prediction["event_occurs"] else "n")
                    group[label] += 1
            if offset <= index < offset + limit:
                # Deliberate whitelist: no credentials, endpoint, raw response, snapshot or request identity.
                public_rows.append({"id": row["id"], "ticker": row["ticker"], "agent": row["agent"],
                    "prediction_type": row["prediction_type"], "batch_date": row["batch_date"], "status": row["status"],
                    "direction": prediction.get("direction"), "event_occurs": prediction.get("event_occurs"),
                    "reason": prediction.get("reason", ""), "evidence_refs": prediction.get("evidence_refs", []),
                    "issued_at": row["issued_at"] or prediction.get("issued_at"), "window_start": context["window_start"], "window_end": context["window_end"],
                    "actual_model": actual_model, "model_confirmed": confirmed, "prompt_version": prompt,
                    "outcome": outcome, "error_code": row["error_code"]})
        for group in groups.values():
            group["hit_rate"] = group["hits"] / group["n"]
            group["baseline_hit_rate"] = group["baseline_hits"] / group["n"]
            group["delta"] = group["hit_rate"] - group["baseline_hit_rate"]
        return {"enabled": enabled, "universe": {"version": UNIVERSE_VERSION, "tickers": list(TICKERS)},
                "coverage": self.coverage(), "summary": {
                    "opportunities": len(rows), "predictions": sum(bool(row["payload"]) for row in rows),
                    **{status: counts[status] for status in ("settled", "pending", "failed", "missed", "abstained", "awaiting_data", "queued", "running", "interrupted")},
                    "batch_count": len({row["batch_date"] for row in rows}), "stock_count": len({row["ticker"] for row in rows})},
                "groups": list(groups.values()), "records": public_rows,
                "pagination": {"offset": offset, "limit": limit, "total": len(rows), "has_more": offset + limit < len(rows)},
                "metadata": {"source": SOURCE, "horizon_sessions": 5, "direction_threshold": .005, "drawdown_threshold": .05}}


@lru_cache(maxsize=1)
def get_prediction_store() -> PredictionStore:
    return PredictionStore()

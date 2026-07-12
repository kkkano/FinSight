# -*- coding: utf-8 -*-
"""按租户归档 Agent 各调用层的 LLM token、成本与失败尝试。"""
from __future__ import annotations

import os
import threading
from typing import Any, Mapping

from sqlalchemy import create_engine, text

from backend.services.llm_usage import estimate_cost


class AgentRunArchiveUnavailable(RuntimeError):
    pass


class AgentRunArchive:
    def __init__(self, *, dsn: str | None = None, engine: Any | None = None) -> None:
        if engine is None:
            normalized = str(dsn or "").strip()
            if not normalized.startswith(("postgresql://", "postgresql+psycopg://")):
                raise ValueError("agent run archive 只允许 PostgreSQL DSN")
            engine = create_engine(normalized, future=True, pool_pre_ping=True)
        self._engine = engine
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    def ensure_schema(self) -> bool:
        if self._schema_ready:
            return True
        with self._schema_lock:
            if self._schema_ready:
                return True
            from backend.services.agent_prediction_store import get_agent_prediction_store

            get_agent_prediction_store().ensure_schema()
            with self._engine.begin() as conn:
                conn.execute(text(
                    "CREATE TABLE IF NOT EXISTS agent_run_archive ("
                    "id BIGSERIAL PRIMARY KEY, run_id TEXT NOT NULL, user_id TEXT NOT NULL, "
                    "agent TEXT NOT NULL, layer TEXT NOT NULL, prediction_id UUID NULL, model TEXT NOT NULL, "
                    "prompt_tokens BIGINT NOT NULL, completion_tokens BIGINT NOT NULL, total_tokens BIGINT NOT NULL, "
                    "cost_usd DOUBLE PRECISION NOT NULL, call_count INTEGER NOT NULL, failed_call_count INTEGER NOT NULL, "
                    "duration_ms BIGINT NOT NULL, status TEXT NOT NULL, created_at TIMESTAMPTZ NOT NULL DEFAULT now(), "
                    "UNIQUE(run_id,user_id,agent,layer,model), "
                    "FOREIGN KEY(prediction_id,user_id) REFERENCES agent_predictions(id,user_id))"
                ))
                conn.execute(text(
                    "CREATE INDEX IF NOT EXISTS idx_agent_run_archive_owner_agent_created "
                    "ON agent_run_archive(user_id,agent,created_at DESC)"
                ))
            self._schema_ready = True
        return True

    def archive_usage_summary(
        self, *, run_id: str, user_id: str, summary: Mapping[str, Any], status: str = "completed",
    ) -> int:
        normalized_user = str(user_id or "").strip()
        normalized_run = str(run_id or "").strip()
        if not normalized_run or not normalized_user or normalized_user == "public":
            return 0
        rows = summary.get("usage_by_attribution") if isinstance(summary, Mapping) else None
        if not isinstance(rows, list) or not rows:
            return 0
        self.ensure_schema()
        written = 0
        with self._engine.begin() as conn:
            for raw in rows:
                if not isinstance(raw, Mapping):
                    continue
                model = str(raw.get("model") or "unknown")
                prompt = max(0, int(raw.get("prompt") or 0))
                completion = max(0, int(raw.get("completion") or 0))
                params = {
                    "run_id": normalized_run,
                    "user_id": normalized_user,
                    "agent": str(raw.get("agent") or "unattributed"),
                    "layer": str(raw.get("layer") or "unknown"),
                    "prediction_id": str(raw.get("prediction_id") or "").strip() or None,
                    "model": model,
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_tokens": prompt + completion,
                    "cost_usd": estimate_cost({model: {"prompt": prompt, "completion": completion}}),
                    "call_count": max(0, int(raw.get("calls") or 0)),
                    "failed_call_count": max(0, int(raw.get("failed_calls") or 0)),
                    "duration_ms": max(0, int(raw.get("duration_ms") or 0)),
                    "status": str(status or "completed"),
                }
                conn.execute(text(
                    "INSERT INTO agent_run_archive (run_id,user_id,agent,layer,prediction_id,model,"
                    "prompt_tokens,completion_tokens,total_tokens,cost_usd,call_count,failed_call_count,duration_ms,status) "
                    "VALUES (:run_id,:user_id,:agent,:layer,CAST(:prediction_id AS uuid),:model,:prompt_tokens,"
                    ":completion_tokens,:total_tokens,:cost_usd,:call_count,:failed_call_count,:duration_ms,:status) "
                    "ON CONFLICT(run_id,user_id,agent,layer,model) DO UPDATE SET "
                    "prediction_id=excluded.prediction_id,prompt_tokens=excluded.prompt_tokens,"
                    "completion_tokens=excluded.completion_tokens,total_tokens=excluded.total_tokens,"
                    "cost_usd=excluded.cost_usd,call_count=excluded.call_count,"
                    "failed_call_count=excluded.failed_call_count,duration_ms=excluded.duration_ms,status=excluded.status"
                ), params)
                written += 1
        return written

    def cost_summary(self, *, user_id: str, agent: str, days: int) -> dict[str, Any]:
        normalized_user = str(user_id or "").strip()
        if not normalized_user or normalized_user == "public":
            return _empty_cost_summary(days)
        self.ensure_schema()
        with self._engine.connect() as conn:
            row = conn.execute(text(
                "SELECT COALESCE(SUM(total_tokens),0) AS tokens,COALESCE(SUM(cost_usd),0) AS cost,"
                "COUNT(DISTINCT run_id) AS run_count,COALESCE(SUM(call_count),0) AS call_count,"
                "COALESCE(SUM(failed_call_count),0) AS failed_call_count,"
                "COUNT(DISTINCT run_id) FILTER (WHERE prediction_id IS NULL) AS unscored_runs "
                "FROM agent_run_archive WHERE user_id=:user_id AND agent=:agent "
                "AND created_at >= now() - (:days * interval '1 day')"
            ), {"user_id": normalized_user, "agent": str(agent), "days": max(1, int(days))}).mappings().first()
        result = _empty_cost_summary(days)
        if row:
            result.update({
                "tokens": int(row.get("tokens") or 0),
                "cost_usd": round(float(row.get("cost") or 0), 6),
                "run_count": int(row.get("run_count") or 0),
                "call_count": int(row.get("call_count") or 0),
                "failed_call_count": int(row.get("failed_call_count") or 0),
                "unscored_runs": int(row.get("unscored_runs") or 0),
            })
        return result


def _empty_cost_summary(days: int) -> dict[str, Any]:
    return {"days": int(days), "tokens": 0, "cost_usd": 0.0, "run_count": 0, "call_count": 0, "failed_call_count": 0, "unscored_runs": 0}


def _resolve_dsn() -> str:
    return (os.getenv("AGENT_PREDICTION_POSTGRES_DSN") or os.getenv("RAG_V2_POSTGRES_DSN") or os.getenv("LANGGRAPH_CHECKPOINT_POSTGRES_DSN") or "").strip()


_archive: AgentRunArchive | None = None
_archive_lock = threading.Lock()


def get_agent_run_archive() -> AgentRunArchive:
    global _archive
    if _archive is not None:
        return _archive
    with _archive_lock:
        if _archive is None:
            dsn = _resolve_dsn()
            if not dsn:
                raise AgentRunArchiveUnavailable("agent run archive postgres unavailable")
            _archive = AgentRunArchive(dsn=dsn)
    return _archive


__all__ = ["AgentRunArchive", "AgentRunArchiveUnavailable", "get_agent_run_archive"]

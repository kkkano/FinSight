# -*- coding: utf-8 -*-
"""按租户归档 Agent 各调用层的 LLM token、成本与失败尝试。"""
from __future__ import annotations

import threading
from typing import Any, Mapping

from sqlalchemy import text

from backend.services.database import create_core_engine, resolve_core_postgres_dsn
from backend.services.llm_usage import estimate_cost


class AgentRunArchiveUnavailable(RuntimeError):
    pass


class AgentRunArchive:
    def __init__(self, *, dsn: str | None = None, engine: Any | None = None) -> None:
        if engine is None:
            engine = create_core_engine(dsn=dsn)
        self._engine = engine

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
    return resolve_core_postgres_dsn(required=False)


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

# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator, Mapping
from datetime import datetime, timezone
from typing import Any

from backend.protocols.a2a_models import A2AAgentCard, A2ASkill, A2ATaskRecord


_TRUE_VALUES = {"1", "true", "yes", "on"}
_TASKS: dict[str, A2ATaskRecord] = {}


def is_a2a_server_enabled() -> bool:
    return str(os.getenv("A2A_SERVER_ENABLED") or "false").strip().lower() in _TRUE_VALUES


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def _metadata(payload: Mapping[str, Any]) -> dict[str, Any]:
    value = payload.get("metadata")
    return dict(value) if isinstance(value, Mapping) else {}


def _message(payload: Mapping[str, Any]) -> str:
    for key in ("message", "query", "text", "task"):
        text = _clean_text(payload.get(key))
        if text:
            return text
    return ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        text = _clean_text(item).upper()
        if text:
            result.append(text)
    return result


def _task_id_for(execute_request: dict[str, Any]) -> str:
    material = repr(sorted(execute_request.items())) + _now_iso()
    return f"a2a_task_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:16]}"


def build_agent_card() -> dict[str, Any]:
    card = A2AAgentCard(
        name="FinSight Research Agent",
        description="Evidence-grounded financial research agent for company deep research, portfolio diagnosis, and holdings-change investigation.",
        url=os.getenv("A2A_PUBLIC_URL", ""),
        version="0.1.0",
        enabled=is_a2a_server_enabled(),
        capabilities={
            "streaming": True,
            "artifacts": True,
            "longRunningTasks": True,
            "pushNotifications": False,
        },
        defaultInputModes=["application/json", "text/plain"],
        defaultOutputModes=["application/json", "text/event-stream"],
        skills=[
            A2ASkill(
                id="company_deep_research",
                name="Company Deep Research",
                description="Run evidence-led company research and return report artifacts.",
                tags=["research", "equity", "evidence-ledger"],
            ),
            A2ASkill(
                id="portfolio_diagnosis",
                name="Portfolio Diagnosis",
                description="Diagnose portfolio exposure, risks, and next research questions.",
                tags=["portfolio", "risk", "diagnosis"],
            ),
            A2ASkill(
                id="holdings_change_investigation",
                name="Holdings Change Investigation",
                description="Investigate public 13F/Form 4 holdings changes and related evidence.",
                tags=["sec", "13f", "form-4", "holdings"],
            ),
        ],
    )
    return card.model_dump(mode="json")


def build_execute_request(payload: Mapping[str, Any]) -> dict[str, Any]:
    metadata = _metadata(payload)
    query = _message(payload)
    skill = _clean_text(metadata.get("skill"))
    tickers = _string_list(metadata.get("tickers") or payload.get("tickers"))

    output_mode = _clean_text(metadata.get("output_mode")) or "investment_report"
    analysis_depth = _clean_text(metadata.get("analysis_depth")) or "deep_research"
    if skill == "portfolio_diagnosis":
        output_mode = _clean_text(metadata.get("output_mode")) or "brief"
        analysis_depth = _clean_text(metadata.get("analysis_depth")) or "report"

    request: dict[str, Any] = {
        "query": query,
        "output_mode": output_mode,
        "analysis_depth": analysis_depth,
        "confirmation_mode": _clean_text(metadata.get("confirmation_mode")) or "skip",
        "source": "a2a",
    }
    session_id = _clean_text(metadata.get("session_id") or payload.get("session_id"))
    if session_id:
        request["session_id"] = session_id
    if tickers:
        request["tickers"] = tickers
    if skill:
        request["agent_preferences"] = {"a2a_skill": skill}
    return request


def submit_task(payload: Mapping[str, Any]) -> dict[str, Any]:
    if not is_a2a_server_enabled():
        return {
            "status": "disabled",
            "error": {
                "code": "a2a_server_disabled",
                "message": "A2A adapter 已关闭。设置 A2A_SERVER_ENABLED=true 后才接受长任务。",
            },
        }
    execute_request = build_execute_request(payload)
    if not _clean_text(execute_request.get("query")):
        return {
            "status": "rejected",
            "error": {"code": "query_required", "message": "A2A task requires message/query text."},
        }
    task_id = _task_id_for(execute_request)
    record = A2ATaskRecord(
        task_id=task_id,
        status="submitted",
        execute_request=execute_request,
        artifacts={
            "execute_request": execute_request,
            "note": "Submit this payload to POST /api/execute for full graph execution.",
        },
    )
    _TASKS[task_id] = record
    return {
        "task_id": task_id,
        "status": "submitted",
        "execute_request": execute_request,
    }


def stream_task(task_id: str) -> Iterator[dict[str, Any]]:
    record = _TASKS.get(_clean_text(task_id))
    if record is None:
        yield {
            "kind": "task_state",
            "task_id": _clean_text(task_id),
            "state": "not_found",
            "timestamp": _now_iso(),
        }
        return
    yield {
        "kind": "task_state",
        "task_id": record.task_id,
        "state": "submitted",
        "timestamp": _now_iso(),
    }
    yield {
        "kind": "task_state",
        "task_id": record.task_id,
        "state": "working",
        "timestamp": _now_iso(),
        "execute_endpoint": "/api/execute",
    }
    yield {
        "kind": "artifact",
        "task_id": record.task_id,
        "artifact": record.artifacts,
        "timestamp": _now_iso(),
    }


def get_task_artifacts(task_id: str) -> dict[str, Any]:
    record = _TASKS.get(_clean_text(task_id))
    if record is None:
        return {"status": "not_found", "task_id": _clean_text(task_id), "artifacts": {}}
    return {
        "status": record.status,
        "task_id": record.task_id,
        **record.artifacts,
    }


__all__ = [
    "build_agent_card",
    "build_execute_request",
    "get_task_artifacts",
    "is_a2a_server_enabled",
    "stream_task",
    "submit_task",
]

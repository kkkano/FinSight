# -*- coding: utf-8 -*-
"""Plan coverage validation for request frames.

This module checks whether a plan is structurally capable of satisfying the
request-frame obligations before execution/rendering.  It is intentionally
planner-invariant: it validates tool/agent presence against the contract, not
the natural-language query.
"""
from __future__ import annotations

from typing import Any, TypedDict

from backend.graph.intent_contract import canonical_evidence_kinds, evidence_plan_for_kinds, evidence_registry
from backend.graph.evidence_dependencies import step_evidence_kinds, step_subjects, step_task_ids
from backend.config.ticker_mapping import normalize_ticker


class CoverageValidation(TypedDict, total=False):
    status: str
    fulfilled_evidence: list[str]
    missing_evidence: list[str]
    frame_results: list[dict[str, Any]]
    missing_requirements: list[dict[str, Any]]


def _plan_step_names(plan_ir: dict[str, Any] | None) -> set[str]:
    if not isinstance(plan_ir, dict):
        return set()
    steps = plan_ir.get("steps")
    if not isinstance(steps, list):
        return set()
    return {str(step.get("name") or "").strip() for step in steps if isinstance(step, dict) and str(step.get("name") or "").strip()}


def _evidence_producers(kind: str, *, market: str = "US") -> set[str]:
    producers: set[str] = set()
    for item in evidence_plan_for_kinds([kind], market=market):
        producers.update(str(tool) for tool in (item.get("tools") or []) if str(tool).strip())
        producers.update(str(agent) for agent in (item.get("agents") or []) if str(agent).strip())
    return producers


def validate_plan_coverage(
    *,
    request_frame: dict[str, Any] | None,
    plan_ir: dict[str, Any] | None,
    market: str = "US",
) -> CoverageValidation:
    frame = request_frame if isinstance(request_frame, dict) else {}
    plan = plan_ir if isinstance(plan_ir, dict) else {}
    steps = [step for step in plan.get("steps", []) if isinstance(step, dict)]
    task_ids = [str(value) for value in frame.get("task_ids", []) if value]
    if not task_ids:
        task_ids = [str(task["id"]) for task in plan.get("tasks", [])
                    if task.get("request_frame_id") == frame.get("frame_id")]
    tickers = [normalize_ticker(str(value)) for value in (frame.get("subject") or {}).get("tickers", []) if value]
    required_evidence = canonical_evidence_kinds(
        request_frame.get("evidence_obligations")
        if isinstance(request_frame, dict) and isinstance(request_frame.get("evidence_obligations"), list)
        else []
    )
    fulfilled_evidence: list[str] = []
    missing_evidence: list[str] = []
    missing_requirements: list[dict[str, Any]] = []
    for kind in required_evidence:
        for task_id in task_ids or [None]:
            for ticker in tickers or [None]:
                required_market = "HK" if ticker and ticker.endswith(".HK") else ("CN" if ticker and ticker.endswith((".SS", ".SZ", ".BJ")) else market)
                producers = _evidence_producers(kind, market=required_market)
                candidates = [step for step in steps
                    if step.get("name") in producers
                    and kind in step_evidence_kinds(step)
                    and (task_id is None or task_id in step_task_ids(step))
                    and (ticker is None or evidence_registry()[kind].scope == 'per_topic' or ticker in step_subjects(step))]
                if not candidates:
                    missing_requirements.append({"task_id": task_id, "subject": ticker,
                        "evidence_kind": kind, "frame_id": frame.get("frame_id"),
                        "reason": "producer_unavailable" if not producers else "producer_not_planned"})
        if any(item["evidence_kind"] == kind for item in missing_requirements):
            missing_evidence.append(kind)
        else:
            fulfilled_evidence.append(kind)

    status = "ok" if not missing_evidence else "missing"
    return {
        "status": status,
        "fulfilled_evidence": fulfilled_evidence,
        "missing_evidence": missing_evidence,
        "missing_requirements": missing_requirements,
    }


def _append_unique(target: list[str], values: list[str], seen: set[str]) -> None:
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        target.append(value)


def validate_plan_coverage_for_frames(
    *,
    request_frames: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None,
    plan_ir: dict[str, Any] | None,
    market: str = "US",
) -> CoverageValidation:
    frames = [frame for frame in (request_frames or []) if isinstance(frame, dict)]
    if not frames:
        return validate_plan_coverage(request_frame=None, plan_ir=plan_ir, market=market)

    fulfilled_evidence: list[str] = []
    missing_evidence: list[str] = []
    seen_fulfilled_evidence: set[str] = set()
    seen_missing_evidence: set[str] = set()
    frame_results: list[dict[str, Any]] = []
    missing_requirements: list[dict[str, Any]] = []

    for index, frame in enumerate(frames, 1):
        result = validate_plan_coverage(request_frame=frame, plan_ir=plan_ir, market=market)
        frame_result: dict[str, Any] = {
            "frame_id": str(frame.get("frame_id") or f"frame_{index}"),
            "status": result.get("status", ""),
            "fulfilled_evidence": result.get("fulfilled_evidence", []),
            "missing_evidence": result.get("missing_evidence", []),
            "missing_requirements": result.get("missing_requirements", []),
        }
        frame_results.append(frame_result)
        missing_requirements.extend(result.get("missing_requirements", []))
        _append_unique(fulfilled_evidence, result.get("fulfilled_evidence", []), seen_fulfilled_evidence)
        _append_unique(missing_evidence, result.get("missing_evidence", []), seen_missing_evidence)

    status = "ok" if not missing_evidence else "missing"
    return {
        "status": status,
        "fulfilled_evidence": fulfilled_evidence,
        "missing_evidence": missing_evidence,
        "frame_results": frame_results,
        "missing_requirements": missing_requirements,
    }


__all__ = ["CoverageValidation", "validate_plan_coverage", "validate_plan_coverage_for_frames"]

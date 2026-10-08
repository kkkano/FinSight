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
    requirements = (frame.get("render_contract") or {}).get("answer_requirements") or []
    if (frame.get("lane") in {"research", "report"} and not required_evidence
            and any(row.get("kind") not in {"constraint", "input_dependency"} for row in requirements)):
        missing_evidence.append("research_evidence")
        missing_requirements.append({"frame_id": frame.get("frame_id"), "reason": "research_evidence_not_planned"})
    from backend.graph.research_capabilities import input_groups
    groups = input_groups({"required_input_groups": frame["required_input_groups"]}) if "required_input_groups" in frame else [
        {"group_id": kind, "any_of": [kind]} for kind in required_evidence]
    for group in groups:
        choices = group["any_of"]
        requirement = next((row for row in requirements if row.get("requirement_id") == group.get("requirement_id")), None) if group.get("requirement_id") else None
        scoped_tickers = ([normalize_ticker(str(requirement["subject"]))] if requirement.get("subject") and requirement.get("kind") != "comparison"
                          else tickers if requirement.get("subject_refs") or requirement.get("kind") == "comparison" else []) if requirement else tickers
        scoped_task_ids = [task_id for task_id in task_ids if not plan.get("tasks") or any(
            task.get("id") == task_id and (not task.get("answer_requirements") or any(
                row.get("requirement_id") == group.get("requirement_id") for row in task["answer_requirements"]))
            for task in plan["tasks"])] if requirement else task_ids
        group_missing = False
        for task_id in scoped_task_ids or [None]:
            for ticker in scoped_tickers or [None]:
                required_market = "HK" if ticker and ticker.endswith(".HK") else ("CN" if ticker and ticker.endswith((".SS", ".SZ", ".BJ")) else market)
                producers = {name for kind in choices for name in _evidence_producers(kind, market=required_market)}
                candidates = [step for step in steps
                    if any(step.get("name") in _evidence_producers(kind, market=required_market)
                           and kind in step_evidence_kinds(step)
                           and (ticker is None or evidence_registry()[kind].scope == 'per_topic' or ticker in step_subjects(step))
                           for kind in choices)
                    and (task_id is None or task_id in step_task_ids(step))
                    ]
                if not candidates:
                    group_missing = True
                    missing_requirements.append({"task_id": task_id, "subject": ticker,
                        "evidence_kind": choices[0], "input_group_id": group["group_id"],
                        "requirement_id": group.get("requirement_id"), "any_of": choices, "frame_id": frame.get("frame_id"),
                        "reason": "producer_unavailable" if not producers else "producer_not_planned"})
        if group_missing:
            missing_evidence.extend(kind for kind in choices if kind not in missing_evidence)
        else:
            fulfilled_evidence.extend(kind for kind in choices if kind not in fulfilled_evidence and any(kind in step_evidence_kinds(step) for step in steps))

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

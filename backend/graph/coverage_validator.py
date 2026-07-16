# -*- coding: utf-8 -*-
"""Plan coverage validation for request frames.

This module checks whether a plan is structurally capable of satisfying the
request-frame obligations before execution/rendering.  It is intentionally
planner-invariant: it validates tool/agent presence against the contract, not
the natural-language query.
"""
from __future__ import annotations

from typing import Any, TypedDict

from backend.graph.intent_contract import canonical_evidence_kinds, evidence_plan_for_kinds


class CoverageValidation(TypedDict, total=False):
    status: str
    fulfilled_evidence: list[str]
    missing_evidence: list[str]
    frame_results: list[dict[str, Any]]


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
    step_names = _plan_step_names(plan_ir)
    required_evidence = canonical_evidence_kinds(
        request_frame.get("evidence_obligations")
        if isinstance(request_frame, dict) and isinstance(request_frame.get("evidence_obligations"), list)
        else []
    )
    fulfilled_evidence: list[str] = []
    missing_evidence: list[str] = []
    for kind in required_evidence:
        producers = _evidence_producers(kind, market=market)
        if producers and step_names.intersection(producers):
            fulfilled_evidence.append(kind)
        else:
            missing_evidence.append(kind)

    status = "ok" if not missing_evidence else "missing"
    return {
        "status": status,
        "fulfilled_evidence": fulfilled_evidence,
        "missing_evidence": missing_evidence,
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

    for index, frame in enumerate(frames, 1):
        result = validate_plan_coverage(request_frame=frame, plan_ir=plan_ir, market=market)
        frame_result: dict[str, Any] = {
            "frame_id": str(frame.get("frame_id") or f"frame_{index}"),
            "status": result.get("status", ""),
            "fulfilled_evidence": result.get("fulfilled_evidence", []),
            "missing_evidence": result.get("missing_evidence", []),
        }
        frame_results.append(frame_result)
        _append_unique(fulfilled_evidence, result.get("fulfilled_evidence", []), seen_fulfilled_evidence)
        _append_unique(missing_evidence, result.get("missing_evidence", []), seen_missing_evidence)

    status = "ok" if not missing_evidence else "missing"
    return {
        "status": status,
        "fulfilled_evidence": fulfilled_evidence,
        "missing_evidence": missing_evidence,
        "frame_results": frame_results,
    }


__all__ = ["CoverageValidation", "validate_plan_coverage", "validate_plan_coverage_for_frames"]

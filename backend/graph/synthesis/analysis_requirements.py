"""根据已编译的逐任务合同决定是否需要研究解释。"""
from __future__ import annotations

from typing import Any


_ANALYTICAL_OPERATIONS = {
    "analysis", "earnings_impact", "investment_opinion", "news_impact", "qa",
    "valuation_sanity",
}
_ANALYTICAL_DIMENSIONS = {
    "business_model", "competition", "valuation", "valuation_sanity",
    "cash_flow_quality", "earnings_impact", "macro_transmission", "macro_impact",
    "investment_thesis", "catalysts", "risk_assessment",
}


def compiled_tasks(state: dict[str, Any]) -> list[dict[str, Any]]:
    understanding = state.get("understanding") or {}
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        tasks = understanding.get("tasks", []) if isinstance(understanding, dict) else []
    return [task for task in tasks if isinstance(task, dict)]


def answer_requirements_by_task(state: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    frames = [frame for frame in state.get("request_frames", []) if isinstance(frame, dict)]
    if isinstance(state.get("request_frame"), dict):
        frames.append(state["request_frame"])
    result = {}
    for task in compiled_tasks(state):
        task_id = str(task.get("id") or task.get("task_id") or "")
        requirements = task.get("answer_requirements")
        if not isinstance(requirements, list):
            frame = next((frame for frame in frames if str(frame.get("frame_id") or frame.get("id") or "") == str(task.get("request_frame_id") or "")), {})
            render = frame.get("render_contract") or {}
            requirements = render.get("answer_requirements", []) if isinstance(render, dict) else []
        result[task_id] = [dict(item) for item in requirements if isinstance(item, dict) and item.get("requirement_id")]
    return result


def task_needs_analysis(task: dict[str, Any], *, report: bool = False) -> bool:
    if task.get("evidence_support_for"):
        return False
    requirements = task.get("answer_requirements")
    if isinstance(requirements, list) and requirements:
        return any(bool(item.get("requires_analysis")) for item in requirements if isinstance(item, dict))
    if report:
        return True
    operation = task.get("operation") or {}
    name = str(operation.get("name") if isinstance(operation, dict) else operation).strip().lower()
    if name in _ANALYTICAL_OPERATIONS:
        return True
    dimensions = task.get("requested_dimensions") or task.get("dimensions") or []
    if set(dimensions) & _ANALYTICAL_DIMENSIONS:
        return True
    if name in {"compare", "macro_brief"}:
        return bool(set(task.get("required_evidence") or []) & {
            "fundamental_snapshot", "risk_profile", "news_context", "filing_context",
        })
    return False


def analysis_task_modes(state: dict[str, Any]) -> dict[str, str]:
    requirements = answer_requirements_by_task(state)
    report = str(state.get("output_mode") or "").lower() == "investment_report"
    return {
        str(task.get("id") or task.get("task_id") or ""):
        "research" if task_needs_analysis({**task, "answer_requirements": requirements.get(str(task.get("id") or task.get("task_id") or ""), [])}, report=report) else "deterministic"
        for task in compiled_tasks(state)
    }


__all__ = ["analysis_task_modes", "answer_requirements_by_task", "compiled_tasks", "task_needs_analysis"]

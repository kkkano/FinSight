"""根据已编译的逐任务合同决定是否需要研究解释。"""
from __future__ import annotations

from typing import Any
from copy import deepcopy
import hashlib

from backend.graph.request_spec import UnmappedRequirement


_ANALYTICAL_OPERATIONS = {
    "analysis", "earnings_impact", "investment_opinion", "news_impact", "qa",
    "valuation_sanity",
}
_ANALYTICAL_DIMENSIONS = {
    "business_model", "competition", "valuation", "valuation_sanity",
    "cash_flow_quality", "earnings_impact", "macro_transmission", "macro_impact",
    "investment_thesis", "catalysts", "risk_assessment",
}


def unconfirmed_request_requirement(state: dict[str, Any]) -> dict[str, Any] | None:
    understanding = state.get("understanding") or {}
    semantic = understanding.get("semantic_contract") or {}
    if semantic.get("status") != "unconfirmed" and understanding.get("requirements_status") not in {"unconfirmed", "deterministic_fallback"}:
        return None
    query = str(semantic.get("query") or state.get("query") or understanding.get("original_query") or "原始研究请求")
    row = next((item for item in semantic.get("requirements", []) if isinstance(item, dict)
                and item.get("metric") == "unknown" and item.get("source_text") == query), None)
    if row is not None:
        return deepcopy(row)
    return UnmappedRequirement(requirement_id="unconfirmed:" + hashlib.sha256(query.encode("utf-8")).hexdigest()[:16],
        source_text=query, description=query, metric_text=query, kind="explanation",
        requires_analysis=True, capability_status="unsupported").model_dump()


def compiled_tasks(state: dict[str, Any]) -> list[dict[str, Any]]:
    understanding = state.get("understanding") or {}
    semantic = understanding.get("semantic_contract") if isinstance(understanding, dict) else None
    unconfirmed = unconfirmed_request_requirement(state)
    if isinstance(semantic, dict) and semantic.get("status") == "confirmed" and unconfirmed is None:
        return [dict(task) for task in semantic.get("tasks", []) if isinstance(task, dict)]
    tasks = state.get("tasks")
    if not isinstance(tasks, list):
        tasks = understanding.get("tasks", []) if isinstance(understanding, dict) else []
    if unconfirmed is not None:
        # 旧任务 ID 只绑定实际采集的事实，不能继续决定原问的回答分母。
        return [{**task, "answer_requirements": [deepcopy(unconfirmed)], "requirements_status": "unconfirmed"}
                for task in tasks if isinstance(task, dict)]
    return [task for task in tasks if isinstance(task, dict)]


def requested_task_partition(state: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    """请求分母来自已确认的原始合同，不能跟随下游丢项而缩小。"""
    understanding = state.get("understanding") or {}
    semantic = understanding.get("semantic_contract") if isinstance(understanding, dict) else None
    if isinstance(semantic, dict) and semantic.get("status") == "confirmed" and unconfirmed_request_requirement(state) is None:
        tasks = compiled_tasks(state)
        return ([task for task in tasks if task.get("status") != "blocked"],
                [task for task in tasks if task.get("status") == "blocked"])
    blocked = state.get("blocked_tasks", understanding.get("blocked_tasks", []))
    return compiled_tasks(state), [task for task in (blocked or []) if isinstance(task, dict)]


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
    if unconfirmed_request_requirement(state) is not None:
        return {str(task.get("id") or task.get("task_id") or ""): "deterministic" for task in compiled_tasks(state)}
    requirements = answer_requirements_by_task(state)
    report = str(state.get("output_mode") or "").lower() == "investment_report"
    return {
        str(task.get("id") or task.get("task_id") or ""):
        "research" if task_needs_analysis({**task, "answer_requirements": requirements.get(str(task.get("id") or task.get("task_id") or ""), [])}, report=report) else "deterministic"
        for task in compiled_tasks(state)
    }


__all__ = ["analysis_task_modes", "answer_requirements_by_task", "compiled_tasks", "requested_task_partition", "task_needs_analysis", "unconfirmed_request_requirement"]

# -*- coding: utf-8 -*-
"""意图层单一事实源（WP2 D1）。

`IntentFrame` 是 understand 阶段的唯一权威产物；`intent_frame_from_legacy` /
`legacy_understanding_from_frame` 提供与现存 `understanding` dict 的无损互转，
供灰度期（FINSIGHT_INTENT_FRAME=shadow/on）双轨对拍与下游渐进切换。
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

SUBJECT_TYPES = {
    "company", "macro", "theme", "portfolio", "news_item", "news_set",
    "research_doc", "filing", "index", "crypto", "fund", "commodity", "unknown",
}


class IntentTask(BaseModel):
    id: str
    title: str = ""
    subject_type: str
    subject_label: str = ""
    tickers: list[str] = Field(default_factory=list)
    operation: str
    operation_confidence: float = 0.75
    params: dict[str, Any] = Field(default_factory=dict)
    required_evidence: list[str] = Field(default_factory=list)
    priority: int = 50
    order_index: int = 0
    request_frame_id: str = ""
    render_kind: str = "single"
    render_group_id: str = ""
    reason: str = ""
    answer_requirements: list[dict[str, Any]] = Field(default_factory=list)
    time_scope: dict[str, Any] = Field(default_factory=dict)
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    requirements_status: str = ""
    evidence_support_for: str = ""
    request_text: str = ""


class BlockedIntent(BaseModel):
    id: str
    title: str = ""
    reason: str
    question: str
    suggestions: list[str] = Field(default_factory=list)
    fallback_allowed: bool = False
    subject_type: str = "unknown"
    subject_label: str = ""
    tickers: list[str] = Field(default_factory=list)
    operation: str = "qa"
    priority: int = 50
    order_index: int = 0
    request_frame_id: str = ""
    render_kind: str = "single"
    render_group_id: str = ""
    error_code: str = "task_blocked"
    answer_requirements: list[dict[str, Any]] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    time_scope: dict[str, Any] = Field(default_factory=dict)
    constraints: list[dict[str, Any]] = Field(default_factory=list)
    requirements_status: str = ""


class IntentFrame(BaseModel):
    schema_version: str = "intent_frame/v1"
    route: str                                  # research | direct | clarify
    query: str
    output_mode: str = "chat"
    language: str = "zh"
    tasks: list[IntentTask] = Field(default_factory=list)
    blocked: list[BlockedIntent] = Field(default_factory=list)
    context_refs: list[dict[str, Any]] = Field(default_factory=list)
    fallback_assumptions: list[str] = Field(default_factory=list)
    reply_plan: dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.5
    source: str = "rules_fallback"              # llm_router | rules_fallback | mixed
    requirements_status: str = ""
    semantic_contract: dict[str, Any] = Field(default_factory=dict)
    request_frames: list[dict[str, Any]] = Field(default_factory=list)


def _task_from_legacy(raw: dict[str, Any]) -> IntentTask:
    operation = raw.get("operation") if isinstance(raw.get("operation"), dict) else {}
    return IntentTask(
        id=str(raw.get("id") or ""),
        title=str(raw.get("title") or raw.get("subject_label") or ""),
        subject_type=str(raw.get("subject_type") or "unknown"),
        subject_label=str(raw.get("subject_label") or ""),
        tickers=[str(t) for t in (raw.get("tickers") or []) if str(t).strip()],
        operation=str(operation.get("name") or "qa"),
        operation_confidence=float(operation.get("confidence") or 0.75),
        params=dict(operation.get("params") or {}) or dict(raw.get("params") or {}),
        required_evidence=[str(e) for e in (raw.get("required_evidence") or [])],
        priority=int(raw.get("priority") or 50),
        order_index=int(raw.get("order_index") or 0),
        request_frame_id=str(raw.get("request_frame_id") or ""),
        render_kind=str(raw.get("render_kind") or "single"),
        render_group_id=str(raw.get("render_group_id") or ""),
        reason=str(raw.get("reason") or ""),
        answer_requirements=list(raw.get("answer_requirements") or []),
        time_scope=dict(raw.get("time_scope") or {}), constraints=list(raw.get("constraints") or []),
        requirements_status=str(raw.get("requirements_status") or ""),
        evidence_support_for=str(raw.get("evidence_support_for") or ""), request_text=str(raw.get("request_text") or ""),
    )


def _blocked_from_legacy(raw: dict[str, Any]) -> BlockedIntent:
    return BlockedIntent(
        id=str(raw.get("id") or "blocked_1"),
        title=str(raw.get("title") or raw.get("subject_label") or ""),
        reason=str(raw.get("reason") or ""),
        question=str(raw.get("question") or ""),
        suggestions=[str(s) for s in (raw.get("suggestions") or [])],
        fallback_allowed=bool(raw.get("fallback_allowed")),
        subject_type=str(raw.get("subject_type") or "unknown"),
        subject_label=str(raw.get("subject_label") or ""),
        tickers=[str(t) for t in (raw.get("tickers") or []) if str(t).strip()],
        operation=str((raw.get("operation") or {}).get("name") if isinstance(raw.get("operation"), dict) else raw.get("operation") or "qa"),
        priority=int(raw.get("priority") or 50),
        order_index=int(raw.get("order_index") or 0),
        request_frame_id=str(raw.get("request_frame_id") or ""),
        render_kind=str(raw.get("render_kind") or "single"),
        render_group_id=str(raw.get("render_group_id") or ""),
        error_code=str(raw.get("error_code") or "task_blocked"),
        answer_requirements=list(raw.get("answer_requirements") or []), required_evidence=list(raw.get("required_evidence") or []),
        time_scope=dict(raw.get("time_scope") or {}), constraints=list(raw.get("constraints") or []),
        requirements_status=str(raw.get("requirements_status") or ""),
    )


def intent_frame_from_legacy(
    understanding: dict[str, Any],
    *,
    reply_contract: dict[str, Any] | None = None,
    intent_contract: dict[str, Any] | None = None,
) -> IntentFrame:
    """由现存 understanding dict（+可选 contract）构造 IntentFrame。

    route 推断：显式 route 优先；缺失时 tasks 非空 → research，否则 clarify。
    intent_contract.required_evidence 应用到 primary_tickers 命中的任务
    （无 primary_tickers 约束时应用到全部任务）。
    """
    tasks = [_task_from_legacy(t) for t in (understanding.get("tasks") or []) if isinstance(t, dict)]
    blocked = [_blocked_from_legacy(b) for b in (understanding.get("blocked_tasks") or []) if isinstance(b, dict)]

    route = str(understanding.get("route") or "").strip().lower()
    if not route:
        route = "research" if tasks else "clarify"

    if isinstance(intent_contract, dict):
        required = [str(e) for e in (intent_contract.get("required_evidence") or [])]
        primary = {str(t).upper() for t in (intent_contract.get("primary_tickers") or [])}
        if required:
            for task in tasks:
                if not primary or primary & {t.upper() for t in task.tickers}:
                    if not task.required_evidence:
                        task.required_evidence = list(required)

    query = str(understanding.get("original_query") or understanding.get("cleaned_query") or "")
    language = str(understanding.get("language") or "zh")
    confidence_raw = understanding.get("confidence")
    confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else (0.78 if tasks else 0.42)

    return IntentFrame(
        route=route,
        query=query,
        output_mode=str(understanding.get("output_mode") or "chat"),
        language=language,
        tasks=tasks,
        blocked=blocked,
        context_refs=[dict(r) for r in (understanding.get("context_refs") or []) if isinstance(r, dict)],
        fallback_assumptions=[str(a) for a in (understanding.get("fallback_assumptions") or [])],
        reply_plan=dict(reply_contract) if isinstance(reply_contract, dict) else {},
        confidence=confidence,
        requirements_status=str(understanding.get("requirements_status") or ""),
        semantic_contract=dict(understanding.get("semantic_contract") or {}),
        request_frames=list(understanding.get("request_frames") or []),
    )


def _user_visible_summary(frame: IntentFrame) -> str:
    """与 understand_request 现状逐字一致的 summary 规则。"""
    summary_bits: list[str] = []
    for task in frame.tasks[:5]:
        subject_label = task.subject_label or ",".join(task.tickers) or task.subject_type
        summary_bits.append(f"{subject_label}:{task.operation}")
    if frame.blocked:
        summary_bits.append(f"阻塞项:{len(frame.blocked)}")
    return "；".join(summary_bits) if summary_bits else "需要补充信息。"


def legacy_understanding_from_frame(frame: IntentFrame) -> dict[str, Any]:
    """逆向重建 legacy understanding dict（键集与 understand_request 现状同构）。"""
    tasks = [
        {
            "id": t.id,
            "title": t.title,
            "subject_type": t.subject_type,
            "subject_label": t.subject_label,
            "tickers": list(t.tickers),
            "operation": {"name": t.operation, "confidence": t.operation_confidence, "params": dict(t.params)},
            "required_evidence": list(t.required_evidence),
            "priority": t.priority,
            "order_index": t.order_index,
            "request_frame_id": t.request_frame_id,
            "render_kind": t.render_kind,
            "render_group_id": t.render_group_id,
            "reason": t.reason,
            "answer_requirements": list(t.answer_requirements), "time_scope": dict(t.time_scope),
            "constraints": list(t.constraints), "requirements_status": t.requirements_status,
            "evidence_support_for": t.evidence_support_for, "request_text": t.request_text,
        }
        for t in frame.tasks
    ]
    blocked_tasks = [
        {
            "id": b.id,
            "title": b.title,
            "subject_type": b.subject_type,
            "subject_label": b.subject_label,
            "tickers": list(b.tickers),
            "operation": {"name": b.operation, "confidence": 0.0},
            "priority": b.priority,
            "order_index": b.order_index,
            "request_frame_id": b.request_frame_id,
            "render_kind": b.render_kind,
            "render_group_id": b.render_group_id,
            "error_code": b.error_code,
            "reason": b.reason,
            "question": b.question,
            "suggestions": list(b.suggestions),
            "fallback_allowed": b.fallback_allowed,
            "answer_requirements": list(b.answer_requirements), "required_evidence": list(b.required_evidence),
            "time_scope": dict(b.time_scope), "constraints": list(b.constraints), "requirements_status": b.requirements_status,
        }
        for b in frame.blocked
    ]
    return {
        "route": frame.route,
        "original_query": frame.query,
        "cleaned_query": frame.query,
        "language": frame.language,
        "user_visible_summary": _user_visible_summary(frame),
        "confidence": frame.confidence,
        "tasks": tasks,
        "blocked_tasks": blocked_tasks,
        "context_refs": list(frame.context_refs),
        "fallback_assumptions": list(frame.fallback_assumptions),
        "intent_frame": frame.model_dump(),
        "requirements_status": frame.requirements_status, "semantic_contract": dict(frame.semantic_contract),
        "request_frames": list(frame.request_frames),
    }


__all__ = [
    "BlockedIntent",
    "IntentFrame",
    "IntentTask",
    "intent_frame_from_legacy",
    "legacy_understanding_from_frame",
]

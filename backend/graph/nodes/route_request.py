# -*- coding: utf-8 -*-
"""请求理解节点：一次性完成闲聊、标的、任务和阻塞项识别。"""
from __future__ import annotations

import os
from typing import Any

from backend.config.ticker_mapping import normalize_ticker
from backend.graph.investment_intent import query_requests_investment_opinion
from backend.graph.intent.deterministic_engine import route_request_deterministic
from backend.graph.intent.frame import intent_frame_from_legacy
from backend.graph.state import GraphState


def _bind_task_render_identity(result: dict[str, Any]) -> dict[str, Any]:
    """在 intent 出口封装任务身份；不读取计划、证据或执行结果。"""
    understanding = result.get("understanding") if isinstance(result.get("understanding"), dict) else {}
    ready = result.get("tasks") if isinstance(result.get("tasks"), list) else understanding.get("tasks")
    blocked = result.get("blocked_tasks") if isinstance(result.get("blocked_tasks"), list) else understanding.get("blocked_tasks")
    ready = [item for item in (ready or []) if isinstance(item, dict)]
    blocked = [item for item in (blocked or []) if isinstance(item, dict)]
    query = str(understanding.get("original_query") or result.get("query") or "")
    has_bound_opinion = any(
        str((item.get("operation") or {}).get("name") or "") == "investment_opinion"
        and bool(item.get("tickers"))
        for item in ready
        if isinstance(item.get("operation"), dict)
    )
    has_blocked_opinion = any(
        str(
            (item.get("operation") or {}).get("name")
            if isinstance(item.get("operation"), dict)
            else item.get("operation") or ""
        ).strip() == "investment_opinion"
        or str(item.get("error_code") or item.get("reason") or "").strip() == "task_missing_subject"
        for item in blocked
    )
    if query_requests_investment_opinion(query) and not has_bound_opinion and not has_blocked_opinion:
        blocked.append({
            "id": f"blocked_{len(blocked) + 1}",
            "title": "需要补充分析标的",
            "subject_type": "company",
            "subject_label": "未指定分析对象",
            "tickers": [],
            "operation": {"name": "investment_opinion", "confidence": 0.0},
            "priority": 50,
            "reason": "task_missing_subject",
            "error_code": "task_missing_subject",
            "question": "请补充需要分析的股票或基金代码。",
            "suggestions": [],
            "fallback_allowed": False,
        })
    frames = result.get("request_frames") if isinstance(result.get("request_frames"), list) else []
    frames = [item for item in frames if isinstance(item, dict)]
    if not frames and isinstance(result.get("request_frame"), dict):
        frames = [result["request_frame"]]

    def _frame_for_task(task: dict[str, Any], ordinal: int) -> dict[str, Any]:
        explicit_id = str(task.get("request_frame_id") or "").strip()
        if explicit_id:
            explicit = [frame for frame in frames if str(frame.get("frame_id") or "").strip() == explicit_id]
            if len(explicit) == 1:
                return explicit[0]
        task_tickers = {
            normalize_ticker(str(value))
            for value in (task.get("tickers") if isinstance(task.get("tickers"), list) else [])
            if normalize_ticker(str(value))
        }
        task_subject = str(task.get("subject_type") or "unknown").strip().lower()
        operation = task.get("operation") if isinstance(task.get("operation"), dict) else {}
        task_operation = str(operation.get("name") or task.get("operation") or "qa").strip()
        scored: list[tuple[int, int, dict[str, Any]]] = []
        for index, frame in enumerate(frames):
            subject = frame.get("subject") if isinstance(frame.get("subject"), dict) else {}
            frame_tickers = {
                normalize_ticker(str(value))
                for value in (subject.get("tickers") if isinstance(subject.get("tickers"), list) else [])
                if normalize_ticker(str(value))
            }
            frame_subject = str(subject.get("type") or "unknown").strip().lower()
            legacy_operation = frame.get("legacy_operation") if isinstance(frame.get("legacy_operation"), dict) else {}
            frame_operation = str(legacy_operation.get("name") or "").strip()
            relation = str(frame.get("relation") or "").strip().lower()
            render = frame.get("render_contract") if isinstance(frame.get("render_contract"), dict) else {}
            compare = relation in {"compare", "rank"} or render.get("shape") == "compare"
            score = 0
            if task_tickers and frame_tickers and task_tickers <= frame_tickers:
                score += 8 if compare else 5
            elif task_tickers or frame_tickers:
                continue
            if task_subject == frame_subject:
                score += 4
            elif task_subject == "macro" or frame_subject == "macro":
                continue
            if frame_operation and task_operation == frame_operation:
                score += 3
            if compare and task_operation == "compare":
                score += 2
            if score:
                scored.append((-score, index, frame))
        if scored:
            return sorted(scored, key=lambda item: (item[0], item[1]))[0][2]
        if len(frames) == 1:
            return frames[0]
        return {
            "frame_id": f"request_frame_{ordinal}",
            "relation": "single",
            "subject": {"type": task_subject, "tickers": sorted(task_tickers)},
            "render_contract": {"shape": "answer"},
        }

    for order_index, task in enumerate([*ready, *blocked]):
        frame = _frame_for_task(task, order_index)
        frame_id = str(task.get("request_frame_id") or frame.get("frame_id") or f"request_frame_{order_index}").strip()
        render = frame.get("render_contract") if isinstance(frame.get("render_contract"), dict) else {}
        relation = str(frame.get("relation") or "").strip().lower()
        operation = task.get("operation") if isinstance(task.get("operation"), dict) else {}
        operation_name = str(operation.get("name") or task.get("operation") or "qa").strip()
        render_kind = "compare" if relation in {"compare", "rank"} or render.get("shape") == "compare" or operation_name == "compare" else "single"
        tickers = []
        for ticker in task.get("tickers") if isinstance(task.get("tickers"), list) else []:
            normalized = normalize_ticker(str(ticker))
            if normalized and normalized not in tickers:
                tickers.append(normalized)
        subject_label = str(task.get("subject_label") or task.get("subject_type") or "未指定分析对象").strip() or "未指定分析对象"
        task.update({
            "title": str(task.get("title") or subject_label).strip() or subject_label,
            "subject_label": subject_label,
            "tickers": tickers,
            "priority": max(0, int(task.get("priority"))) if isinstance(task.get("priority"), int) else 50,
            "order_index": order_index,
            "request_frame_id": frame_id,
            "render_kind": render_kind,
            "render_group_id": str(task.get("render_group_id") or frame_id).strip() or frame_id,
        })
        if order_index >= len(ready):
            task.setdefault("error_code", str(task.get("reason") or "task_blocked").strip() or "task_blocked")
    understanding["tasks"] = ready
    understanding["blocked_tasks"] = blocked
    result["understanding"] = understanding
    result["tasks"] = ready
    result["blocked_tasks"] = blocked
    return result


async def route_request(state: GraphState) -> dict[str, Any]:
    """规则优先地生成请求、任务与渲染身份，全程不调用 LLM。"""
    resolver_enabled = str(os.getenv("FINSIGHT_FINANCIAL_TERM_RESOLVER", "on")).strip().lower() != "off"
    if resolver_enabled:
        from backend.graph.intent.financial_terms import (
            build_financial_term_direct_result,
            resolve_financial_term_definition,
        )

        options = state.get("options") if isinstance(state.get("options"), dict) else {}
        ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
        forced_agent = bool(options.get("agents")) or bool(ui_context.get("agents_override"))
        match = resolve_financial_term_definition(
            str(state.get("query") or ""), str(state.get("output_mode") or "chat"), forced_agent=forced_agent,
        )
        if match is not None:
            return build_financial_term_direct_result(state, match)

    result = _bind_task_render_identity(await route_request_deterministic(state))
    understanding = result.get("understanding") if isinstance(result.get("understanding"), dict) else {}
    frame = intent_frame_from_legacy(understanding)
    frame.source = "deterministic_rules"
    understanding["intent_frame"] = frame.model_dump()
    return result


__all__ = ["route_request"]

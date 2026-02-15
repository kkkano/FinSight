# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Callable

from backend.contracts import TRACE_SCHEMA_VERSION
from backend.graph.event_bus import emit_event
from backend.graph.state import GraphState
from backend.services.langfuse_tracer import langfuse_span


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_preview(value: Any, *, limit: int = 240) -> Any:
    try:
        if value is None:
            return None
        if isinstance(value, (int, float, bool)):
            return value
        if isinstance(value, str):
            return value if len(value) <= limit else value[:limit] + "…"
        if isinstance(value, list):
            return value[:8]
        if isinstance(value, dict):
            return {k: _safe_preview(v, limit=limit) for k, v in list(value.items())[:12]}
        return str(value)[:limit]
    except Exception:
        return None


def _has_meaningful_input(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _resolve_input_state(*values: Any) -> str:
    if any(isinstance(v, str) and "***" in v for v in values if isinstance(v, str)):
        return "redacted"
    return "explicit" if any(_has_meaningful_input(v) for v in values) else "empty"


def _resolve_input_sources(state: GraphState) -> list[str]:
    sources: list[str] = []
    query = state.get("query")
    ui_context = state.get("ui_context")
    subject = state.get("subject")
    policy = state.get("policy")
    if _has_meaningful_input(query):
        sources.append("state.query")
    if isinstance(ui_context, dict):
        if _has_meaningful_input(ui_context.get("active_symbol")):
            sources.append("state.ui_context.active_symbol")
        if _has_meaningful_input(ui_context.get("selections")):
            sources.append("state.ui_context.selections")
    if isinstance(subject, dict) and _has_meaningful_input(subject.get("tickers")):
        sources.append("state.subject.tickers")
    if isinstance(policy, dict):
        if _has_meaningful_input(policy.get("allowed_tools")):
            sources.append("state.policy.allowed_tools")
        if _has_meaningful_input(policy.get("allowed_agents")):
            sources.append("state.policy.allowed_agents")
    return sources


def _span_data(node_name: str, state: GraphState, updates: dict[str, Any]) -> dict[str, Any]:
    """
    Build a small, UI-friendly summary for a node span.
    Keep it compact (avoid dumping large tool outputs).
    """

    try:
        if node_name == "normalize_ui_context":
            ui = updates.get("ui_context") or state.get("ui_context") or {}
            selections = ui.get("selections") if isinstance(ui, dict) else None
            selections = selections if isinstance(selections, list) else []
            types = sorted({str(s.get("type")) for s in selections if isinstance(s, dict) and s.get("type")})
            return {"selections": {"count": len(selections), "types": types[:8]}}

        if node_name == "decide_output_mode":
            return {"output_mode": updates.get("output_mode")}

        if node_name == "resolve_subject":
            subj = updates.get("subject") or state.get("subject") or {}
            if isinstance(subj, dict):
                return {
                    "subject_type": subj.get("subject_type"),
                    "tickers": (subj.get("tickers") or [])[:3],
                    "selection_types": (subj.get("selection_types") or [])[:5],
                }
            return {}

        if node_name == "clarify":
            clarify = updates.get("clarify") or state.get("clarify") or {}
            if isinstance(clarify, dict):
                return {
                    "needed": clarify.get("needed"),
                    "reason": clarify.get("reason"),
                    "question": clarify.get("question"),
                }
            return {}

        if node_name == "parse_operation":
            op = updates.get("operation") or state.get("operation") or {}
            if isinstance(op, dict):
                query = state.get("query")
                return {
                    "operation": op.get("name"),
                    "confidence": op.get("confidence"),
                    "input_state": _resolve_input_state(query),
                    "input_sources": ["state.query"] if _has_meaningful_input(query) else [],
                }
            return {}

        if node_name == "policy_gate":
            policy = updates.get("policy") or state.get("policy") or {}
            if isinstance(policy, dict):
                budget = policy.get("budget") or {}
                tools = policy.get("allowed_tools") or []
                selection = policy.get("agent_selection") or {}
                selected_agents = selection.get("selected") if isinstance(selection, dict) else []
                selected_agents = selected_agents if isinstance(selected_agents, list) else []
                required_agents = selection.get("required") if isinstance(selection, dict) else []
                required_agents = required_agents if isinstance(required_agents, list) else []
                scores = selection.get("scores") if isinstance(selection, dict) else {}
                scores = scores if isinstance(scores, dict) else {}
                reasons = selection.get("reasons") if isinstance(selection, dict) else {}
                reasons = reasons if isinstance(reasons, dict) else {}
                score_rows: list[dict[str, Any]] = []
                for name in selected_agents[:8]:
                    if not isinstance(name, str):
                        continue
                    reason_items = reasons.get(name) if isinstance(reasons.get(name), list) else []
                    score_rows.append(
                        {
                            "agent": name,
                            "score": _safe_preview(scores.get(name)),
                            "reasons": [_safe_preview(item, limit=120) for item in reason_items[:6]],
                        }
                    )
                return {
                    "decision_type": "policy_gate",
                    "summary": (
                        f"selected={len(selected_agents)} required={len(required_agents)} "
                        f"tools={len(tools) if isinstance(tools, list) else 0}"
                    ),
                    "fallback_reason": str(policy.get("fallback_reason") or "none"),
                    "budget": budget,
                    "allowed_tools": tools[:12],
                    "allowed_tools_count": len(tools) if isinstance(tools, list) else None,
                    "input_state": _resolve_input_state(state.get("query"), state.get("subject"), state.get("ui_context")),
                    "input_sources": _resolve_input_sources(state),
                    "selection_summary": (
                        f"selected={len(selected_agents)} required={len(required_agents)} tools={len(tools) if isinstance(tools, list) else 0}"
                    ),
                    "agent_selection": {
                        "selected": selected_agents[:8],
                        "required": required_agents[:8],
                        "scored": score_rows,
                    },
                }
            return {}

        if node_name == "planner":
            plan = updates.get("plan_ir") or state.get("plan_ir") or {}
            trace_patch = updates.get("trace") or {}
            runtime = trace_patch.get("planner_runtime") if isinstance(trace_patch, dict) else None
            if isinstance(plan, dict):
                steps = plan.get("steps") or []
                preview_steps = []
                if isinstance(steps, list):
                    for s in steps[:10]:
                        if not isinstance(s, dict):
                            continue
                        preview_steps.append(
                            {
                                "id": s.get("id"),
                                "kind": s.get("kind"),
                                "name": s.get("name"),
                                "why": _safe_preview(s.get("why"), limit=160),
                                "parallel_group": s.get("parallel_group"),
                            }
                        )
                return {
                    "decision_type": "planner",
                    "summary": (
                        f"plan={len(steps) if isinstance(steps, list) else 0} steps, "
                        f"first={preview_steps[0].get('name') if preview_steps else 'none'}"
                    ),
                    "fallback_reason": str((runtime or {}).get("reason") or "none") if isinstance(runtime, dict) else "none",
                    "planner_runtime": runtime,
                    "steps": preview_steps,
                    "step_count": len(steps) if isinstance(steps, list) else 0,
                    "input_state": _resolve_input_state(state.get("query"), state.get("policy"), state.get("subject")),
                    "input_sources": _resolve_input_sources(state),
                    "decision_summary": (
                        f"plan={len(steps) if isinstance(steps, list) else 0} steps, "
                        f"first={preview_steps[0].get('name') if preview_steps else 'none'}"
                    ),
                }
            return {"planner_runtime": runtime}

        if node_name == "execute_plan":
            artifacts = updates.get("artifacts") or state.get("artifacts") or {}
            trace_patch = updates.get("trace") or {}
            executor = trace_patch.get("executor") if isinstance(trace_patch, dict) else None
            plan = state.get("plan_ir") or {}
            step_index: dict[str, dict[str, Any]] = {}
            if isinstance(plan, dict):
                for s in plan.get("steps") or []:
                    if isinstance(s, dict) and s.get("id"):
                        step_index[str(s.get("id"))] = s
            if isinstance(artifacts, dict):
                step_results = artifacts.get("step_results")
                if isinstance(step_results, dict):
                    compact = []
                    for step_id, item in list(step_results.items())[:12]:
                        if not isinstance(item, dict):
                            continue
                        output = item.get("output")
                        step_meta = step_index.get(str(step_id)) or {}
                        status_reason = "done"
                        if isinstance(output, dict):
                            if output.get("skipped") is True:
                                status_reason = str(output.get("reason") or "skipped")
                            elif output.get("error"):
                                status_reason = str(output.get("error"))
                        compact.append(
                            {
                                "id": step_id,
                                "name": step_meta.get("name"),
                                "kind": step_meta.get("kind"),
                                "parallel_group": item.get("parallel_group") or step_meta.get("parallel_group"),
                                "cached": item.get("cached"),
                                "skipped": isinstance(output, dict) and output.get("skipped") is True,
                                "status_reason": status_reason,
                                "duration_ms": item.get("duration_ms"),
                                "output_preview": None
                                if isinstance(output, dict) and output.get("skipped") is True
                                else _safe_preview(output, limit=240),
                            }
                        )
                    done_count = sum(1 for row in compact if not row.get("skipped") and not row.get("status_reason") == "error")
                    skip_count = sum(1 for row in compact if row.get("skipped"))
                    return {
                        "decision_type": "execute_plan",
                        "summary": f"steps={len(compact)} done={done_count} skipped={skip_count}",
                        "fallback_reason": "none",
                        "executor": executor,
                        "steps": compact,
                        "input_state": _resolve_input_state(state.get("plan_ir"), state.get("policy")),
                        "input_sources": _resolve_input_sources(state),
                    }
            return {"executor": executor}

        if node_name == "synthesize":
            artifacts = updates.get("artifacts") or state.get("artifacts") or {}
            trace_patch = updates.get("trace") or {}
            runtime = trace_patch.get("synthesize_runtime") if isinstance(trace_patch, dict) else None
            render_vars = artifacts.get("render_vars") if isinstance(artifacts, dict) else None
            keys = sorted(render_vars.keys()) if isinstance(render_vars, dict) else []
            return {
                "decision_type": "synthesize",
                "summary": f"render_vars={len(keys)}",
                "fallback_reason": str((runtime or {}).get("reason") or "none") if isinstance(runtime, dict) else "none",
                "synthesize_runtime": runtime,
                "render_vars_keys": keys[:16],
            }

        if node_name == "render":
            artifacts = updates.get("artifacts") or state.get("artifacts") or {}
            md = artifacts.get("draft_markdown") if isinstance(artifacts, dict) else None
            if isinstance(md, str):
                return {"draft_markdown_len": len(md), "draft_markdown_preview": _safe_preview(md, limit=140)}
            return {}

    except Exception:
        return {}

    return {}


def with_node_trace(node_name: str, fn: Callable[[GraphState], Any]) -> Callable[[GraphState], Any]:
    """
    Wrap a node function to append a lightweight span into state.trace.

    Phase 1: span collection is returned in response (and can be emitted to SSE in stub mode).
    Later phases may stream real-time node events.
    """

    async def _wrapped(state: GraphState) -> dict:
        base_trace = state.get("trace") or {}
        spans = list(base_trace.get("spans") or [])

        # ========== SSE 实时推送：节点启动 ==========
        await emit_event(
            {
                "schema_version": TRACE_SCHEMA_VERSION,
                "type": "thinking",
                "stage": f"langgraph_{node_name}_start",
                "message": node_name,
                "timestamp": _utc_now_iso(),
            }
        )

        start = time.perf_counter()

        # ========== Langfuse 桥接：节点级 Span ==========
        # langfuse_span 内部处理 Langfuse 未启用 / 异常场景，保证不影响主流程
        async with langfuse_span(node_name) as lf_span:
            maybe_updates = fn(state)
            updates = (
                await maybe_updates
                if asyncio.iscoroutine(maybe_updates)
                else (maybe_updates or {})
            )
            duration_ms = int((time.perf_counter() - start) * 1000)
            data = _span_data(node_name, state, updates) or {}

            # 将节点产出同步写入 Langfuse Span
            if lf_span is not None:
                try:
                    lf_span.update(
                        output=data,
                        metadata={"duration_ms": duration_ms},
                    )
                except Exception:
                    pass

        # ========== 内部 Trace 收集（SSE 推送用） ==========
        span: dict[str, Any] = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "node": node_name,
            "duration_ms": duration_ms,
            "ts": _utc_now_iso(),
        }
        if data:
            span["data"] = data
        spans.append(span)

        # SSE 实时推送：节点完成
        await emit_event(
            {
                "schema_version": TRACE_SCHEMA_VERSION,
                "type": "thinking",
                "stage": f"langgraph_{node_name}_done",
                "message": node_name,
                "result": {"duration_ms": duration_ms, **(data or {})},
                "timestamp": _utc_now_iso(),
            }
        )

        patch_trace = updates.get("trace") or {}
        merged_trace: dict[str, Any] = {
            **base_trace,
            **patch_trace,
            "schema_version": TRACE_SCHEMA_VERSION,
            "spans": spans,
        }
        updates["trace"] = merged_trace
        return updates

    return _wrapped

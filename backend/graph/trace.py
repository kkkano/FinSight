# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any, Callable

from backend.contracts import TRACE_SCHEMA_VERSION
from backend.graph.event_bus import emit_event
from backend.graph.state import GraphState


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
                return {"operation": op.get("name"), "confidence": op.get("confidence")}
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
                    "budget": budget,
                    "allowed_tools": tools[:12],
                    "allowed_tools_count": len(tools) if isinstance(tools, list) else None,
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
                            }
                        )
                return {
                    "planner_runtime": runtime,
                    "steps": preview_steps,
                    "step_count": len(steps) if isinstance(steps, list) else 0,
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
                        compact.append(
                            {
                                "id": step_id,
                                "name": step_meta.get("name"),
                                "kind": step_meta.get("kind"),
                                "cached": item.get("cached"),
                                "skipped": isinstance(output, dict) and output.get("skipped") is True,
                                "output_preview": None
                                if isinstance(output, dict) and output.get("skipped") is True
                                else _safe_preview(output, limit=240),
                            }
                        )
                    return {"executor": executor, "steps": compact}
            return {"executor": executor}

        if node_name == "synthesize":
            artifacts = updates.get("artifacts") or state.get("artifacts") or {}
            trace_patch = updates.get("trace") or {}
            runtime = trace_patch.get("synthesize_runtime") if isinstance(trace_patch, dict) else None
            render_vars = artifacts.get("render_vars") if isinstance(artifacts, dict) else None
            keys = sorted(render_vars.keys()) if isinstance(render_vars, dict) else []
            return {"synthesize_runtime": runtime, "render_vars_keys": keys[:16]}

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

        # Real-time stream: node start (stream endpoint sets event emitter).
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
        maybe_updates = fn(state)
        updates = await maybe_updates if asyncio.iscoroutine(maybe_updates) else (maybe_updates or {})
        duration_ms = int((time.perf_counter() - start) * 1000)

        data = _span_data(node_name, state, updates) or {}
        span: dict[str, Any] = {
            "schema_version": TRACE_SCHEMA_VERSION,
            "node": node_name,
            "duration_ms": duration_ms,
            "ts": _utc_now_iso(),
        }
        if data:
            span["data"] = data
        spans.append(span)

        # Real-time stream: node done with compact summary.
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

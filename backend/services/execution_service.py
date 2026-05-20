"""
Shared graph pipeline execution service.

Both ``/chat/supervisor/stream`` and ``/api/execute`` delegate to
:func:`run_graph_pipeline` so that streaming logic is never duplicated.
"""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional
from uuid import uuid4

from backend.report.quality_engine import apply_quality_to_report, record_quality_metrics

logger = logging.getLogger("execution_service")


def _utc_iso_now() -> str:
    return datetime.now(UTC).isoformat()


def _normalize_run_id(run_id: str | None) -> str:
    value = str(run_id or "").strip()
    return value or str(uuid4())


def _normalize_report_source_type(source: str | None) -> str:
    raw = str(source or "").strip().lower()
    if not raw:
        return "ai_generated"
    if raw.startswith("dashboard"):
        return "dashboard"
    if raw.startswith("chat"):
        return "chat"
    if raw.startswith("workbench"):
        return "workbench"
    return raw[:64]


def _resolve_ticker_override(ui_context: dict[str, Any] | None) -> str | None:
    if not isinstance(ui_context, dict):
        return None
    tickers = ui_context.get("tickers_override")
    if not isinstance(tickers, list):
        return None
    for item in tickers:
        value = str(item or "").strip().upper()
        if value:
            return value
    return None


def _annotate_report_source(
    report: dict[str, Any] | None,
    source: str | None,
    ticker_override: str | None = None,
) -> dict[str, Any] | None:
    if not isinstance(report, dict):
        return report

    source_type = _normalize_report_source_type(source)
    report["source_type"] = source_type

    normalized_ticker = str(ticker_override or "").strip().upper()
    if normalized_ticker:
        report["ticker"] = normalized_ticker

    meta = report.get("meta")
    if not isinstance(meta, dict):
        meta = {}
    meta["source_type"] = source_type
    if source:
        meta["source_trigger"] = str(source).strip()
    report["meta"] = meta
    return report


def _ensure_deliverable_markdown(state: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    artifacts = state.get("artifacts") if isinstance(state.get("artifacts"), dict) else {}
    markdown = str(artifacts.get("draft_markdown") or "")
    if markdown.strip():
        return markdown, state
    try:
        from backend.graph.nodes.render_stub import render_stub

        rendered = render_stub(state)
        rendered_artifacts = rendered.get("artifacts") if isinstance(rendered, dict) else None
        if isinstance(rendered_artifacts, dict):
            state = {**state, "artifacts": rendered_artifacts}
            markdown = str(rendered_artifacts.get("draft_markdown") or "")
            if markdown.strip():
                return markdown, state
    except Exception as exc:
        logger.warning("[execution_service] final render fallback failed: %s", exc)
    query = str(state.get("query") or "这个问题").strip()
    markdown = f"这轮没有合成出可用文字，但我已经保留了上下文。你可以直接重试：{query}\n"
    state = {**state, "artifacts": {**artifacts, "draft_markdown": markdown}}
    return markdown, state


def _apply_quality_gate(
    *,
    report: dict[str, Any] | None,
    source: str,
) -> tuple[dict[str, Any], bool]:
    quality, blocked = apply_quality_to_report(report)
    record_quality_metrics(quality, source=source)
    return quality, blocked


def _execution_timeout_seconds(output_mode: str | None = None, ui_context: dict[str, Any] | None = None) -> float:
    """
    Resolve execution timeout with mode-aware defaults.

    - brief/chat/default: LANGGRAPH_EXECUTION_TIMEOUT_SECONDS (default 500s)
    - investment_report: LANGGRAPH_EXECUTION_TIMEOUT_REPORT_SECONDS (default 900s)
      fallback to LANGGRAPH_EXECUTION_TIMEOUT_SECONDS when report-specific key is absent.
    """
    mode = (output_mode or "").strip().lower()
    default_base = "500"
    default_report = "900"
    raw = (
        os.getenv("LANGGRAPH_EXECUTION_TIMEOUT_REPORT_SECONDS", default_report)
        if mode == "investment_report"
        else os.getenv("LANGGRAPH_EXECUTION_TIMEOUT_SECONDS", default_base)
    )
    try:
        default_timeout = max(60.0, float(raw))
    except Exception:
        default_timeout = 900.0 if mode == "investment_report" else 500.0
    try:
        from backend.graph.preference_timeouts import timeout_seconds_from_ui_context

        preferred_timeout = timeout_seconds_from_ui_context(ui_context)
        if preferred_timeout is not None:
            return preferred_timeout
    except Exception:
        pass
    return default_timeout


def _cancelled_trace_payload() -> dict[str, Any]:
    return {
        "type": "trace",
        "stage": "cancelled",
        "status": "cancelled",
        "visibility": "user",
        "title": "已停止生成",
        "summary": "已停止生成，保留已完成的结果。",
        "timestamp": _utc_iso_now(),
    }


def _cancelled_pipeline_payload() -> dict[str, Any]:
    return {
        "type": "pipeline_stage",
        "stage": "cancelled",
        "status": "cancelled",
        "message": "Generation cancelled by client",
        "timestamp": _utc_iso_now(),
    }


# ---------------------------------------------------------------------------
# Dependency injection container
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExecutionDeps:
    """Injected from the application layer (main.py) — keeps this module pure."""

    get_graph_runner: Callable[[], Awaitable[Any]]
    schedule_report_index: Callable[..., None]
    update_session_context: Callable[..., None]
    redact_sensitive_payload: Callable[[Any], Any]
    is_raw_trace_event: Callable[[dict[str, Any]], bool]
    contract_info: Callable[[], dict[str, str]]
    sse_event_schema_version: str


# ---------------------------------------------------------------------------
# Core pipeline
# ---------------------------------------------------------------------------

async def run_graph_pipeline(
    *,
    deps: ExecutionDeps,
    query: str,
    thread_id: str,
    run_id: str | None = None,
    ui_context: dict[str, Any] | None = None,
    output_mode: str | None = None,
    strict_selection: str | None = None,
    confirmation_mode: str | None = None,
    original_query: str | None = None,
    source: str | None = None,
    trace_raw_enabled: bool = False,
    markdown_chunk_size: int = 60,
) -> AsyncGenerator[dict[str, Any], None]:
    """Yield SSE-compatible event dicts for a full graph run.

    The caller (chat_router / execution_router) only needs to iterate
    this generator and serialise each dict as ``data: <json>\\n\\n``.

    Parameters
    ----------
    deps:
        Application-level dependencies.
    query:
        Resolved user query (after reference resolution).
    thread_id:
        Normalised session / thread identifier.
    ui_context:
        Contextual hints from the frontend (active_symbol, view, …).
    output_mode:
        ``chat`` | ``brief`` | ``investment_report``.
    strict_selection:
        Whether to force selection-centric analysis.
    original_query:
        The raw user query *before* reference resolution (for session
        context bookkeeping).  Falls back to *query* when ``None``.
    source:
        Trigger origin for observability (``"chat"`` / ``"execute"`` /
        ``"workbench"`` / …).
    trace_raw_enabled:
        If ``False``, intermediate graph trace events are filtered out
        and only essential types (``token``, ``done``, ``error``) are
        forwarded.
    markdown_chunk_size:
        Characters per ``token`` event when streaming the final
        markdown response.
    """
    from backend.graph.event_bus import reset_event_emitter, set_event_emitter
    from backend.graph.cancellation import reset_cancel_event, set_cancel_event
    from backend.orchestration.trace_emitter import TraceEvent, get_trace_emitter

    queue: asyncio.Queue[object] = asyncio.Queue()
    _END = object()
    cancel_event = asyncio.Event()
    run_id_value = _normalize_run_id(run_id)
    request_started_at = _utc_iso_now()
    stream_metrics: dict[str, int] = {
        "llm_start": 0,
        "llm_call": 0,
        "llm_end": 0,
        "tool_start": 0,
        "tool_call": 0,
        "tool_end": 0,
        "agent_start": 0,
        "agent_done": 0,
    }

    def _record_stream_metric(payload: dict[str, Any]) -> None:
        event_type = str(payload.get("type") or "").strip()
        if event_type in stream_metrics:
            stream_metrics[event_type] += 1

    def _stamp_ids(payload: dict[str, Any]) -> dict[str, Any]:
        outgoing = deps.redact_sensitive_payload(dict(payload))
        original_schema = outgoing.get("schema_version")
        if (
            isinstance(original_schema, str)
            and original_schema
            and original_schema != deps.sse_event_schema_version
        ):
            outgoing["trace_schema_version"] = original_schema
        outgoing["schema_version"] = deps.sse_event_schema_version
        outgoing.setdefault("session_id", thread_id)
        outgoing.setdefault("run_id", run_id_value)
        return outgoing

    async def _queue_event(payload: dict[str, Any], *, record_metric: bool = True) -> None:
        outgoing = _stamp_ids(payload)
        if record_metric:
            _record_stream_metric(outgoing)
        await queue.put(outgoing)

    # -- internal emitter (graph nodes call emit_event → _emit) ------------

    async def _emit(payload: dict) -> None:
        if (not trace_raw_enabled) and deps.is_raw_trace_event(payload):
            return
        await _queue_event(payload)

    def _enqueue_trace_event(event: TraceEvent) -> None:
        if event is None:
            return
        try:
            payload = event.to_sse_dict()
        except Exception:
            return

        if (not trace_raw_enabled) and deps.is_raw_trace_event(payload):
            return

        outgoing = _stamp_ids(payload)
        _record_stream_metric(outgoing)

        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(queue.put_nowait, outgoing)
        except Exception:
            pass

    # -- producer coroutine ------------------------------------------------

    async def _producer() -> None:
        token = set_event_emitter(_emit)
        cancel_token = set_cancel_event(cancel_event)
        trace_emitter = get_trace_emitter()
        trace_emitter.add_listener(_enqueue_trace_event)
        try:
            # 1. langgraph_start
            await _queue_event(
                {
                    "schema_version": deps.sse_event_schema_version,
                    "type": "thinking",
                    "stage": "langgraph_start",
                    "message": "LangGraph",
                    "timestamp": _utc_iso_now(),
                }
            )

            # 2. Run the graph（通过 Langfuse Trace 入口）
            runner = await deps.get_graph_runner()

            from backend.graph.runner import run_graph_traced
            timeout_seconds = _execution_timeout_seconds(output_mode, ui_context=ui_context)
            try:
                state = await asyncio.wait_for(
                    run_graph_traced(
                        runner,
                        thread_id=thread_id,
                        query=query,
                        ui_context=ui_context or {},
                        output_mode=output_mode,
                        strict_selection=strict_selection,
                        confirmation_mode=confirmation_mode,
                    ),
                    timeout=timeout_seconds,
                )
            except asyncio.TimeoutError:
                cancel_event.set()
                logger.error(
                    "[execution_service] graph timeout thread_id=%s timeout=%ss query=%s",
                    thread_id,
                    timeout_seconds,
                    (query or "")[:120],
                )
                await _queue_event(
                    {
                        "schema_version": deps.sse_event_schema_version,
                        "type": "error",
                        "message": f"Execution timed out after {int(timeout_seconds)}s; please retry with brief mode or fewer agents.",
                    }
                )
                return

            # 2b. Check if the graph was interrupted (human-in-the-loop)
            # LangGraph stores pending interrupts in __interrupt__ state key
            pending_interrupts = state.get("__interrupt__")
            if pending_interrupts:
                # Extract interrupt info and forward to client
                interrupt_data: dict[str, Any] = {
                    "thread_id": thread_id,
                }
                if isinstance(pending_interrupts, (list, tuple)) and len(pending_interrupts) > 0:
                    first = pending_interrupts[0]
                    if hasattr(first, "value"):
                        interrupt_data["data"] = first.value
                    elif isinstance(first, dict):
                        interrupt_data["data"] = first
                await _queue_event(
                    {
                        "schema_version": deps.sse_event_schema_version,
                        "type": "interrupt",
                        **interrupt_data,
                    }
                )
                await queue.put(_END)
                return

            markdown, state = _ensure_deliverable_markdown(state)

            # 3. Build report payload
            report: dict[str, Any] | None = None
            try:
                from backend.graph.report_builder import build_report_payload

                report = build_report_payload(
                    state=state, query=query, thread_id=thread_id,
                )
                report = _annotate_report_source(
                    report,
                    source,
                    ticker_override=_resolve_ticker_override(ui_context),
                )
            except Exception as exc:
                logger.warning(
                    "[execution_service] report build failed: %s",
                    exc,
                    exc_info=True,
                )
            report_quality, quality_blocked = _apply_quality_gate(
                report=report,
                source="execute_run",
            )
            blocked_report_preview = report if quality_blocked and isinstance(report, dict) else None
            # 软阻断：质量门控 blocked 但报告已生成时，仍然交付内容并附带警告
            soft_blocked = quality_blocked and blocked_report_preview is not None
            is_report_mode = str(state.get("output_mode") or "").strip().lower() == "investment_report"
            response_markdown = (
                markdown
                if (soft_blocked or not is_report_mode)
                else ("" if quality_blocked else markdown)
            )
            if not str(response_markdown or "").strip():
                query_preview = str(query or "这个问题").strip()
                response_markdown = f"这轮没有合成出可用文字，但我已经保留了上下文。你可以直接重试：{query_preview}\n"
            persisted_report = report if soft_blocked else (None if quality_blocked else report)

            if quality_blocked:
                blocked_reason_codes = [
                    str(item.get("code") or "").strip()
                    for item in (report_quality.get("reasons") or [])
                    if isinstance(item, dict)
                ]
                await _queue_event(
                    {
                        "type": "quality_blocked",
                        "message": "Report quality warning" if soft_blocked else "Report blocked by quality gate",
                        "quality": report_quality,
                        "blocked_reason_codes": [code for code in blocked_reason_codes if code],
                        "publishable": soft_blocked,
                        "blocked_report_available": bool(blocked_report_preview),
                        "allow_continue_when_blocked": True,
                        "soft_blocked": soft_blocked,
                    }
                )
            if isinstance(report, dict):
                # 4. Persist report index (async / fire-and-forget)
                deps.schedule_report_index(
                    session_id=thread_id, report=report, state=state,
                )

            # 5. Update conversational session context
            deps.update_session_context(
                thread_id=thread_id,
                original_query=original_query or query,
                response_markdown=response_markdown,
                subject=state.get("subject"),
                skip_context=bool(state.get("skip_session_context")),
            )

            # 5b. Persist lightweight long-term memory snapshot (best-effort)
            if not quality_blocked or soft_blocked:
                try:
                    from backend.graph.store import persist_memory_snapshot

                    persist_memory_snapshot(
                        thread_id=thread_id,
                        state=state,
                        report=report,
                    )
                except Exception as exc:
                    logger.warning("[execution_service] persist memory snapshot failed: %s", exc)

            if not quality_blocked or soft_blocked:
                # 6. Stream markdown in chunks
                await _queue_event(
                    {
                        "schema_version": deps.sse_event_schema_version,
                        "type": "pipeline_stage",
                        "stage": "rendering",
                        "status": "start",
                        "message": "Rendering markdown stream",
                        "timestamp": _utc_iso_now(),
                    }
                )
                for idx in range(0, len(markdown), markdown_chunk_size):
                    chunk = markdown[idx: idx + markdown_chunk_size]
                    if chunk:
                        await _queue_event(
                            {
                                "schema_version": deps.sse_event_schema_version,
                                "type": "token",
                                "content": chunk,
                            }
                        )
                    await asyncio.sleep(0)

                await _queue_event(
                    {
                        "schema_version": deps.sse_event_schema_version,
                        "type": "pipeline_stage",
                        "stage": "rendering",
                        "status": "done",
                        "message": "Rendering stream completed",
                        "timestamp": _utc_iso_now(),
                    }
                )

                await _queue_event(
                    {
                        "schema_version": deps.sse_event_schema_version,
                        "type": "pipeline_stage",
                        "stage": "done",
                        "status": "done",
                        "message": "Execution completed",
                        "timestamp": _utc_iso_now(),
                    }
                )

            # 7. Final "done" event
            llm_total_calls = stream_metrics.get("llm_start", 0)
            if llm_total_calls <= 0:
                llm_total_calls = stream_metrics.get("llm_call", 0)

            tool_total_calls = stream_metrics.get("tool_start", 0)
            if tool_total_calls <= 0:
                tool_total_calls = stream_metrics.get("tool_call", 0)

            await _queue_event(
                {
                    "schema_version": deps.sse_event_schema_version,
                    "type": "done",
                    "contracts": deps.contract_info(),
                    "intent": "chat",
                    "session_id": thread_id,
                    "source": source,
                    "response": response_markdown,
                    "report": persisted_report,
                    "blocked_report": blocked_report_preview,
                    "quality": report_quality,
                    "quality_blocked": quality_blocked and not soft_blocked,
                    "publishable": not quality_blocked or soft_blocked,
                    "blocked_report_available": bool(blocked_report_preview),
                    "allow_continue_when_blocked": True,
                    "soft_blocked": soft_blocked,
                    "graph": {
                        "subject": state.get("subject"),
                        "output_mode": state.get("output_mode"),
                        "trace": state.get("trace"),
                    },
                    "metrics": {
                        **stream_metrics,
                        "llm_total_calls": llm_total_calls,
                        "tool_total_calls": tool_total_calls,
                        "request_started_at": request_started_at,
                        "request_finished_at": _utc_iso_now(),
                    },
                }
            )
        except asyncio.CancelledError:
            cancel_event.set()
            await _queue_event(_cancelled_trace_payload(), record_metric=False)
            await _queue_event(_cancelled_pipeline_payload(), record_metric=False)
            logger.info("[execution_service] graph run cancelled thread_id=%s", thread_id)
        except Exception as exc:
            logger.error(
                "[execution_service] unhandled: %s", exc, exc_info=True,
            )
            await _queue_event(
                {
                    "schema_version": deps.sse_event_schema_version,
                    "type": "error",
                    "message": "Internal server error",
                }
            )
        finally:
            trace_emitter.remove_listener(_enqueue_trace_event)
            reset_cancel_event(cancel_token)
            reset_event_emitter(token)
            await queue.put(_END)

    # -- launch & yield ----------------------------------------------------

    producer_task = asyncio.create_task(_producer())

    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=3)
            except asyncio.TimeoutError:
                yield {"type": "keep-alive", "ts": _utc_iso_now()}
                continue

            if item is _END:
                break
            if isinstance(item, dict):
                yield item
    finally:
        if not producer_task.done():
            cancel_event.set()
            producer_task.cancel()
            try:
                await producer_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Resume pipeline (for human-in-the-loop interrupt/resume flow)
# ---------------------------------------------------------------------------

async def resume_graph_pipeline(
    *,
    deps: ExecutionDeps,
    thread_id: str,
    run_id: str | None = None,
    resume_value: Any,
    source: str | None = None,
    trace_raw_enabled: bool = False,
    markdown_chunk_size: int = 60,
) -> AsyncGenerator[dict[str, Any], None]:
    """Resume an interrupted graph run and yield SSE-compatible events.

    Mirrors the structure of :func:`run_graph_pipeline` but instead of
    starting a new run it sends ``Command(resume=resume_value)`` to the
    checkpointed graph via ``runner.resume()``.
    """
    from backend.graph.event_bus import reset_event_emitter, set_event_emitter
    from backend.graph.cancellation import reset_cancel_event, set_cancel_event
    from backend.orchestration.trace_emitter import TraceEvent, get_trace_emitter

    queue: asyncio.Queue[object] = asyncio.Queue()
    _END = object()
    cancel_event = asyncio.Event()
    run_id_value = _normalize_run_id(run_id)
    request_started_at = _utc_iso_now()

    def _stamp_ids(payload: dict[str, Any]) -> dict[str, Any]:
        outgoing = deps.redact_sensitive_payload(dict(payload))
        original_schema = outgoing.get("schema_version")
        if (
            isinstance(original_schema, str)
            and original_schema
            and original_schema != deps.sse_event_schema_version
        ):
            outgoing["trace_schema_version"] = original_schema
        outgoing["schema_version"] = deps.sse_event_schema_version
        outgoing.setdefault("session_id", thread_id)
        outgoing.setdefault("run_id", run_id_value)
        return outgoing

    async def _queue_event(payload: dict[str, Any]) -> None:
        await queue.put(_stamp_ids(payload))

    # -- internal emitter ---------------------------------------------------

    async def _emit(payload: dict) -> None:
        if (not trace_raw_enabled) and deps.is_raw_trace_event(payload):
            return
        await _queue_event(payload)

    def _enqueue_trace_event(event: TraceEvent) -> None:
        if event is None:
            return
        try:
            payload = event.to_sse_dict()
        except Exception:
            return
        if (not trace_raw_enabled) and deps.is_raw_trace_event(payload):
            return
        outgoing = _stamp_ids(payload)
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(queue.put_nowait, outgoing)
        except Exception:
            pass

    # -- producer coroutine ------------------------------------------------

    async def _producer() -> None:
        token = set_event_emitter(_emit)
        cancel_token = set_cancel_event(cancel_event)
        trace_emitter = get_trace_emitter()
        trace_emitter.add_listener(_enqueue_trace_event)
        try:
            await _queue_event(
                {
                    "schema_version": deps.sse_event_schema_version,
                    "type": "thinking",
                    "stage": "resume_start",
                    "message": "Resuming execution",
                    "timestamp": _utc_iso_now(),
                }
            )

            runner = await deps.get_graph_runner()

            # Collect final state from the stream events
            final_state: dict[str, Any] = {}
            async for event in runner.resume(
                thread_id=thread_id,
                resume_value=resume_value,
            ):
                event_name = event.get("event", "")
                # Forward interrupt events to the client
                if "interrupt" in event_name:
                    await _queue_event(
                        {
                            "schema_version": deps.sse_event_schema_version,
                            "type": "interrupt",
                            "thread_id": thread_id,
                            "data": event.get("data", {}),
                        }
                    )
                # Capture final state from on_chain_end
                if event_name == "on_chain_end" and event.get("data", {}).get("output"):
                    final_state = event["data"]["output"]

            # Build report from final state
            markdown, final_state = _ensure_deliverable_markdown(final_state)
            report: dict[str, Any] | None = None
            try:
                from backend.graph.report_builder import build_report_payload
                report = build_report_payload(
                    state=final_state, query=final_state.get("query", ""), thread_id=thread_id,
                )
                report = _annotate_report_source(report, source)
            except Exception as exc:
                logger.warning("[resume_pipeline] report build failed: %s", exc)
            report_quality, quality_blocked = _apply_quality_gate(
                report=report,
                source="execute_resume",
            )
            blocked_report_preview = report if quality_blocked and isinstance(report, dict) else None
            # 软阻断：质量门控 blocked 但报告已生成时，仍然交付内容并附带警告
            soft_blocked = quality_blocked and blocked_report_preview is not None
            is_report_mode = str(final_state.get("output_mode") or "").strip().lower() == "investment_report"
            response_markdown = (
                markdown
                if (soft_blocked or not is_report_mode)
                else ("" if quality_blocked else markdown)
            )
            if not str(response_markdown or "").strip():
                query_preview = str(final_state.get("query") or "这个问题").strip()
                response_markdown = f"这轮没有合成出可用文字，但我已经保留了上下文。你可以直接重试：{query_preview}\n"
            persisted_report = report if soft_blocked else (None if quality_blocked else report)

            if quality_blocked:
                blocked_reason_codes = [
                    str(item.get("code") or "").strip()
                    for item in (report_quality.get("reasons") or [])
                    if isinstance(item, dict)
                ]
                await _queue_event(
                    {
                        "type": "quality_blocked",
                        "message": "Report quality warning" if soft_blocked else "Report blocked by quality gate",
                        "quality": report_quality,
                        "blocked_reason_codes": [code for code in blocked_reason_codes if code],
                        "publishable": soft_blocked,
                        "blocked_report_available": bool(blocked_report_preview),
                        "allow_continue_when_blocked": True,
                        "soft_blocked": soft_blocked,
                    }
                )
            if isinstance(report, dict):
                # Persist report index
                deps.schedule_report_index(
                    session_id=thread_id, report=report, state=final_state,
                )

            # Persist lightweight long-term memory snapshot (best-effort)
            if not quality_blocked or soft_blocked:
                try:
                    from backend.graph.store import persist_memory_snapshot

                    persist_memory_snapshot(
                        thread_id=thread_id,
                        state=final_state,
                        report=report,
                    )
                except Exception as exc:
                    logger.warning("[resume_pipeline] persist memory snapshot failed: %s", exc)

            if not quality_blocked or soft_blocked:
                # Stream markdown
                await _queue_event(
                    {
                        "schema_version": deps.sse_event_schema_version,
                        "type": "pipeline_stage",
                        "stage": "rendering",
                        "status": "start",
                        "message": "Rendering markdown stream",
                        "timestamp": _utc_iso_now(),
                    }
                )
                for idx in range(0, len(markdown), markdown_chunk_size):
                    chunk = markdown[idx: idx + markdown_chunk_size]
                    if chunk:
                        await _queue_event(
                            {
                                "schema_version": deps.sse_event_schema_version,
                                "type": "token",
                                "content": chunk,
                            }
                        )
                    await asyncio.sleep(0)

                await _queue_event(
                    {
                        "schema_version": deps.sse_event_schema_version,
                        "type": "pipeline_stage",
                        "stage": "rendering",
                        "status": "done",
                        "message": "Rendering stream completed",
                        "timestamp": _utc_iso_now(),
                    }
                )

                await _queue_event(
                    {
                        "schema_version": deps.sse_event_schema_version,
                        "type": "pipeline_stage",
                        "stage": "done",
                        "status": "done",
                        "message": "Execution completed",
                        "timestamp": _utc_iso_now(),
                    }
                )

            # Done
            await _queue_event(
                {
                    "schema_version": deps.sse_event_schema_version,
                    "type": "done",
                    "contracts": deps.contract_info(),
                    "intent": "resume",
                    "session_id": thread_id,
                    "source": source,
                    "response": response_markdown,
                    "report": persisted_report,
                    "blocked_report": blocked_report_preview,
                    "quality": report_quality,
                    "quality_blocked": quality_blocked and not soft_blocked,
                    "publishable": not quality_blocked or soft_blocked,
                    "blocked_report_available": bool(blocked_report_preview),
                    "allow_continue_when_blocked": True,
                    "soft_blocked": soft_blocked,
                    "metrics": {
                        "request_started_at": request_started_at,
                        "request_finished_at": _utc_iso_now(),
                    },
                }
            )
        except asyncio.CancelledError:
            cancel_event.set()
            await _queue_event(_cancelled_trace_payload())
            await _queue_event(_cancelled_pipeline_payload())
            logger.info("[resume_pipeline] graph resume cancelled thread_id=%s", thread_id)
        except Exception as exc:
            logger.error("[resume_pipeline] unhandled: %s", exc, exc_info=True)
            await _queue_event(
                {
                    "schema_version": deps.sse_event_schema_version,
                    "type": "error",
                    "message": "Resume execution failed",
                }
            )
        finally:
            trace_emitter.remove_listener(_enqueue_trace_event)
            reset_cancel_event(cancel_token)
            reset_event_emitter(token)
            await queue.put(_END)

    # -- launch & yield ----------------------------------------------------

    producer_task = asyncio.create_task(_producer())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=3)
            except asyncio.TimeoutError:
                yield {"type": "keep-alive", "ts": _utc_iso_now()}
                continue
            if item is _END:
                break
            if isinstance(item, dict):
                yield item
    finally:
        if not producer_task.done():
            cancel_event.set()
            producer_task.cancel()
            try:
                await producer_task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass

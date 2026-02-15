"""
Shared graph pipeline execution service.

Both ``/chat/supervisor/stream`` and ``/api/execute`` delegate to
:func:`run_graph_pipeline` so that streaming logic is never duplicated.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, AsyncGenerator, Awaitable, Callable, Optional

logger = logging.getLogger("execution_service")


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
    ui_context: dict[str, Any] | None = None,
    output_mode: str | None = None,
    strict_selection: str | None = None,
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
    from backend.orchestration.trace_emitter import TraceEvent, get_trace_emitter

    queue: asyncio.Queue[object] = asyncio.Queue()
    _END = object()
    request_started_at = datetime.utcnow().isoformat()
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

    # -- internal emitter (graph nodes call emit_event → _emit) ------------

    async def _emit(payload: dict) -> None:
        if (not trace_raw_enabled) and deps.is_raw_trace_event(payload):
            return
        outgoing = deps.redact_sensitive_payload(dict(payload))
        original_schema = outgoing.get("schema_version")
        if (
            isinstance(original_schema, str)
            and original_schema
            and original_schema != deps.sse_event_schema_version
        ):
            outgoing["trace_schema_version"] = original_schema
        outgoing["schema_version"] = deps.sse_event_schema_version
        _record_stream_metric(outgoing)
        await queue.put(outgoing)

    def _enqueue_trace_event(event: TraceEvent) -> None:
        if event is None:
            return
        try:
            payload = event.to_sse_dict()
        except Exception:
            return

        if (not trace_raw_enabled) and deps.is_raw_trace_event(payload):
            return

        outgoing = deps.redact_sensitive_payload(dict(payload))
        outgoing["schema_version"] = deps.sse_event_schema_version
        _record_stream_metric(outgoing)

        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(queue.put_nowait, outgoing)
        except Exception:
            pass

    # -- producer coroutine ------------------------------------------------

    async def _producer() -> None:
        token = set_event_emitter(_emit)
        trace_emitter = get_trace_emitter()
        trace_emitter.add_listener(_enqueue_trace_event)
        try:
            # 1. langgraph_start
            await queue.put(
                {
                    "schema_version": deps.sse_event_schema_version,
                    "type": "thinking",
                    "stage": "langgraph_start",
                    "message": "LangGraph",
                    "timestamp": datetime.utcnow().isoformat(),
                }
            )

            # 2. Run the graph（通过 Langfuse Trace 入口）
            runner = await deps.get_graph_runner()

            from backend.graph.runner import run_graph_traced
            state = await run_graph_traced(
                runner,
                thread_id=thread_id,
                query=query,
                ui_context=ui_context or {},
                output_mode=output_mode,
                strict_selection=strict_selection,
            )
            markdown = ((state.get("artifacts") or {}).get("draft_markdown")) or ""

            # 3. Build report payload
            report: dict[str, Any] | None = None
            try:
                from backend.graph.report_builder import build_report_payload

                report = build_report_payload(
                    state=state, query=query, thread_id=thread_id,
                )
            except Exception as exc:
                logger.warning(
                    "[execution_service] report build failed: %s",
                    exc,
                    exc_info=True,
                )

            # 4. Persist report index (async / fire-and-forget)
            deps.schedule_report_index(
                session_id=thread_id, report=report, state=state,
            )

            # 5. Update conversational session context
            deps.update_session_context(
                thread_id=thread_id,
                original_query=original_query or query,
                response_markdown=markdown,
                subject=state.get("subject"),
            )

            # 6. Stream markdown in chunks
            for idx in range(0, len(markdown), markdown_chunk_size):
                chunk = markdown[idx: idx + markdown_chunk_size]
                if chunk:
                    await queue.put(
                        {
                            "schema_version": deps.sse_event_schema_version,
                            "type": "token",
                            "content": chunk,
                        }
                    )
                await asyncio.sleep(0)

            # 7. Final "done" event
            llm_total_calls = stream_metrics.get("llm_start", 0)
            if llm_total_calls <= 0:
                llm_total_calls = stream_metrics.get("llm_call", 0)

            tool_total_calls = stream_metrics.get("tool_start", 0)
            if tool_total_calls <= 0:
                tool_total_calls = stream_metrics.get("tool_call", 0)

            await queue.put(
                {
                    "schema_version": deps.sse_event_schema_version,
                    "type": "done",
                    "contracts": deps.contract_info(),
                    "intent": "chat",
                    "session_id": thread_id,
                    "source": source,
                    "response": markdown,
                    "report": report,
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
                        "request_finished_at": datetime.utcnow().isoformat(),
                    },
                }
            )
        except Exception as exc:
            logger.error(
                "[execution_service] unhandled: %s", exc, exc_info=True,
            )
            await queue.put(
                deps.redact_sensitive_payload(
                    {
                        "schema_version": deps.sse_event_schema_version,
                        "type": "error",
                        "message": "Internal server error",
                    }
                )
            )
        finally:
            trace_emitter.remove_listener(_enqueue_trace_event)
            reset_event_emitter(token)
            await queue.put(_END)

    # -- launch & yield ----------------------------------------------------

    producer_task = asyncio.create_task(_producer())

    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=5)
            except asyncio.TimeoutError:
                yield {"type": "keep-alive"}
                continue

            if item is _END:
                break
            if isinstance(item, dict):
                yield item
    finally:
        if not producer_task.done():
            producer_task.cancel()
            try:
                await producer_task
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Resume pipeline (for human-in-the-loop interrupt/resume flow)
# ---------------------------------------------------------------------------

async def resume_graph_pipeline(
    *,
    deps: ExecutionDeps,
    thread_id: str,
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
    from backend.orchestration.trace_emitter import TraceEvent, get_trace_emitter

    queue: asyncio.Queue[object] = asyncio.Queue()
    _END = object()
    request_started_at = datetime.utcnow().isoformat()

    # -- internal emitter ---------------------------------------------------

    async def _emit(payload: dict) -> None:
        if (not trace_raw_enabled) and deps.is_raw_trace_event(payload):
            return
        outgoing = deps.redact_sensitive_payload(dict(payload))
        outgoing["schema_version"] = deps.sse_event_schema_version
        await queue.put(outgoing)

    def _enqueue_trace_event(event: TraceEvent) -> None:
        if event is None:
            return
        try:
            payload = event.to_sse_dict()
        except Exception:
            return
        if (not trace_raw_enabled) and deps.is_raw_trace_event(payload):
            return
        outgoing = deps.redact_sensitive_payload(dict(payload))
        outgoing["schema_version"] = deps.sse_event_schema_version
        try:
            loop = asyncio.get_running_loop()
            loop.call_soon_threadsafe(queue.put_nowait, outgoing)
        except Exception:
            pass

    # -- producer coroutine ------------------------------------------------

    async def _producer() -> None:
        token = set_event_emitter(_emit)
        trace_emitter = get_trace_emitter()
        trace_emitter.add_listener(_enqueue_trace_event)
        try:
            await queue.put(
                {
                    "schema_version": deps.sse_event_schema_version,
                    "type": "thinking",
                    "stage": "resume_start",
                    "message": "Resuming execution",
                    "timestamp": datetime.utcnow().isoformat(),
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
                    await queue.put(
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
            markdown = ((final_state.get("artifacts") or {}).get("draft_markdown")) or ""
            report: dict[str, Any] | None = None
            try:
                from backend.graph.report_builder import build_report_payload
                report = build_report_payload(
                    state=final_state, query=final_state.get("query", ""), thread_id=thread_id,
                )
            except Exception as exc:
                logger.warning("[resume_pipeline] report build failed: %s", exc)

            # Persist report index
            deps.schedule_report_index(
                session_id=thread_id, report=report, state=final_state,
            )

            # Stream markdown
            for idx in range(0, len(markdown), markdown_chunk_size):
                chunk = markdown[idx: idx + markdown_chunk_size]
                if chunk:
                    await queue.put(
                        {
                            "schema_version": deps.sse_event_schema_version,
                            "type": "token",
                            "content": chunk,
                        }
                    )
                await asyncio.sleep(0)

            # Done
            await queue.put(
                {
                    "schema_version": deps.sse_event_schema_version,
                    "type": "done",
                    "contracts": deps.contract_info(),
                    "intent": "resume",
                    "session_id": thread_id,
                    "source": source,
                    "response": markdown,
                    "report": report,
                    "metrics": {
                        "request_started_at": request_started_at,
                        "request_finished_at": datetime.utcnow().isoformat(),
                    },
                }
            )
        except Exception as exc:
            logger.error("[resume_pipeline] unhandled: %s", exc, exc_info=True)
            await queue.put(
                deps.redact_sensitive_payload(
                    {
                        "schema_version": deps.sse_event_schema_version,
                        "type": "error",
                        "message": "Resume execution failed",
                    }
                )
            )
        finally:
            trace_emitter.remove_listener(_enqueue_trace_event)
            reset_event_emitter(token)
            await queue.put(_END)

    # -- launch & yield ----------------------------------------------------

    producer_task = asyncio.create_task(_producer())
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=5)
            except asyncio.TimeoutError:
                yield {"type": "keep-alive"}
                continue
            if item is _END:
                break
            if isinstance(item, dict):
                yield item
    finally:
        if not producer_task.done():
            producer_task.cancel()
            try:
                await producer_task
            except Exception:
                pass

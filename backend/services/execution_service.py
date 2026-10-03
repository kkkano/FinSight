"""
Shared graph pipeline execution service.

``/api/execute`` delegates to
:func:`run_graph_pipeline` so that streaming logic is never duplicated.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, AsyncGenerator, Awaitable, Callable
from uuid import uuid4

from backend.report.quality_engine import apply_quality_to_report, record_quality_metrics
from backend.services.llm_usage import (
    TokenUsageAccumulator,
    set_token_accumulator,
)

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
        from backend.graph.nodes.render_node import render_node as render_stub

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


def _llm_degradation(
    state: dict[str, Any],
    usage_summary: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    def _stable_reason(value: Any, default: str = "llm_unavailable") -> str:
        raw = str(value or "").strip().lower()
        allowed = {
            "llm_unavailable",
            "provider_timeout",
            "rate_limited",
            "all_llm_attempts_failed",
            "configuration",
            "llm_output_truncated", "llm_empty_output", "llm_output_invalid", "authentication", "quota_exhausted", "invalid_request",
        }
        if raw in allowed:
            return raw
        if "timeout" in raw or "timed out" in raw:
            return "provider_timeout"
        if any(token in raw for token in ("rate", "429", "quota", "too many")):
            return "rate_limited"
        if raw in {"configuration", "config", "configuration_error"}:
            return "configuration"
        return default

    trace = state.get("trace") if isinstance(state.get("trace"), dict) else {}
    conversation = trace.get("conversation_degraded") if isinstance(trace, dict) else None
    if isinstance(conversation, dict) and conversation.get("used"):
        return {
            "used": True,
            "stage": str(conversation.get("stage") or "conversation"),
            "reason": _stable_reason(conversation.get("reason")),
        }
    synth = trace.get("synthesize_runtime") if isinstance(trace, dict) else None
    if isinstance(synth, dict) and synth.get("fallback"):
        return {
            "used": True,
            "stage": "synthesis",
            "reason": _stable_reason(synth.get("reason")),
        }
    usage = usage_summary if isinstance(usage_summary, dict) else {}
    calls = max(0, int(usage.get("llm_token_calls") or 0))
    failed_calls = max(0, int(usage.get("failed_llm_calls") or 0))
    if calls > 0 and failed_calls >= calls:
        return {
            "used": True,
            "stage": "runtime",
            "reason": "all_llm_attempts_failed",
        }
    return None


def _degradation_message(degradation: dict[str, Any]) -> str:
    return {
        "llm_output_truncated": "模型输出达到长度上限，回答被截断；本轮保留已核验数据，请重新生成。",
        "llm_empty_output": "模型返回空正文，研究回答未完成；本轮保留已核验数据，可重新生成。",
        "llm_output_invalid": "模型返回格式无法解析，本轮已使用已核验数据生成降级回答。",
        "provider_timeout": "模型生成超时，本轮保留已核验数据，请稍后重试。",
        "rate_limited": "模型服务触发频率限制，本轮保留已核验数据，请稍后重试。",
        "quota_exhausted": "模型供应商拒绝了调用额度，请检查供应商账户后重试。",
        "authentication": "模型服务认证失败，请检查模型配置后重试。",
        "invalid_request": "模型服务拒绝了请求参数，请检查模型兼容配置。",
        "configuration": "模型配置异常，本轮保留已核验数据，请检查配置。",
    }.get(str(degradation.get("reason") or ""), "模型调用失败，本轮已使用降级回答；结果可能不完整，请稍后重试。")


def _apply_quality_gate(
    *,
    report: dict[str, Any] | None,
    source: str,
) -> tuple[dict[str, Any], bool]:
    quality, blocked = apply_quality_to_report(report)
    record_quality_metrics(quality, source=source)
    return quality, blocked


def _resolve_cache_ticker(ui_context: dict[str, Any] | None, output_mode: str | None) -> str | None:
    """P1-7: 解析可用于报告缓存的 ticker。

    只有 investment_report 模式 + 显式单 ticker（tickers_override）才走缓存，
    避免把 Chat 上下文里的 active_symbol 误当作查询意图。
    """
    if str(output_mode or "").strip().lower() != "investment_report":
        return None
    context = ui_context or {}
    tickers_override = context.get("tickers_override")
    if isinstance(tickers_override, list) and len(tickers_override) == 1:
        ticker = str(tickers_override[0] or "").strip().upper()
        return ticker or None
    return None


async def _replay_cached_report(
    queue_event,
    *,
    deps: "ExecutionDeps",
    thread_id: str,
    source: str,
    cached: dict[str, Any],
    markdown_chunk_size: int,
) -> None:
    """P1-7: 回放缓存的报告（跳过整个图执行，零 LLM 成本）。"""
    report = cached.get("report")
    markdown = str(cached.get("markdown") or "")

    await queue_event(
        {
            "schema_version": deps.sse_event_schema_version,
            "type": "pipeline_stage",
            "stage": "rendering",
            "status": "start",
            "message": "命中报告缓存，直接返回（零成本）",
            "timestamp": _utc_iso_now(),
        }
    )
    for idx in range(0, len(markdown), markdown_chunk_size):
        chunk = markdown[idx: idx + markdown_chunk_size]
        if chunk:
            await queue_event(
                {
                    "schema_version": deps.sse_event_schema_version,
                    "type": "token",
                    "content": chunk,
                }
            )
        await asyncio.sleep(0)
    await queue_event(
        {
            "schema_version": deps.sse_event_schema_version,
            "type": "pipeline_stage",
            "stage": "done",
            "status": "done",
            "message": "Execution completed (cached)",
            "timestamp": _utc_iso_now(),
        }
    )
    quality = {}
    if isinstance(report, dict):
        quality = report.get("report_quality") or {}
    await queue_event(
        {
            "schema_version": deps.sse_event_schema_version,
            "type": "done",
            "contracts": deps.contract_info(),
            "intent": "chat",
            "session_id": thread_id,
            "source": source,
            "response": markdown,
            "report": report,
            "cached": True,
            "quality": quality,
            "quality_blocked": False,
            "publishable": True,
            "metrics": {"cached": True, "cache_created_at": cached.get("created_at")},
        }
    )


def _execution_timeout_seconds(output_mode: str | None = None) -> float:
    """
    Resolve execution timeout with mode-aware defaults.

    - brief/chat/default: LANGGRAPH_EXECUTION_TIMEOUT_SECONDS (default 3600s)
    - investment_report: LANGGRAPH_EXECUTION_TIMEOUT_REPORT_SECONDS (default 7200s)
      fallback to LANGGRAPH_EXECUTION_TIMEOUT_SECONDS when report-specific key is absent.
    """
    mode = (output_mode or "").strip().lower()
    default_base = "3600"
    default_report = "7200"
    raw = (
        os.getenv("LANGGRAPH_EXECUTION_TIMEOUT_REPORT_SECONDS", default_report)
        if mode == "investment_report"
        else os.getenv("LANGGRAPH_EXECUTION_TIMEOUT_SECONDS", default_base)
    )
    try:
        default_timeout = max(60.0, float(raw))
    except Exception:
        default_timeout = 7200.0 if mode == "investment_report" else 3600.0
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
    original_query: str | None = None,
    source: str | None = None,
    user_id: str = "public",
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
        Trigger origin for observability (``"chat"`` / ``"execute"`` / …).
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
    token_acc = TokenUsageAccumulator(user_id=user_id)
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
        # 每个 run 独立的 token 累加器（create_task 复制 context，天然隔离，无需 reset）
        set_token_accumulator(token_acc)
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

            graph_ui_context = dict(ui_context or {})
            graph_ui_context.setdefault("run_id", run_id_value)
            graph_ui_context["__user_id"] = str(user_id or "public").strip() or "public"

            # 2. Run the graph（通过 Langfuse Trace 入口）
            runner = await deps.get_graph_runner()

            from backend.graph.runner import run_graph_traced
            timeout_seconds = _execution_timeout_seconds(output_mode)
            try:
                state = await asyncio.wait_for(
                    run_graph_traced(
                        runner,
                        thread_id=thread_id,
                        query=query,
                        ui_context=graph_ui_context,
                        output_mode=output_mode,
                        strict_selection=strict_selection,
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

            markdown, state = _ensure_deliverable_markdown(state)

            # 3. Build report payload
            report: dict[str, Any] | None = None
            # P1-4: 记录报告构建崩溃（执行失败），与质量门控拦截区分
            report_build_failed = False
            try:
                from backend.graph.report_builder import build_report_payload

                report = build_report_payload(
                    state=state, query=query, thread_id=thread_id,
                )
                report = _annotate_report_source(
                    report,
                    source,
                    ticker_override=_resolve_ticker_override(graph_ui_context),
                )
            except Exception as exc:
                report_build_failed = True
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
            # A blocked report may be shown to the current requester as a
            # non-publishable preview, but it is never an indexed artifact.
            soft_blocked = quality_blocked and blocked_report_preview is not None
            is_report_mode = str(state.get("output_mode") or "").strip().lower() == "investment_report"
            execution_failed = bool(report_build_failed and is_report_mode)
            response_markdown = (
                markdown
                if (soft_blocked or not is_report_mode)
                else ("" if quality_blocked else markdown)
            )
            if not str(response_markdown or "").strip():
                query_preview = str(query or "这个问题").strip()
                response_markdown = f"这轮没有合成出可用文字，但我已经保留了上下文。你可以直接重试：{query_preview}\n"
            persisted_report = None if (quality_blocked or execution_failed) else report

            if report_build_failed and is_report_mode:
                # P1-4: 报告模式下构建崩溃 = 执行失败，必须显式告知用户，
                # 不能伪装成"执行完成"（quality gate 对 None 报告不拦截）或"质量拦截"
                await _queue_event(
                    {
                        "type": "quality_blocked",
                        "code": "report_build_failed",
                        "message": "报告生成失败，当前结果无法发布或归档，请稍后重试。",
                        "failure_kind": "execution_error",
                        "failure_detail": None,
                        "quality": report_quality,
                        "blocked_reason_codes": [],
                        "publishable": False,
                        "blocked_report_available": False,
                        "allow_continue_when_blocked": True,
                        "soft_blocked": False,
                    }
                )
            elif quality_blocked:
                blocked_reason_codes = [
                    str(item.get("code") or "").strip()
                    for item in (report_quality.get("reasons") or [])
                    if isinstance(item, dict)
                ]
                await _queue_event(
                    {
                        "type": "quality_blocked",
                        "message": "Report blocked by quality gate; preview is not publishable",
                        "failure_kind": "quality_gate",
                        "failure_detail": None,
                        "quality": report_quality,
                        "blocked_reason_codes": [code for code in blocked_reason_codes if code],
                        "publishable": False,
                        "blocked_report_available": bool(blocked_report_preview),
                        "allow_continue_when_blocked": True,
                        "soft_blocked": soft_blocked,
                    }
                )
            report_archived = False
            persistence_failed = False
            if isinstance(persisted_report, dict):
                # 4. Persist before the final event. History must be readable
                # when the client observes done; sync callbacks remain valid in
                # isolated tests, while production uses an async to_thread path.
                try:
                    persistence_result = deps.schedule_report_index(
                        session_id=thread_id,
                        user_id=user_id,
                        report=persisted_report,
                        state=state,
                    )
                    if inspect.isawaitable(persistence_result):
                        persistence_result = await persistence_result
                    if persistence_result is False:
                        raise RuntimeError("report persistence unavailable")
                    report_archived = True
                except Exception as exc:
                    logger.error(
                        "[execution_service] report persistence failed thread_id=%s: %s",
                        thread_id,
                        exc,
                        exc_info=True,
                    )
                    persistence_failed = True
                    blocked_report_preview = persisted_report
                    persisted_report = None
                    await _queue_event(
                        {
                            "type": "pipeline_stage",
                            "stage": "persistence",
                            "status": "error",
                            "error_code": "report_persistence_failed",
                            "message": "报告已生成，但保存失败；当前内容仅作为临时预览，请稍后重试。",
                            "publishable": False,
                            "archived": False,
                        }
                    )

            # 5. Update conversational session context
            deps.update_session_context(
                thread_id=thread_id,
                original_query=original_query or query,
                response_markdown=response_markdown,
                subject=state.get("subject"),
                skip_context=bool(state.get("skip_session_context")),
            )

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

            usage_summary = token_acc.summary()
            degradation = _llm_degradation(state, usage_summary)
            if degradation:
                await _queue_event(
                    {
                        "schema_version": deps.sse_event_schema_version,
                        "type": "degraded",
                        "message": _degradation_message(degradation),
                        "degradation": degradation,
                    }
                )

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
                    "quality_blocked": quality_blocked,
                    "publishable": not quality_blocked and not execution_failed and not persistence_failed,
                    "archived": report_archived,
                    "error_code": (
                        "report_build_failed"
                        if execution_failed
                        else ("report_persistence_failed" if persistence_failed else None)
                    ),
                    "failure_kind": (
                        "execution_error"
                        if execution_failed
                        else (
                            "quality_gate"
                            if quality_blocked
                            else ("persistence_error" if persistence_failed else None)
                        )
                    ),
                    "blocked_report_available": bool(blocked_report_preview),
                    "allow_continue_when_blocked": True,
                    "soft_blocked": soft_blocked,
                    "degraded": bool(degradation),
                    "degradation": degradation,
                    "degradation_message": _degradation_message(degradation) if degradation else None,
                    "graph": {
                        "subject": state.get("subject"),
                        "output_mode": state.get("output_mode"),
                        "trace": state.get("trace"),
                    },
                    "metrics": {
                        **stream_metrics,
                        "llm_total_calls": llm_total_calls,
                        "tool_total_calls": tool_total_calls,
                        **usage_summary,
                        "request_started_at": request_started_at,
                        "request_finished_at": _utc_iso_now(),
                    },
                }
            )

            try:
                from backend.services.agent_run_archive import get_agent_run_archive

                get_agent_run_archive().archive_usage_summary(
                    run_id=str(run_id_value or thread_id),
                    user_id=token_acc.user_id,
                    summary=token_acc.summary(),
                    status="completed",
                )
            except Exception as archive_exc:  # noqa: BLE001 — PostgreSQL 归档为旁路
                logger.warning(
                    "[execution_service] agent run archive failed thread_id=%s: %s",
                    thread_id,
                    archive_exc,
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

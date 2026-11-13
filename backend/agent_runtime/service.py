"""唯一研究入口与完成、取消、失败三类终态。"""
import asyncio
import os
from collections import OrderedDict
from contextlib import suppress

from .config import resolve_model
from .diagnostics import error_info, exception_code
from .model import ModelTransport, ModelProtocolError, cached_tool_capability, verify_tool_capability
from .limits import LeaseLimiter, CapacityExceeded
from .events import EventSink
from .finalize import completed_event, initial_answer, persist_event
from .loop import AgentRuntime


async def run_agent_pipeline(*, deps, query, thread_id, run_id, run_context, ui_context=None,
                             output_mode=None, checkpoint=None, message_id=None, initial_seq=0,
                             strict_selection=None, **_unused):
    from backend.services.run_context import run_context_scope
    queue, sentinel = asyncio.Queue(maxsize=256), object()
    sink = EventSink(queue, run_id=run_id, session_id=thread_id, message_id=message_id,
                     initial_seq=initial_seq, checkpoint=checkpoint)
    runtime, consumer_closed = None, False

    async def publish(event):
        if not consumer_closed:
            await queue.put(event)

    async def producer():
        nonlocal runtime
        with run_context_scope(run_context):
            try:
                ui = {**(ui_context or {}), "output_mode": output_mode}
                if strict_selection is not None:
                    ui["strict_selection"] = strict_selection
                runtime = AgentRuntime(context=run_context, session_id=thread_id, query=query,
                    model=ModelTransport(resolve_model()), emit=sink.emit,
                    history=ui.get("session_history", []), ui_context=ui)
                sink.runtime = runtime
                _ACTIVE[(run_context.owner, run_id)] = runtime
                if ui.get("resume_from_run_id"):
                    await asyncio.to_thread(runtime.data.restore, ui["resume_from_run_id"])
                if output_mode in {"report", "investment_report"}:
                    runtime.report_title = "研究报告"
                await sink.emit("run.accepted", {"runtime": "agent_runtime", "status": "running"})
                async with runtime.limiter.slot("root", run_context.owner,
                        max(1, int(os.getenv("FINSIGHT_AGENT_MAX_ACTIVE_RUNS", "2"))),
                        owner_max=1, timeout=1, ttl=run_context.remaining_seconds + 30):
                    result = await initial_answer(runtime)
                    event = await completed_event(runtime, result, sink, deps)
            except asyncio.CancelledError:
                event = {**sink.snapshot(), "type": "cancelled", "run_id": run_id, "session_id": thread_id,
                         "run_status": "cancelled", "response": runtime.root_content if runtime else "",
                         "message": "已停止，保留已生成内容。", "publishable": False}
            except Exception as exc:
                code = exception_code(exc)
                event = {**sink.snapshot(), "type": "error", "run_id": run_id, "session_id": thread_id,
                         "run_status": "failed", "response": runtime.root_content if runtime else "",
                         "publishable": False, "answer_status": "partial" if runtime and runtime.root_content else "unavailable",
                         "message": error_info(code)["reason"], **error_info(code),
                         "metrics": {**run_context.usage.summary(), "tool_calls": runtime.tool_count if runtime else 0}}
            try:
                event.update(seq=sink.seq + 1, attempt_id=sink.epoch, stream_epoch=sink.epoch)
                committed = await asyncio.shield(persist_event(event, deps))
                run_context.finish(committed.get("run_status", "failed"))
                await publish(committed)
            except Exception:
                run_context.finish("persistence_failed")
                await publish({**event, "type": "error", "run_status": "persistence_failed",
                                 "publishable": False, "persistence_status": "unconfirmed",
                                 "message": "回答已生成，但未保存成功"})
            finally:
                if runtime:
                    for key, value in runtime.actions.items():
                        _ACTIONS[(run_context.owner, run_id, key)] = value
                    _ACTIVE.pop((run_context.owner, run_id), None)
                    with suppress(Exception):
                        await runtime.close()
                with suppress(Exception):
                    await run_context.archive_usage()
                await publish(sentinel)

    task = asyncio.create_task(producer())
    try:
        while True:
            event = await queue.get()
            if event is sentinel:
                return
            yield event
    finally:
        consumer_closed = True
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


_ACTIVE = {}
_ACTIONS = OrderedDict()

def cached_model_capability() -> dict | None:
    try:
        return cached_tool_capability(resolve_model())
    except RuntimeError:
        return None

async def preflight(context=None) -> dict:
    from fastapi import HTTPException
    try:
        model = resolve_model()
        if not model.model or not model.base_url.startswith("https://") or not model.api_key:
            raise ModelProtocolError("model_configuration_missing")
        cached = cached_tool_capability(model)
        if cached:
            return cached
        async with LeaseLimiter().slot("model", context.owner if context else "model-test",
                                       max(1, int(os.getenv("FINSIGHT_AGENT_MODEL_CONCURRENCY", "2"))),
                                       timeout=context.timeout(15) if context else 15, ttl=80):
            result = await verify_tool_capability(ModelTransport(model), timeout=context.timeout(65) if context else 65)
        return result
    except (RuntimeError, TimeoutError) as exc:
        code = getattr(exc, "code", "model_probe_timeout")
        status = 429 if isinstance(exc, CapacityExceeded) else (422 if code == "model_tool_calling_unsupported" else 503)
        message = "此模型不支持原生工具调用，请更换模型。" if status == 422 else "模型工具能力暂时无法验证，请检查配置或稍后重试。"
        raise HTTPException(status, detail={"code": code, "message": message}) from None

def add_instruction(owner: str, run_id: str, instruction: str, instruction_id: str):
    runtime = _ACTIVE.get((owner, run_id))
    if runtime is None:
        raise ValueError("run_not_active")
    return runtime.instruct(instruction, instruction_id)

async def confirm_action(owner: str, run_id: str, action_id: str, payload_hash: str, confirmed: bool,
                         *, notify_runtime: bool = True) -> dict:
    from .actions import ActionStore
    receipts = ActionStore()
    action, execute = await asyncio.to_thread(receipts.claim, owner, run_id, action_id, payload_hash, confirmed)
    if not execute:
        return action
    try:
        from backend.services.watchlist_store import get_watchlist_store
        store = get_watchlist_store()
        if action["action"] == "watchlist.add":
            await asyncio.to_thread(store.add_item, ticker=action["ticker"], user_id=owner)
        elif action["action"] == "watchlist.remove":
            await asyncio.to_thread(store.remove_item, ticker=action["ticker"], user_id=owner)
        else:
            raise ValueError("action_not_allowed")
        action["status"] = "completed"
    except Exception:
        action["status"] = "failed"
        action["error"] = "action_execution_failed"
    await asyncio.to_thread(receipts.finish, owner, run_id, action)
    runtime = _ACTIVE.get((owner, run_id))
    if runtime is not None and action_id in runtime.actions:
        runtime.actions[action_id].update(action)
        if notify_runtime:
            await runtime.emit("action.finished", {"action": action})
    return dict(action)

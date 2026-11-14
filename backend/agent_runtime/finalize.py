"""依据结构事实交付并持久化；正文始终是模型实际生成的原文。"""
import asyncio
from copy import deepcopy
import inspect
import time

from backend.services.run_context import RunContext, run_context_scope

from .citations import references
from .context import dumps
from .loop import AgentSpec, run
from .limits import CapacityExceeded
from .verifier import REVIEW_TIMEOUT_SECONDS, review_answer, should_review


async def _within_budget(runtime, seconds, operation):
    """阶段预算只缩短原截止时间；身份、用量和取消信号保持共享。"""
    parent = runtime.context
    context = RunContext(owner=parent.owner, entry=parent.entry, run_id=parent.run_id,
        deadline=min(parent.deadline, time.monotonic() + seconds), selected_model=parent.selected_model,
        cancelled=parent.cancelled, quota_checker=parent.quota_checker)
    context.usage = parent.usage
    runtime.context = context
    try:
        with run_context_scope(context):
            async with asyncio.timeout(context.remaining_seconds):
                return await operation()
    finally:
        runtime.context = parent


async def initial_answer(runtime):
    remaining = runtime.context.remaining_seconds
    reserve = min(REVIEW_TIMEOUT_SECONDS, remaining * .25)
    try:
        return await _within_budget(runtime, remaining - reserve, runtime.run_agent)
    except TimeoutError:
        if not runtime.root_content:
            raise
        if runtime._stream_text:
            partial = runtime._stream_text
            runtime._answer_parts.append((partial, "length"))
            runtime._stream_text = ""
            runtime.transcripts["root"].append({"role": "assistant", "content": partial})
        return {"stopped": "deadline", "summary": runtime.root_content}


async def _review(runtime, answer, seconds):
    review = await review_answer(runtime, answer, model=runtime.role_models.get("reviewer"), max_seconds=seconds)
    runtime.reviews.append(review)
    return review


async def review_delivery(runtime, result, sink):
    """默认核查数据回答；一次模型追加/报告修订，代码不修改答案内容。"""
    if not runtime.report_title and not runtime.ui_context.get("review_revision") and not should_review(runtime):
        runtime.accepting_instructions = False
        return result
    await runtime.emit("answer.completed", {"status": "completed", "review_pending": True})
    review = await _review(runtime, runtime.root_content, min(REVIEW_TIMEOUT_SECONDS, runtime.context.remaining_seconds))
    pending = runtime.drain("root")
    complete = review["status"] == "completed"
    missing = [item for item in review.get("coverage", []) if not item["met"]]
    revise = bool(runtime.report_title and complete and review.get("findings"))
    if not (pending or complete and (missing or revise)):
        runtime.accepting_instructions = False
        return result
    task = dumps({"instruction": (
        "根据核查意见修订报告，保留有依据的内容；可以继续调用工具，输出完整修订稿。" if revise else
        "只追加交付尚未完成的事项和新增要求，不重复、不改写之前已交付的文字。需要的资料与产物由你调用工具取得。"),
        "review": review, "existing_answer": runtime.root_content, "additional_user_messages": pending})
    agent_id = "report_revision" if revise else "root"
    transcript = deepcopy(runtime.transcripts["root"]) if revise else runtime.transcripts["root"]
    if revise:
        runtime.compactors[agent_id] = runtime.compactors["root"]
    try:
        continuation = await _within_budget(runtime, min(120, runtime.context.remaining_seconds * .65),
            lambda: run(runtime, AgentSpec(agent_id=agent_id, max_turns=4,
                tools=runtime.registry.available("root", "research_lead")), task, transcript=transcript))
    except TimeoutError:
        runtime.accepting_instructions = False
        return {**result, "stopped": "revision_deadline" if revise else "continuation_deadline"}
    except CapacityExceeded as exc:
        if str(exc) != "run_token_budget_exhausted":
            raise
        runtime.accepting_instructions = False
        return {**result, "stopped": "revision_token_budget" if revise else "continuation_token_budget"}
    runtime.accepting_instructions = False
    if revise and continuation["stopped"] == "completed":
        original = runtime.root_content
        runtime.report_revision = {"content": continuation["summary"], "original": original, "review_id": review["review_id"]}
        await runtime.emit("content.revised", {"block_id": "report_revision_" + review["review_id"],
            "text": continuation["summary"], "revision": 1, "content_phase": "answer", "review_id": review["review_id"],
            "revision_of": [key for key, block in sink.blocks.items()
                            if block["kind"] == "text" and block.get("content_phase") == "answer"]})
    answer = runtime.report_revision["content"] if runtime.report_revision else runtime.root_content
    await _review(runtime, answer, min(REVIEW_TIMEOUT_SECONDS, runtime.context.remaining_seconds))
    return continuation


def build_report(runtime, response, quality):
    citations = [{"source_id": str(key), "title": source.get("title", ""), "url": source.get("url") or "",
                  "published_date": str(source.get("published_date") or source.get("as_of") or "")}
                 for key, source in runtime.data.sources.items()]
    return {"report_id": runtime.context.run_id, "ticker": ", ".join(runtime.observed_tickers) or "RESEARCH",
            "company_name": "", "title": runtime.report_title or "研究报告", "summary": "",
            "sentiment": "unknown", "confidence_score": None,
            "sections": [{"title": runtime.report_title or "研究报告", "order": 0,
                          "contents": [{"type": "text", "content": response,
                                        "citation_refs": references(response, runtime.data.sources)["resolved"]}]}],
            "citations": citations, "report_quality": quality,
            "meta": {"runtime": "agent_runtime", "model": runtime.model.config.model,
                     "run_id": runtime.context.run_id, "artifacts": deepcopy(runtime.data.artifacts),
                     "source_count": len(citations), "report_quality": quality}}


async def completed_event(runtime, result, sink, deps):
    result = await review_delivery(runtime, result, sink)
    response = runtime.report_revision["content"] if runtime.report_revision else runtime.root_content
    review = runtime.reviews[-1] if runtime.reviews else None
    cited = references(response, runtime.data.sources)
    errors = [row for row in runtime.registry.attempts if row.get("status") == "error"]
    reasons = []
    if cited["unknown"]:
        reasons.append({"code": "unknown_citations", "severity": "warn", "source_ids": cited["unknown"]})
    if errors:
        reasons.append({"code": "partial_tool_failure", "severity": "warn", "count": len(errors)})
    if result["stopped"] != "completed":
        reasons.append({"code": "run_budget_exhausted", "severity": "warn"})
    if review:
        if review["status"] != "completed":
            reasons.append({"code": review["error_code"], "severity": "warn"})
        elif review["verdict"] != "pass" or review["findings"]:
            reasons.append({"code": "review_" + review["verdict"], "severity": "warn"})
        if any(not item["met"] for item in review.get("coverage", [])):
            reasons.append({"code": "unmet_requirements", "severity": "warn"})
    blocked = not response.strip() or bool(cited["unknown"])
    if runtime.report_title and (not review or review["status"] != "completed" or review["verdict"] != "pass"
                                or review.get("findings") or result["stopped"] != "completed"
                                or any(not item["met"] for item in review.get("coverage", []))):
        blocked = True
    quality = {"state": "block" if blocked else "warn" if reasons else "pass", "reasons": reasons,
               "source_count": len(runtime.data.sources), "evidence_ledger": list(runtime.data.sources.values()),
               "publishable": not blocked, "review": review}
    await asyncio.to_thread(runtime.data.save)
    report = build_report(runtime, response, quality) if runtime.report_title else None
    state = {"query": runtime.query, "thread_id": runtime.session_id,
             "subject": {"tickers": list(runtime.observed_tickers)},
             "artifacts": {"draft_markdown": response, "evidence_pool": list(runtime.data.sources.values()),
                           "step_results": runtime.data.results, "artifacts": runtime.data.artifacts}}
    if report is not None and not blocked:
        indexed = deps.schedule_report_index(session_id=runtime.session_id, report=report, state=state)
        if inspect.isawaitable(indexed):
            indexed = await indexed
        if indexed is False:
            from .model import ModelProtocolError
            raise ModelProtocolError("report_persistence_failed")
    updated = deps.update_session_context(thread_id=runtime.session_id, original_query=runtime.query,
        response_markdown=response, subject=state["subject"], skip_context=False)
    if inspect.isawaitable(updated):
        await updated
    selected = set(cited["resolved"])
    for artifact in runtime.data.artifacts:
        selected.update(str(value) for value in artifact.get("source_refs", []))
    event = {**sink.snapshot(), "type": "done", "schema_version": "2", "run_id": runtime.context.run_id,
             "response": response, "reviews": deepcopy(runtime.reviews), "report_revision": deepcopy(runtime.report_revision),
             "review_revision": deepcopy(runtime.ui_context.get("review_revision")),
             "session_id": runtime.session_id, "message_id": sink.message_id, "success": True,
             "run_status": "completed", "answer_status": "partial" if blocked or reasons else "answered",
             "quality": quality, "report_quality": quality, "publishable": not blocked,
             "report": report if not blocked else None, "blocked_report": report if blocked else None,
             "quality_blocked": blocked, "tickers": list(runtime.observed_tickers), "price_levels": [],
             "current_focus": next(iter(runtime.observed_tickers), None), "actions": list(runtime.actions.values()),
             "evidence_pool": [source for key, source in runtime.data.sources.items() if str(key) in selected],
             "metrics": {**runtime.context.usage.summary(), "tool_calls": runtime.tool_count,
                         "runtime": "agent_runtime", "stopped": result["stopped"]}}
    return event


async def persist_event(event, deps):
    if getattr(deps, "persist_run_event", None) is None:
        return {**event, "persistence_status": "ephemeral"}
    result = deps.persist_run_event(event)
    result = await result if inspect.isawaitable(result) else result
    if result.get("persistence_status") in {"failed", "unconfirmed"} or result.get("run_status") == "persistence_failed":
        return {**result, "type": "error", "run_status": "persistence_failed", "success": False,
                "publishable": False, "message": "回答已生成，但未保存成功"}
    return result

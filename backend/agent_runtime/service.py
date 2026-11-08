"""自主研究流与现有权威终态/报告存储的适配。"""
from __future__ import annotations

import asyncio
import inspect
import os
import re
import time
import uuid
import logging
import traceback
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from .config import resolve_model
from .context import dumps, tokens, evidence_preview
from .limits import LeaseLimiter, CapacityExceeded
from .loop import AgentRuntime
from .model import ModelProtocolError, ModelTransport, verify_tool_capability
from .grounding import cited_sources, source_urls, chart_coverages, checked_comparison_stats, validate_paragraph
from .diagnostics import error_info, exception_code
from .presentation import message_blocks, message_activities, price_levels_from_blocks, clean_public_text

logger = logging.getLogger(__name__)

_ACTIVE: dict[tuple[str, str], AgentRuntime] = {}
_ACTIONS: OrderedDict[tuple[str, str, str], dict] = OrderedDict()
MAX_REPAIR_FEEDBACK_BYTES = 10_000


def paragraph_issues(text: str, data, *, require_citations: bool = False) -> list[str]:
    """引用与事实一起核验；被修正或删除的草稿不污染最终交付质量。"""
    issues = validate_paragraph(text, data, require_citations=require_citations)
    known_urls = {source.get("url") for source in data.sources.values() if source.get("url")}
    urls = source_urls(text, data)
    refs = re.findall(r"\[\^?(S[a-fA-F0-9]+)\](?!\s*\(https?://)", text)
    if any(url not in known_urls for url in urls) or any(ref not in data.sources for ref in refs):
        issues.append("unverified_citation")
    return list(dict.fromkeys(issues))


def answer_paragraphs(text: str) -> list[str]:
    """紧邻表格的显式来源脚注属于该表，不把其它段落的引用泛化给正文。"""
    paragraphs = re.split(r"\n\s*\n", clean_public_text(text))
    result = []
    for paragraph in paragraphs:
        references = re.findall(r"\[\^?S[a-fA-F0-9]+\]", paragraph)
        stripped = re.sub(r"\[\^?S[a-fA-F0-9]+\]", "", paragraph).strip(" 。.，,；;：:")
        source_note = bool(references) and (not stripped or bool(re.match(
            r"^(?:数据)?来源\s*[:：]|^(?:上表|表中|上述|以上|[一二两三四五六七八九十]+条新闻).{0,100}(?:来自|来源|取自)", paragraph)))
        if result and source_note and len(paragraph) < 600 and re.search(r"(?m)^\s*\|.*\|\s*$", result[-1]):
            result[-1] += "\n\n" + paragraph
        else:
            result.append(paragraph)
    return result


def answer_feedback(text: str, data, *, require_citations: bool = False, short_cause: bool = False) -> str | None:
    invalid = [{"paragraph": paragraph.encode("utf-8")[:900].decode("utf-8", errors="ignore"), "issues": issues}
               for paragraph in answer_paragraphs(text)
               if (issues := paragraph_issues(paragraph, data, require_citations=require_citations))]
    if not invalid:
        return None
    header = ("请给用户一份完整答案，不写‘核对后的段落’或描述修正过程。只采用已取得资料中明确支持的结果，"
            "保留真实引用；未计算的扩展统计、未声明的延迟/交易所/复权口径不要写成事实。"
            "新闻只是返回条目，不能据此断言整个时间窗口没有新事件、利好或利空；缺失说明限定为本轮已取得的资料。"
            "交叉以comparison_stats.crossovers核验为准，共同起点的首次分离不是交叉；两个观测只支持一次相邻变化，不能写两个期间各自增长。"
            "连续下跌的ongoing表示区间尚未结束，末周是否收盘以latest_period_closed和交易日历收盘时间为准；周一日期标签不等于周收盘日。"
            "无法核实的结论用一句自然的说明交代，不输出‘已撤回’占位，也不要补入新数字。"
            "下面的事实摘要只是实际成功工具结果的投影，每条保留自己的来源；不能把某条来源用于另一主体或指标。"
            "缺少的增长率、利润率等可用已授权资料调用analyze_dataset或run_analysis_code核实，最多两轮；Python必须将输出赋给result。"
            "没有计算依据时保留已得到的数值与不依赖该数值的解释，不手算猜测，不另开无关研究。比例保留百分数单位、比例和倍数四舍五入到两位小数，不自行转倍数、取整或计算未提供的差额。")
    if short_cause:
        header = "行情价格表将由程序按真实数据直接生成。这一轮只写有原文依据的定性原因说明和证据边界，不写标题、数字、日期、表格或行情内容。说明哪项具体消息影响了市场预期，保留实际source_refs；找不到有源解释时明确说明，不能编造原因。以下是已经取得的资料。"
    issues_text = "需核对的段落摘录：" + dumps(invalid[:2])
    facts = []
    candidates = _feedback_facts(text, data)
    candidates.sort(key=lambda fact: 0 if isinstance(fact.get("result"),dict) and fact["result"].get("comparison_stats")
                    else 1 if fact.get("tool") in {"analyze_dataset","run_analysis_code"} else 2)
    for fact in candidates:
        # 来源编号足以回绑真实账本；长URL和其它诊断字段不重复占据修正上下文。
        fact = {**fact, "sources": [{"source_id": source["source_id"]} for source in fact.get("sources", [])]}
        candidate = header + "相关已核实资料：" + dumps(facts + [fact]) + issues_text
        if tokens(candidate) <= MAX_REPAIR_FEEDBACK_BYTES:
            facts.append(fact)
    return header + "相关已核实资料：" + dumps(facts) + issues_text


def _feedback_facts(text: str, data) -> list[dict]:
    """只投影当前答案相关的成功资料；不向每个段落自动附加全部来源。"""
    def subjects(ref, seen=None):
        seen = set() if seen is None else seen
        if ref in seen:
            return set()
        seen.add(ref)
        record = data.records.get(ref, {})
        inputs = record.get("inputs") or {}
        result = {str(inputs["ticker"]).upper()} if inputs.get("ticker") else set()
        for parent in inputs.get("dataset_refs") or ([inputs["dataset_ref"]] if inputs.get("dataset_ref") else []):
            result.update(subjects(parent, seen))
        return result
    bindings = {ref: subjects(ref) for ref in data.records}
    known = set().union(*bindings.values()) if bindings else set()
    mentioned = {ticker for ticker in known if re.search(r"(?<![A-Za-z0-9])" + re.escape(ticker) + r"(?![A-Za-z0-9])", text, re.I)}
    if not mentioned and len(known) == 1:
        mentioned = known
    cited_refs = {data.sources[sid].get("data_ref") for sid in cited_sources(text, data)}
    matches = [(ref, record) for ref, record in reversed(list(data.records.items()))
               if record.get("status") == "success" and
               (ref in cited_refs or bool(bindings[ref]) and bindings[ref].issubset(mentioned))]
    matches.sort(key=lambda item: 0 if isinstance(item[1].get("output"),dict) and item[1]["output"].get("comparison_stats")
                 else 1 if item[1].get("tool") in {"analyze_dataset", "run_analysis_code"} else 2)
    facts = []
    for artifact, series, coverage in chart_coverages(data, cited_sources(text, data)):
        artifact_subjects = set().union(*(bindings.get(ref, set()) for ref in artifact.get("dataset_refs", [])))
        if not artifact_subjects or not artifact_subjects.issubset(mentioned):
            continue
        refs = artifact.get("source_refs") or []
        facts.append({"tool": "render_chart", "result": {"title": artifact.get("title"), "series": series,
            "coverage": coverage}, "sources": [{"source_id": sid, "url": data.sources[sid].get("url")}
                for sid in refs if sid in data.sources]})
        if len(facts) >= 3:
            break
    for ref, record in matches[:6]:
        output = record.get("output")
        if isinstance(output, dict):
            projection = {}
            if output.get("comparison_stats") and record.get("tool") == "analyze_dataset":
                projection["comparison_stats"] = checked_comparison_stats(record)
            for key, value in output.items():
                if key in {"code", "code_hash", "input_hash"}:
                    continue
                if key == "method" and isinstance(value, dict):
                    value = {k: v for k, v in value.items() if k not in {"code", "code_hash", "input_hash"}}
                if key == "comparison_stats" and record.get("tool") == "analyze_dataset":
                    value = checked_comparison_stats(record)
                projection[key] = value
            output = evidence_preview(projection, limit=2600)
        elif isinstance(output, (str, list)):
            output = evidence_preview(output, limit=2600)
        refs = data.source_refs(ref)
        facts.append({"tool": record["tool"], "data_ref": ref, "subjects": sorted(bindings[ref]),
            "result": output, "sources": [{"source_id": sid, **{k: data.sources[sid].get(k) for k in ("title", "url", "source", "as_of")}}
                for sid in refs[:5] if sid in data.sources]})
    return facts


def verified_text(text: str, data, *, require_citations: bool = False) -> tuple[str, list[str]]:
    """保留完整合格段；不把一个错误段拆成数字碰巧命中的伪合格结论。"""
    kept, issues = [], []
    for paragraph in answer_paragraphs(text):
        violations = paragraph_issues(paragraph, data, require_citations=require_citations)
        if violations:
            issues.extend(violations)
        else:
            kept.append(paragraph)
    return "\n\n".join(kept).strip(), list(dict.fromkeys(issues))


def checked_factual_answer(runtime) -> str:
    from .fact_answer import factual_answer
    candidate = factual_answer(runtime)
    return candidate if candidate and not verified_text(candidate, runtime.data)[1] else ""


async def preflight(context=None) -> dict:
    from fastapi import HTTPException
    try:
        model = resolve_model()
        if not model.model or not model.base_url.startswith("https://") or not model.api_key:
            raise ModelProtocolError("model_configuration_missing")
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


def build_report(runtime: AgentRuntime, response: str) -> dict:
    from backend.report.validator import ReportValidator
    tickers = list(dict.fromkeys(str(record["inputs"].get("ticker")) for record in runtime.data.records.values()
                                if record["inputs"].get("ticker")))
    references = [{"source_id": sid, "title": source.get("title", ""), "url": source.get("url") or "",
                   "snippet": str(source.get("snippet") or source.get("summary") or "")[:500],
                   "published_date": str(source.get("published_date") or source.get("as_of") or "")}
                  for sid, source in runtime.data.sources.items()]
    def content_blocks(text):
        blocks = []
        for paragraph in re.split(r"\n\s*\n", text):
            if not paragraph.strip():
                continue
            refs = cited_sources(paragraph, runtime.data)
            if validate_paragraph(paragraph, runtime.data, require_citations=True):
                refs = []
            blocks.append({"type": "text", "content": paragraph, "citation_refs": refs})
        return blocks
    sections = []
    pieces = re.split(r"(?m)^#{1,3}\s+(.+)$", response)
    if pieces[0].strip():
        sections.append({"title": "研究结论", "order": 0, "contents": content_blocks(pieces[0])})
    for index in range(1, len(pieces), 2):
        sections.append({"title": pieces[index], "order": len(sections),
                         "contents": content_blocks(pieces[index + 1])})
    return ReportValidator.validate_and_fix({
        "report_id": runtime.context.run_id, "ticker": ", ".join(tickers) or "RESEARCH", "company_name": "",
        "title": runtime.report_title or runtime.query[:100], "summary": response[:600],
        "sentiment": "unknown", "confidence_score": None, "sections": sections, "citations": references,
        "meta": {"runtime": "agent", "model": runtime.model.config.model, "run_id": runtime.context.run_id,
                 "artifacts": runtime.data.artifacts, "source_count": len(references)},
    })


async def run_agent_pipeline(*, deps, query: str, thread_id: str, run_id: str,
                             run_context, ui_context: dict | None = None, output_mode: str | None = None,
                             checkpoint=None, message_id: str | None = None, strict_selection: bool | None = None,
                             initial_seq: int = 0, **_unused):
    """外层 execution_router 的后台 pump 持有本生成器；SSE订阅断开不取消pump。"""
    from backend.services.run_context import run_context_scope
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    sentinel = object()
    seq, attempt_id = initial_seq, uuid.uuid4().hex
    blocks: dict[str, dict] = {}
    thinking: list[dict] = []
    runtime = None
    last_checkpoint = 0.0

    async def emit(kind: str, payload: dict, agent_id="root"):
        nonlocal seq, last_checkpoint
        seq += 1
        outgoing = {"schema_version": "2", "type": kind, "runtime_type": kind, "run_id": run_id,
                    "session_id": thread_id, "message_id": message_id or "assistant:" + run_id, "attempt_id": attempt_id,
                    "stream_epoch": attempt_id, "seq": seq, "event_id": attempt_id + ":" + str(seq),
                    "agent_id": agent_id, "parent_agent_id": None if agent_id == "root" else "root",
                    "timestamp": datetime.now(timezone.utc).isoformat(), "payload": payload}
        if kind == "content.delta":
            outgoing.update(type="token", content=payload["delta"], block_id=payload["block_id"])
            block = blocks.setdefault(payload["block_id"], {"id": payload["block_id"], "kind": "text", "content": "", "revision": 0,
                "seq": outgoing["seq"], "agent_id": agent_id, "agent_label": payload.get("agent_label")})
            block["content"] += payload["delta"]
        elif kind == "content.block_finished" and payload.get("block_id") in blocks:
            blocks[payload["block_id"]]["content_phase"] = payload.get("content_phase", "progress")
        elif kind.startswith("reasoning."):
            block = blocks.setdefault(payload["block_id"], {"id": payload["block_id"], "kind": "reasoning", "content": "", "revision": 0,
                "reasoning_kind": payload.get("kind", "provider_raw"), "seq": outgoing["seq"],
                "agent_id": agent_id, "agent_label": payload.get("agent_label"), "provider": payload.get("provider")})
            block["content"] += str(payload.get("delta") or "")
            block["truncated"] = bool(block.get("truncated") or payload.get("truncated"))
            if payload.get("duration_ms") is not None:
                block["duration_ms"] = payload["duration_ms"]
        elif kind == "artifact.ready":
            artifact = payload["artifact"]
            blocks[artifact["artifact_id"]] = {"id": artifact["artifact_id"], "kind": "artifact",
                                                "artifact": artifact, "revision": 1, "seq": outgoing["seq"], "agent_id": agent_id}
        elif kind in {"action.proposed", "action.finished"}:
            action = payload["action"]
            blocks[action["action_id"]] = {"id": action["action_id"], "kind": "action", "action": action, "revision": 1, "seq": outgoing["seq"]}
        if kind.startswith(("tool.", "agent.", "skill.", "activity.")) and not str(payload.get("activity_id", "")).endswith("_model"):
            thinking.append({"stage": kind, "message": payload.get("summary") or payload.get("title") or payload.get("reason") or "",
                "timestamp": datetime.now(timezone.utc).isoformat(), "eventType": "trace", "runId": run_id, "sessionId": thread_id,
                "result": {**payload, "runtime_type": kind, "seq": outgoing["seq"], "agent_id": agent_id,
                           "run_id": run_id, "session_id": thread_id}})
        await queue.put(outgoing)
        if checkpoint is not None and (kind in {"content.delta", "reasoning.delta", "reasoning.completed", "tool.result", "tool.failed", "agent.finished"}) and time.monotonic() - last_checkpoint >= 1:
            last_checkpoint = time.monotonic()
            try:
                result = checkpoint({"attempt_id": attempt_id, "stream_epoch": attempt_id, "committed_seq": outgoing["seq"],
                                     "blocks": message_blocks(list(blocks.values())), "thinking": message_activities(thinking),
                                     "response": runtime.root_content if runtime else "",
                                     "artifacts": deepcopy(runtime.data.artifacts) if runtime else []})
                if inspect.isawaitable(result):
                    await result
            except Exception:
                await emit("delivery.persistence_unconfirmed", {"message": "生成内容暂未保存，正在保留当前页面结果。"})

    async def producer():
        nonlocal runtime
        with run_context_scope(run_context):
            runtime = AgentRuntime(context=run_context, session_id=thread_id, query=query,
                model=ModelTransport(resolve_model()), emit=emit,
                history=(ui_context or {}).get("session_history", []),
                ui_context={**(ui_context or {}), "strict_selection": bool(strict_selection)})
            parent_run = (ui_context or {}).get("resume_from_run_id")
            if not parent_run and deps.persist_run_event is not None:
                try:
                    from backend.services.research_run_store import get_research_run_store
                    store = get_research_run_store()
                    parent_run = await asyncio.wait_for(asyncio.to_thread(store.previous_run_id,
                        thread_id, run_id, user_id=run_context.owner), timeout=run_context.timeout(5))
                except Exception as exc:
                    logger.warning("旧资料索引暂不可用 run_id=%s error_type=%s", run_id, type(exc).__name__)
            if parent_run:
                restored = await asyncio.wait_for(asyncio.to_thread(runtime.data.restore, parent_run), timeout=run_context.timeout(5))
                if not restored:
                    await emit("activity.updated", {"title": "此前原始资料已过期或不可用，将按当前问题重新取证。"})
                else:
                    await emit("activity.updated", {"activity_id": "conversation_evidence", "title": "已沿用本会话仍有效的资料",
                        "summary": "保留原始来源与时间；涉及最新行情时仍会重新取数。", "data_refs": list(runtime.data.records)})
                    try:
                        await asyncio.to_thread(runtime.data.save)
                    except OSError:
                        logger.warning("沿用资料未写入新运行缓存 run_id=%s", run_id)
            if output_mode == "investment_report":
                runtime.report_title = query[:100]
            from .fact_answer import can_compose_causal
            runtime.answer_feedback = lambda text: answer_feedback(text, runtime.data,
                require_citations=bool(runtime.report_title), short_cause=can_compose_causal(runtime))
            _ACTIVE[(run_context.owner, run_id)] = runtime
            report = None
            try:
                async with runtime.limiter.slot("research", run_context.owner,
                        max(1, int(os.getenv("FINSIGHT_AGENT_MAX_ACTIVE_RUNS", "2"))),
                        owner_max=1, timeout=1, ttl=run_context.remaining_seconds + 30):
                    await emit("run.accepted", {"status": "running", "model": runtime.model.config.model})
                    fallback_answer_id = None
                    fact_fallback_used = False
                    try:
                        async with asyncio.timeout(run_context.remaining_seconds):
                            final = await runtime.run_agent("root", "research_lead", query)
                    except (ModelProtocolError, TimeoutError, CapacityExceeded) as exc:
                        factual = checked_factual_answer(runtime)
                        if not factual and "price_cause" in runtime.completeness.facets and runtime.answer_repair_candidate:
                            from .fact_answer import causal_fact_delivery
                            candidate = causal_fact_delivery(runtime, runtime.answer_repair_candidate[1])
                            factual = candidate if candidate and not verified_text(candidate, runtime.data)[1] else ""
                        if factual:
                            fact_fallback_used = True
                            fallback_answer_id, final = "root_fact_answer", factual
                            await emit("content.delta", {"block_id": fallback_answer_id, "delta": factual})
                            await emit("content.block_finished", {"block_id": fallback_answer_id, "content_phase": "answer"})
                        else:
                            if runtime.answer_repair_candidate is None:
                                raise
                            fallback_answer_id, final = runtime.answer_repair_candidate
                            await emit("activity.finished", {"activity_id": "answer_check", "status": "failed",
                                "title": "回答核对未完成", "summary": "保留已核实的结果，其余部分暂时无法确认。",
                                "error_code": exception_code(exc)})
                    await runtime.close(notify=True)
                    if not final.strip() and runtime.answer_repair_candidate is not None:
                        fallback_answer_id, final = runtime.answer_repair_candidate
                    if not final.strip():
                        raise ModelProtocolError("model_empty_response")
                    reasons = []
                    text_blocks = [block for block in blocks.values() if block.get("kind") == "text"
                                   and block.get("agent_id") == "root"]
                    answer_block = (blocks.get(fallback_answer_id) if fallback_answer_id else
                                    text_blocks[-1] if text_blocks else None)
                    prefer_financial_facts = bool(runtime.completeness.facets) and set(runtime.completeness.facets) <= {"filings", "cash_flow"}
                    prefer_calculation_facts = "chart" in runtime.completeness.facets and bool(re.search(r"连续(?:至少|不少于)?\s*\d+\s*(?:周|天).*下跌", query))
                    prefer_causal_facts = "price_cause" in runtime.completeness.facets
                    if answer_block is not None and (prefer_financial_facts or prefer_calculation_facts or prefer_causal_facts or verified_text(answer_block["content"], runtime.data)[1]):
                        factual = checked_factual_answer(runtime)
                        if not factual and "price_cause" in runtime.completeness.facets:
                            from .fact_answer import causal_fact_delivery
                            candidate = causal_fact_delivery(runtime, answer_block["content"])
                            factual = candidate if candidate and not verified_text(candidate, runtime.data)[1] else ""
                        if factual:
                            fact_fallback_used = True
                            answer_block["content"] = final = factual
                            answer_block["revision"] += 1
                            await emit("content.revised", {"block_id": answer_block["id"], "content": factual,
                                "revision": answer_block["revision"], "content_phase": "answer", "reason": "verified_fact_delivery"})
                    response = ""
                    for block in list(blocks.values()):
                        if block.get("kind") != "text":
                            continue
                        is_answer = block is answer_block
                        block["content_phase"] = "answer" if is_answer else "progress"
                        revised, violations = verified_text(block["content"], runtime.data,
                            require_citations=bool(runtime.report_title) and is_answer)
                        if fallback_answer_id and block is not answer_block and block.get("seq", 0) > answer_block.get("seq", 0):
                            # 失败校正轮的半截输出不是可交付答案，不能混进正文。
                            revised = ""
                        block["validation_issues"] = violations
                        if is_answer:
                            if violations:
                                revised = (revised + "\n\n" if revised else "") + "部分结论还缺少可靠依据，暂时无法确认。"
                                validation_messages = {
                                    "explanation_delivery_delay_unverified": "行情来源未提供可核实的延迟说明。",
                                    "explanation_realtime_unverified": "现有行情没有注明为实时报价。",
                                    "explanation_adjustment_unverified": "行情来源未说明相关复权或股息处理口径。",
                                    "explanation_exchange_unverified": "本轮资料不足以确认所述交易场所。",
                                    "unverified_citation": "部分引用未能对应已取得的来源。",
                                }
                                reasons.extend({"code": code, "severity": "block",
                                    "message": validation_messages.get(code, "部分结论缺少可核实的数据依据。")} for code in violations)
                            response = revised
                        if revised != block["content"]:
                            block["content"] = revised
                            block["revision"] += 1
                            await emit("content.revised", {"block_id": block["id"], "content": block["content"],
                                "revision": block["revision"], "content_phase": block["content_phase"],
                                "reason": "unbound_factual_quantity" if violations else "public_content_normalized"})
                    if answer_block is None:
                        raise ModelProtocolError("model_empty_response")
                    runtime.root_content = response
                    if runtime.answer_repair_attempted and fallback_answer_id is None:
                        await emit("activity.finished", {"activity_id": "answer_check", "status": "completed",
                            "title": "回答核对完成", "summary": "已保留与资料一致的结果。"})
                    tickers = list(dict.fromkeys(str(record["inputs"]["ticker"]).upper() for record in runtime.data.records.values()
                        if record.get("inputs", {}).get("ticker")))
                    price_levels = price_levels_from_blocks([answer_block], tickers)
                    referenced_ids = set(cited_sources(response, runtime.data))
                    for artifact in runtime.data.artifacts:
                        referenced_ids.update(artifact.get("source_refs") or [])
                    for sid in list(referenced_ids):
                        ref = runtime.data.sources.get(sid, {}).get("data_ref")
                        if ref:
                            referenced_ids.update(runtime.data.source_refs(ref))
                    referenced_sources = [source for sid, source in runtime.data.sources.items() if sid in referenced_ids]
                    if any(coverage.get("missing", 0) > 0 for artifact in runtime.data.artifacts
                           for coverage in (artifact.get("coverage") or {}).values()):
                        reasons.append({"code": "partial_chart_data", "severity": "warn",
                                        "message": "图中部分数值缺失，曲线没有覆盖完整区间。"})
                    if runtime.executor.unresolved_failures:
                        usable = any(r.get("status") == "success" and r.get("tool") != "get_current_datetime"
                                     and runtime.data.source_refs(ref) for ref, r in runtime.data.records.items())
                        # 尝试过的辅助计算不是交付需求；失败已在过程记录，不把成功的替代路径标成缺资料。
                        # 没有任何可核验来源则仍明确阻止无证据交付。
                        if not usable:
                            reasons.append({"code": "no_verified_evidence", "severity": "block",
                                            "message": "本轮没有取得可核验的研究数据。"})
                        elif re.search(r"\[数据缺失\]|(?:未能|尚未|没有|无法|未)(?:取得|获取|完成)|取不到|(?:资料|数据|计算|统计|新闻|财报)[^\n。]{0,16}(?:缺失|不足|未完成|不可用)",
                                       re.sub(r"未完成(?:周期|周|月|交易日)", "尚未收盘的周期", response)):
                            reasons.append({"code": "partial_tool_failure", "severity": "warn",
                                            "message": "回答中仍有未能取得的资料或未完成的计算。"})
                    research_gaps = runtime.completeness.missing(runtime.data, runtime.executor.attempts)
                    if research_gaps:
                        missing = "、".join(dict.fromkeys((gap["ticker"] + " " + gap["label"]).strip() for gap in research_gaps))
                        reasons.append({"code": "research_incomplete", "severity": "block",
                            "message": "尚未核实：" + missing + "。", "missing_evidence": research_gaps})
                        response += "\n\n尚未核实：" + missing + "。现有资料不足以完成这部分判断。"
                        answer_block["content"] = runtime.root_content = response
                        answer_block["revision"] += 1
                        await emit("content.revised", {"block_id": answer_block["id"], "content": response,
                            "revision": answer_block["revision"], "content_phase": "answer", "reason": "research_incomplete"})
                    hard_block = any(reason.get("severity") == "block" for reason in reasons)
                    quality = {"state": "block" if hard_block else ("warn" if reasons else "pass"), "reasons": reasons,
                               "source_count": len(runtime.data.sources), "evidence_ledger": list(runtime.data.sources.values())}
                    report = build_report(runtime, response) if runtime.report_title else None
                    report_quality = (report or {}).get("report_quality") or (report or {}).get("meta", {}).get("report_quality") or quality
                    blocked = (hard_block or report_quality.get("state") in {"block", "blocked"}
                               or report_quality.get("publishable") is False)
                    state = {"query": query, "thread_id": thread_id,
                             "subject": {"tickers": (ui_context or {}).get("tickers_override", [])},
                             "artifacts": {"draft_markdown": response, "evidence_pool": list(runtime.data.sources.values()),
                                           "step_results": runtime.data.results, "artifacts": runtime.data.artifacts}}
                    if report is not None and not blocked:
                        result = deps.schedule_report_index(session_id=thread_id, report=report, state=state)
                        if inspect.isawaitable(result):
                            result = await result
                        if result is False:
                            raise ModelProtocolError("report_persistence_failed")
                    deps.update_session_context(thread_id=thread_id, original_query=query,
                                                response_markdown=response, subject=state["subject"], skip_context=False)
                    event = {"type": "done", "schema_version": "2", "run_id": run_id, "session_id": thread_id,
                             "message_id": message_id or "assistant:" + run_id, "attempt_id": attempt_id, "stream_epoch": attempt_id,
                             "response": response, "success": True, "run_status": "completed",
                             "answer_status": "partial" if blocked or reasons else "answered", "quality": quality,
                             "report_quality": report_quality, "publishable": not blocked,
                             "report": report if not blocked else None, "blocked_report": report if blocked else None,
                             "quality_blocked": blocked, "blocks": message_blocks(list(blocks.values())),
                             "thinking": message_activities(thinking), "price_levels": price_levels,
                             "evidence_pool": referenced_sources,
                             "current_focus": runtime.observed_tickers[-1] if runtime.observed_tickers else (ui_context or {}).get("active_symbol"),
                             "tickers": runtime.observed_tickers or tickers,
                             "artifacts": runtime.data.artifacts, "actions": list(runtime.actions.values()),
                             "metrics": {**run_context.usage.summary(), "tool_calls": runtime.tool_count,
                                         "research_recovery_rounds": runtime.research_recovery_rounds,
                                         "fact_fallback_used": fact_fallback_used,
                                         "answer_repair_attempted": runtime.answer_repair_attempted}}
                    if deps.persist_run_event is not None:
                        event = await deps.persist_run_event(event)
                    else:
                        event["persistence_status"] = "ephemeral"
                    run_context.finish(event.get("run_status", "completed"))
                    await queue.put(event)
            except asyncio.CancelledError:
                run_context.finish("cancelled")
                event = {"type": "cancelled", "run_id": run_id, "session_id": thread_id,
                         "response": runtime.root_content, "message": "已停止，保留已生成内容。",
                         "publishable": False, "blocks": message_blocks(list(blocks.values())), "thinking": message_activities(thinking),
                         "evidence_pool": list(runtime.data.sources.values()), "artifacts": runtime.data.artifacts}
                if deps.persist_run_event:
                    event = await asyncio.shield(deps.persist_run_event(event))
                await queue.put(event)
            except Exception as exc:
                code = exception_code(exc)
                persistence_failure = code == "report_persistence_failed"
                logger.error("研究中断 run_id=%s code=%s stage=%s exception_type=%s frames=%s", run_id, code,
                    runtime.stages.get("root", "initialization"), type(exc).__name__,
                    [(frame.name, frame.lineno) for frame in traceback.extract_tb(exc.__traceback__)[-8:]])
                run_context.finish("persistence_failed" if persistence_failure else "failed")
                info = error_info(code)
                event = {"type": "error", "run_id": run_id, "session_id": thread_id,
                         "message": info["reason"], **info,
                         "response": runtime.root_content, "publishable": False,
                         "run_status": run_context.status,
                         "failure_kind": "persistence_error" if persistence_failure else "execution_error",
                         "blocked_report": report if persistence_failure else None,
                         "answer_status": "partial" if runtime.root_content else "unavailable",
                         "blocks": message_blocks(list(blocks.values())), "thinking": message_activities(thinking),
                         "evidence_pool": list(runtime.data.sources.values()), "artifacts": runtime.data.artifacts,
                         "metrics": {**run_context.usage.summary(), "tool_calls": runtime.tool_count,
                                     "failed_stage": runtime.stages.get("root", "initialization")}}
                if deps.persist_run_event:
                    event = await deps.persist_run_event(event)
                await queue.put(event)
            finally:
                for action_id, action in runtime.actions.items():
                    _ACTIONS[(run_context.owner, run_id, action_id)] = action
                while len(_ACTIONS) > 256:
                    _ACTIONS.popitem(last=False)
                _ACTIVE.pop((run_context.owner, run_id), None)
                await runtime.close()
                await run_context.archive_usage()
                await queue.put(sentinel)

    async def guarded_producer():
        try:
            await producer()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # 初始化/资料恢复也可能失败；必须给订阅者终态，不能留下无限心跳。
            run_context.finish("failed")
            info = error_info(exception_code(exc))
            event = {"type": "error", "run_id": run_id, "session_id": thread_id,
                     "message": info["reason"], **info,
                     "publishable": False, "run_status": "failed"}
            if deps.persist_run_event is not None:
                event = await deps.persist_run_event(event)
            await queue.put(event)
            await queue.put(sentinel)

    task = asyncio.create_task(guarded_producer())
    try:
        while True:
            try:
                event = await asyncio.wait_for(queue.get(), timeout=3)
            except TimeoutError:
                # 订阅层负责无序号心跳；不要在规范事件流中插入另一个seq来源。
                continue
            if event is sentinel:
                break
            yield event
    finally:
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)


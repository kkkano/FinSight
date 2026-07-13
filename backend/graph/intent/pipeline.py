# -*- coding: utf-8 -*-
"""意图管线（WP2 Task 3 / D2）——LLM 唯一决策者 + 规则兜底。

顺序固定：
1. extract_signals 提取客观信号
2. 硬前置（不经 LLM 的三类合理短路）：空 query / 纯社交
3. route_conversation（LLM router）——唯一路由决策者
4. direct/out_of_scope：复核只能「保持」或「降级 clarify」，绝不伪造 research（改 ORC-02）
5. clarify：直接产出澄清
6. research + task_hints：hints 投影为任务（LLM 权威）
7. 其余一切（router 不可用 / research 无 hints）→ fallback：整体委托给
   _legacy_understand_request（关键词瀑布零复制，行为与金样逐字节一致；
   物理拆分按计划归 WP3）。

返回 (IntentFrame, legacy 同构 result dict)。任何未预期异常由调用方（understand_request
分发壳）兜底回 legacy——新管线永远不能比旧路径更脆。
"""
from __future__ import annotations

import logging
import re
from typing import Any

from backend.graph.intent.frame import IntentFrame, intent_frame_from_legacy
from backend.graph.intent.priorities import CONFIDENCE_NO_TASKS, CONFIDENCE_WITH_TASKS
from backend.graph.intent.signals import extract_signals
from backend.graph.intent.router import route_conversation
from backend.graph.state import GraphState

logger = logging.getLogger(__name__)


def _ur():
    """延迟导入 understand_request 模块。

    必须走 importlib：backend.graph.nodes 包的 __init__ 把 `understand_request`
    属性绑定为同名函数，`import a.b.c as m` 的属性查找会拿到函数而非模块。
    """
    import importlib

    return importlib.import_module("backend.graph.nodes.understand_request")


async def _fallback_to_legacy(state: GraphState, *, reason: str, source: str = "rules_fallback") -> tuple[IntentFrame, dict]:
    """规则兜底：整体委托 legacy 主函数，行为与旧路径逐字节一致。"""
    ur = _ur()
    result = await ur._legacy_understand_request(state)
    understanding = result.get("understanding") if isinstance(result.get("understanding"), dict) else {}
    frame = intent_frame_from_legacy(understanding)
    frame.source = source
    trace = result.get("trace")
    if isinstance(trace, dict):
        trace["intent_pipeline"] = {"lane": "fallback", "reason": reason}
    return frame, result


def review_direct_decision(query: str, decision: Any, *, current_tickers: list[str], request_frame: dict | None) -> str:
    """direct 决策复核（D2）：只能 'keep' 或 'clarify'，不得伪造 research。

    判定条件复用原 _direct_decision_must_project_tasks（该函数原本会把 direct
    强改为 research——ORC-02 的病灶之一；新语义收窄为降级澄清让用户拍板）。
    """
    ur = _ur()
    must_project = ur._direct_decision_must_project_tasks(
        query, decision, current_tickers=current_tickers, request_frame=request_frame or {}
    )
    return "clarify" if must_project else "keep"


def _clarify_result(
    state: GraphState,
    *,
    query: str,
    output_mode: str,
    decision: Any,
    trace: dict[str, Any],
    artifacts: dict[str, Any],
) -> tuple[IntentFrame, dict]:
    """由 router 的 clarify/降级决策构造澄清结果（组装规则照抄 legacy 3227-3402 对应段）。"""
    ur = _ur()
    blocked_tasks = [ur._context_router_clarify_block(decision)]
    ur._sanitize_blocked_task_questions(query, blocked_tasks)

    first_blocked = blocked_tasks[0]
    suggestions = list(first_blocked.get("suggestions") or [])[:2]
    question = str(first_blocked.get("question") or "请补充分析对象。")
    if suggestions:
        artifacts["draft_markdown"] = "\n".join([question, "", "可以补充：", *[f"- {s}" for s in suggestions]]).strip()
    else:
        artifacts["draft_markdown"] = question

    operation = ur._operation("qa", 0.0)
    subject = ur._build_subject(None, [], [])
    facets = ur.derive_request_facets(query=query, operation=operation, subject=subject)
    understanding = {
        "route": "clarify",
        "original_query": query,
        "cleaned_query": query,
        "language": "zh" if re.search(r"[一-鿿]", query) else "en",
        "social_prefix": "",
        "user_visible_summary": f"阻塞项:{len(blocked_tasks)}",
        "confidence": CONFIDENCE_NO_TASKS,
        "tasks": [],
        "blocked_tasks": blocked_tasks,
        "context_refs": [],
        "fallback_assumptions": [],
        "facets": facets,
    }
    trace["understanding"] = understanding
    result = {
        "understanding": understanding,
        "reply_contract": {},
        "tasks": [],
        "blocked_tasks": blocked_tasks,
        "context_refs": [],
        "subject": subject,
        "operation": operation,
        "facets": facets,
        "output_mode": output_mode,
        "clarify": {
            "needed": True,
            "reason": str(first_blocked.get("reason") or ""),
            "question": question,
            "suggestions": list(first_blocked.get("suggestions") or []),
        },
        "chat_responded": False,
        "pending_research_after_alert": False,
        "artifacts": artifacts,
        "trace": trace,
    }
    frame = intent_frame_from_legacy(understanding)
    frame.source = "llm_router"
    return frame, result


async def build_intent_result(state: GraphState) -> tuple[IntentFrame, dict]:
    ur = _ur()
    query = (state.get("query") or "").strip()
    ui_context = dict(state.get("ui_context") or {}) if isinstance(state.get("ui_context"), dict) else {}
    output_mode = ur.decide_output_mode(state).get("output_mode") or "chat"
    memory_context = state.get("memory_context") if isinstance(state.get("memory_context"), dict) else {}
    artifacts = dict(state.get("artifacts") or {})
    trace = dict(state.get("trace") or {})
    selection_ids, selection_types, _payload = ur._normalize_selection(ui_context)

    # ── 硬前置 ──
    if not query:
        return await _fallback_to_legacy(state, reason="empty_query")

    signals = extract_signals(query, ui_context=ui_context)

    if signals.is_casual:
        decision = ur.ConversationDecision(
            execution_route="direct_answer",
            context_binding=ur.ContextBinding(),
            relation="new_topic",
            domain_intent="smalltalk",
            confidence=1.0,
            needs_tools=False,
            reason="纯社交问候，直接回答",
        )
        result = ur._direct_conversation_result(
            query=query,
            output_mode=output_mode,
            decision=decision,
            reply=ur._direct_reply(query),
            context_refs=[],
            artifacts=artifacts,
            trace=trace,
            memory_context=memory_context,
            request_frame={},
        )
        frame = intent_frame_from_legacy(result.get("understanding") or {})
        frame.route, frame.source = "direct", "rules_fallback"
        return frame, result

    # ── LLM 路由（唯一决策者）──
    forced_agents = ui_context.get("agents_override")
    has_forced = isinstance(forced_agents, list) and any(isinstance(a, str) and a.strip() for a in forced_agents)

    try:
        decision = await route_conversation(state, tickers=signals.tickers, selection_ids=selection_ids)
    except Exception:
        logger.warning("[intent-pipeline] route_conversation raised; falling back to rules", exc_info=True)
        decision = None
    if decision is None:
        return await _fallback_to_legacy(state, reason="router_unavailable")
    if getattr(decision, "decision_source", "llm") == "heuristic_fallback":
        # fail-open 启发式决策没有 LLM 权威（D2）：视同 router 不可用，交回规则兜底，
        # 避免投资类 query 被低置信 direct 短路（legacy 靠 must_project 兜底的场景）。
        return await _fallback_to_legacy(state, reason="router_heuristic_only")

    trace["conversation_router"] = decision.model_dump()
    trace["intent_pipeline"] = {"lane": "llm"}

    route = str(decision.execution_route or "").strip().lower()

    if route in {"direct_answer", "out_of_scope"} and not has_forced:
        verdict = review_direct_decision(query, decision, current_tickers=signals.tickers, request_frame={})
        if verdict == "clarify":
            trace["intent_pipeline"]["direct_review"] = "downgraded_to_clarify"
            return _clarify_result(state, query=query, output_mode=output_mode, decision=decision, trace=trace, artifacts=artifacts)
        reply = await ur.generate_contextual_reply(state, decision)
        direct_refs: list[dict[str, Any]] = []
        binding = decision.context_binding
        if binding.source != "none":
            direct_refs.append({
                "source": "conversation_context",
                "key": binding.source,
                "label": binding.subject_hint or binding.source,
                "value": binding.reason,
            })
        result = ur._direct_conversation_result(
            query=query,
            output_mode=output_mode,
            decision=decision,
            reply=reply,
            context_refs=direct_refs,
            artifacts=artifacts,
            trace=trace,
            memory_context=memory_context,
            request_frame={},
        )
        frame = intent_frame_from_legacy(result.get("understanding") or {})
        frame.route, frame.source = "direct", "llm_router"
        return frame, result

    if route == "clarify" and not has_forced:
        return _clarify_result(state, query=query, output_mode=output_mode, decision=decision, trace=trace, artifacts=artifacts)

    # ── research：hints 投影（LLM 权威）──
    tasks: list[dict[str, Any]] = []
    context_refs: list[dict[str, Any]] = []
    intent_contracts: list[dict[str, Any]] = []
    request_frames: list[dict[str, Any]] = []
    if getattr(decision, "task_hints", ()):
        contract_enforced = ur.intent_contract_mode() == "enforce"
        if contract_enforced:
            ur._add_router_task_hints_contract(
                tasks=tasks, context_refs=context_refs, decision=decision, query=query,
                output_mode=output_mode, current_tickers=signals.tickers,
                selection_ids=selection_ids, selection_types=selection_types,
                intent_contracts=intent_contracts, request_frames=request_frames,
                project_residual_hints=True,
            )
        else:
            ur._add_router_task_hints(
                tasks=tasks, context_refs=context_refs, decision=decision, query=query,
                current_tickers=signals.tickers, output_mode=output_mode,
                selection_ids=selection_ids, selection_types=selection_types,
            )
    if not tasks:
        return await _fallback_to_legacy(state, reason="research_without_hints", source="mixed")

    reply_contract = ur.build_reply_contract(
        query=query, output_mode=output_mode, tasks=tasks, blocked_tasks=[],
        conversation_decision=decision, memory_context=memory_context,
    )
    ur._apply_reply_contract_to_tasks(tasks, reply_contract)
    reply_contract = ur.build_reply_contract(
        query=query, output_mode=output_mode, tasks=tasks, blocked_tasks=[],
        conversation_decision=decision, memory_context=memory_context,
    )

    has_alert_task = any((t.get("operation") or {}).get("name") == "alert_set" for t in tasks)
    pending_research_after_alert = has_alert_task and any(
        (t.get("operation") or {}).get("name") != "alert_set" for t in tasks
    )
    final_route = "alert" if has_alert_task else "research"

    primary = tasks[0]
    operation = (primary or {}).get("operation") or ur._operation("qa", 0.0)
    subject = ur._build_subject(primary, [], tasks)
    facets = ur.derive_request_facets(query=query, operation=operation, subject=subject)

    summary_bits: list[str] = []
    for task in tasks[:5]:
        op_name = (task.get("operation") or {}).get("name")
        subject_label = task.get("subject_label") or ",".join(task.get("tickers") or []) or task.get("subject_type")
        summary_bits.append(f"{subject_label}:{op_name}")
    understanding = {
        "route": final_route,
        "original_query": query,
        "cleaned_query": query,
        "language": "zh" if re.search(r"[一-鿿]", query) else "en",
        "social_prefix": ur._social_prefix(query),
        "user_visible_summary": "；".join(summary_bits) if summary_bits else "需要补充信息。",
        "confidence": CONFIDENCE_WITH_TASKS,
        "tasks": tasks,
        "blocked_tasks": [],
        "context_refs": context_refs,
        "fallback_assumptions": [],
        "facets": facets,
    }
    trace["understanding"] = understanding
    trace["reply_contract"] = reply_contract
    if intent_contracts:
        trace["intent_contract"] = intent_contracts[0]
        trace["intent_contracts"] = intent_contracts

    result = {
        "understanding": understanding,
        "reply_contract": reply_contract,
        "tasks": tasks,
        "blocked_tasks": [],
        "context_refs": context_refs,
        "subject": subject,
        "operation": operation,
        "facets": facets,
        "output_mode": output_mode,
        "clarify": {"needed": False, "reason": "", "question": "", "suggestions": []},
        "chat_responded": False,
        "pending_research_after_alert": pending_research_after_alert,
        "artifacts": artifacts,
        "trace": trace,
    }
    if intent_contracts:
        result["intent_contract"] = intent_contracts[0]
        result["intent_contracts"] = intent_contracts
        understanding["intent_contract"] = intent_contracts[0]
    if request_frames:
        result["request_frame"] = request_frames[0]
        result["request_frames"] = request_frames
    frame = intent_frame_from_legacy(understanding)
    frame.source = "llm_router"
    understanding["intent_frame"] = frame.model_dump()
    return frame, result


async def build_intent_frame(state: GraphState) -> IntentFrame:
    """测试友好入口：只要 frame。"""
    frame, _result = await build_intent_result(state)
    return frame


__all__ = ["build_intent_frame", "build_intent_result", "review_direct_decision"]

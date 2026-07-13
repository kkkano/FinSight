# -*- coding: utf-8 -*-
# 机械拆分自 backend/graph/nodes/understand_request.py（WP3 Task3，零行为变更）。
"""请求理解节点：一次性完成闲聊、标的、任务和阻塞项识别。"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import replace
from typing import Any

from langchain_core.messages import AIMessage

from backend.config.ticker_mapping import CN_TO_TICKER, COMPANY_MAP, dedup_tickers, extract_tickers, normalize_ticker
from backend.graph.earnings_intent import (
    query_requests_earnings_performance,
    query_requests_earnings_price_impact,
)
from backend.graph.event_bus import emit_event
from backend.graph.intent_contract import (
    derive_intent_contract,
    evidence_focused_operation,
    intent_contract_mode,
    legacy_operation_for_contract,
    requires_per_ticker_research,
    synthesis_compare_operation,
)
from backend.graph.investment_intent import (
    query_requests_comparative_investment_opinion,
    query_requests_investment_opinion,
)
from backend.graph.intent.router import (
    ContextBinding,
    ConversationDecision,
    _effective_current_turn_tickers,
    _task_hints_require_execution,
    generate_contextual_reply,
    route_conversation,
)
from backend.graph.nodes.decide_output_mode import decide_output_mode
from backend.graph.nodes.parse_operation import parse_operation
from backend.graph.nodes.query_intent import has_financial_intent, is_casual_chat, is_greeting
from backend.graph.memory_scope import current_report_context, current_thread_focus
from backend.graph.request_facets import derive_request_facets
from backend.graph.request_frame import compile_request_frame, compile_request_frames
from backend.graph.understanding_v2 import (
    build_understanding_v2,
    chat_multi_ticker_research_limit,
    has_comparison_relation,
    infer_facets,
    relation_operation_params,
    support_operations_for_relation,
)
from backend.graph.request_task_contract import (
    build_reply_contract,
    query_explicitly_requests_links,
    query_explicitly_requests_sources,
    reply_contract_disallows_news,
    wants_no_news_or_links,
)
from backend.graph.state import GraphState
from backend.graph.intent.operations import _operation
from backend.graph.intent.predicates import _build_subject

logger = logging.getLogger(__name__)


from backend.graph.intent.keywords import (  # noqa: F401 —— 关键词单一来源（WP2-T2）
    _ALERT_HINTS,
    _ASSET_DEICTIC_HINTS,
    _COMPARE_HINTS,
    _FALLBACK_HINTS,
    _FORBIDDEN_DIRECT_REPLY_MARKERS,
    _GLOBAL_CHAT_VIEWS,
    _HOLDINGS_HINTS,
    _IMPACT_HINTS,
    _INDEX_TICKERS,
    _LIGHTWEIGHT_COMPARE_HINTS,
    _MACRO_HINTS,
    _NEWS_HINTS,
    _NON_ASSET_TOKENS,
    _PORTFOLIO_HINTS,
    _PRICE_HINTS,
    _PRIVATE_INSIDER_INFO_HINTS,
    _PUBLIC_INSIDER_DISCLOSURE_HINTS,
    _REPORT_PEER_CONTEXT_HINTS,
    _RESEARCH_CONFIRMATION_ACTION_TERMS,
    _RESEARCH_CONFIRMATION_ASK_TERMS,
    _ROUTER_GENERIC_COMPANY_OPERATIONS,
    _ROUTER_SPECIFIC_COMPANY_OPERATIONS,
    _SOCIAL_PREFIX_RE,
    _TECHNICAL_HINTS,
    _THEME_HINTS,
    _URL_RE,
    _VAGUE_SUBJECT_HINTS,
    _VALUATION_CONCEPT_HINTS,
    _VALUATION_JUDGMENT_HINTS,
)




def _sanitize_direct_chat_reply(reply: str) -> str:
    """Keep direct LLM answers inside the same user-facing chat contract as rendered answers."""
    cleaned = str(reply or "").strip()
    cleaned = re.sub(r"我理解你的问题是[:：]\s*", "", cleaned)
    cleaned = cleaned.replace("问题：", "关键点：")
    cleaned = cleaned.replace("后续关注：", "后续观察：")
    for marker in _FORBIDDEN_DIRECT_REPLY_MARKERS:
        cleaned = cleaned.replace(marker, "")
    paragraphs = re.split(r"\n\s*\n", cleaned)
    kept: list[str] = []
    for paragraph in paragraphs:
        compact = re.sub(r"\s+", " ", paragraph).strip()
        lowered = compact.lower()
        asks_to_confirm_research = any(term in compact or term in lowered for term in _RESEARCH_CONFIRMATION_ASK_TERMS)
        mentions_research_action = any(term in compact or term in lowered for term in _RESEARCH_CONFIRMATION_ACTION_TERMS)
        if asks_to_confirm_research and mentions_research_action:
            continue
        kept.append(paragraph.strip())
    if kept:
        cleaned = "\n\n".join(part for part in kept if part)
    elif cleaned:
        cleaned = "这个问题需要实时数据才能可靠回答，当前直接答复缺少足够证据。"
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()

def _ensure_direct_reply_names_bound_tickers(reply: str, *, decision: ConversationDecision, query: str) -> str:
    explicit_tickers = dedup_tickers(extract_tickers(query).get("tickers") or [])
    if decision.relation != "compare" and len(explicit_tickers) < 2:
        return reply
    subject_hint = str(decision.context_binding.subject_hint or "")
    tickers = dedup_tickers(extract_tickers(subject_hint).get("tickers") or [])
    if len(tickers) < 2:
        return reply
    upper_reply = reply.upper()
    if all(ticker.upper() in upper_reply for ticker in tickers):
        return reply
    ticker_label = ", ".join(tickers[:6])
    if re.search(r"[\u4e00-\u9fff]", query):
        prefix = f"按 {ticker_label} 作为代表来看："
    else:
        prefix = f"Using {ticker_label} as the representative set:"
    if reply.startswith(prefix):
        return reply
    return f"{prefix}\n\n{reply}".strip()


def _direct_reply_subject(
    *,
    query: str,
    decision: ConversationDecision,
    memory_context: dict[str, Any] | None,
) -> dict[str, Any]:
    """为直接追问保留已验证焦点，不从回答正文扩散大写缩写。"""
    tickers = dedup_tickers(extract_tickers(query).get("tickers") or [])
    if not tickers and decision.relation != "new_topic":
        thread_focus = current_thread_focus(memory_context or {})
        focus_ticker = str((thread_focus or {}).get("ticker") or "").strip().upper()
        if focus_ticker:
            tickers = [focus_ticker]
    if not tickers and decision.context_binding.source != "none":
        bound = dedup_tickers(extract_tickers(str(decision.context_binding.subject_hint or "")).get("tickers") or [])
        tickers = bound if decision.relation == "compare" else bound[:1]
    if not tickers:
        return _build_subject(None, [])
    return _build_subject(
        {
            "subject_type": "company",
            "tickers": tickers,
            "selection_ids": [],
            "selection_types": [],
            "operation": {"name": "compare" if decision.relation == "compare" else "qa"},
        },
        [],
    )

def _direct_conversation_result(
    *,
    query: str,
    output_mode: str,
    decision: ConversationDecision,
    reply: str,
    context_refs: list[dict[str, Any]],
    artifacts: dict[str, Any],
    trace: dict[str, Any],
    memory_context: dict[str, Any] | None = None,
    request_frame: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reply = _sanitize_direct_chat_reply(reply)
    reply = _ensure_direct_reply_names_bound_tickers(reply, decision=decision, query=query)
    artifacts["draft_markdown"] = reply
    artifacts["conversation_decision"] = decision.model_dump()
    understanding = {
        "route": "direct",
        "original_query": query,
        "cleaned_query": query,
        "language": "zh" if re.search(r"[\u4e00-\u9fff]", query) else "en",
        "social_prefix": "",
        "user_visible_summary": decision.reason or "直接回答",
        "confidence": decision.confidence,
        "tasks": [],
        "blocked_tasks": [],
        "context_refs": context_refs,
        "fallback_assumptions": [],
    }
    reply_contract = build_reply_contract(
        query=query,
        output_mode=output_mode,
        tasks=[],
        blocked_tasks=[],
        conversation_decision=decision,
        memory_context=memory_context,
    )
    trace["understanding"] = understanding
    trace["conversation_router"] = decision.model_dump()
    trace["reply_contract"] = reply_contract
    subject = _direct_reply_subject(
        query=query,
        decision=decision,
        memory_context=memory_context,
    )
    operation = _operation("chat", decision.confidence)
    facets = derive_request_facets(query=query, operation=operation, subject=subject)
    understanding["facets"] = facets
    if request_frame:
        understanding["request_frame"] = request_frame
        understanding["request_frames"] = [request_frame]
        trace["request_frame"] = request_frame
        trace["request_frames"] = [request_frame]
    result: dict[str, Any] = {
        "understanding": understanding,
        "reply_contract": reply_contract,
        "tasks": [],
        "blocked_tasks": [],
        "context_refs": context_refs,
        "subject": subject,
        "operation": operation,
        "output_mode": output_mode,
        "clarify": {"needed": False, "reason": "", "question": "", "suggestions": []},
        "chat_responded": True,
        "artifacts": artifacts,
        "facets": facets,
        "messages": [AIMessage(content=reply or "(response completed)")],
        "trace": trace,
    }
    if request_frame:
        result["request_frame"] = request_frame
        result["request_frames"] = [request_frame]
    if decision.execution_route == "out_of_scope":
        result["skip_session_context"] = True
    return result

def _context_router_clarify_block(decision: ConversationDecision) -> dict[str, Any]:
    return {
        "id": "blocked_1",
        "subject_type": "unknown",
        "subject_label": decision.context_binding.subject_hint,
        "operation": _operation("qa", 0.0),
        "reason": "context_router_clarify",
        "question": decision.reply_guidance or "我需要你补充想看的对象或上下文。",
        "suggestions": ["补充公司、股票代码、宏观主题、持仓，或说明你指的是哪条消息/哪份报告"],
        "fallback_allowed": False,
    }

def _social_prefix(query: str) -> str:
    match = _SOCIAL_PREFIX_RE.match(query or "")
    return match.group(0).strip(" ，,。") if match else ""

def _direct_reply(query: str) -> str:
    if is_greeting(query):
        return "你好！你可以直接告诉我股票、公司、宏观主题或持仓问题，我会先识别任务再开始分析。"
    return "我主要负责金融投研问题。你可以输入股票代码、公司名称、宏观主题，或让我比较多只股票。"

def _natural_clarify_question(query: str, fallback: str) -> str:
    """Convert router guidance into user-facing clarification copy."""
    text = str(fallback or "").strip()
    if not text:
        text = "我还不能确定你想接着看哪一部分。"

    lower_text = text.lower()
    guidance_like = (
        text.startswith(("询问用户", "请询问用户", "请向用户", "向用户询问"))
        or "询问用户" in text[:40]
        or "ask the user" in lower_text[:80]
    )
    if guidance_like:
        if "持仓" in text or "portfolio" in lower_text or "holding" in lower_text:
            return "要判断你今天的持仓风险，我需要你的持仓列表和大致权重；如果不方便，也可以只给主要股票或基金，我先按大类估算。"
        if "报告" in text or "report" in lower_text:
            return "我还不能确定你指的是哪份报告或哪一段结论。把报告标题、结论片段或对应标的发我，我就可以接着聊。"
        if "新闻" in text or "消息" in text or "news" in lower_text:
            return "我还不能确定你指的是哪条新闻。把新闻标题、链接、摘要或对应标的发我，我再判断影响。"
        return "我还不能确定你指的是哪一部分。把前一段结论、报告标题、新闻标题或标的发我，我就可以接着展开。"

    if re.search(r"(第二|第[一二三四五六七八九十0-9]+|继续|展开|上面|刚才|上一条|前面|那它|它|this|that|it)", query, re.IGNORECASE):
        return "我这边没有足够的当前会话上下文，不能确定你指的是哪一点。把那段内容或对应标的发我，我再接着讲。"

    return text

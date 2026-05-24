# -*- coding: utf-8 -*-
"""请求理解节点：一次性完成闲聊、标的、任务和阻塞项识别。"""
from __future__ import annotations

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
    legacy_operation_for_contract,
    requires_per_ticker_research,
    synthesis_compare_operation,
)
from backend.graph.investment_intent import query_requests_investment_opinion
from backend.graph.nodes.conversation_router import (
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


_INDEX_TICKERS = {"SPY", "QQQ", "DIA", "IWM", "VTI", "^IXIC", "^DJI", "^GSPC", "^RUT", "^VIX"}
_NON_ASSET_TOKENS = {
    "PDF", "DOC", "DOCX", "PPT", "PPTX", "CSV", "TXT", "HTML", "URL",
    "IV", "PCR", "RSI", "MACD",
    "USD", "EUR", "GBP", "JPY", "CAD", "AUD", "CHF",
}
_NEWS_HINTS = ("新闻", "消息", "大新闻", "发生什么", "快讯", "news", "headline", "latest")
_PRICE_HINTS = ("价格", "股价", "涨了多少", "跌了多少", "涨幅", "跌幅", "表现", "行情", "price", "quote", "performance")
_IMPACT_HINTS = ("影响", "冲击", "拖累", "风险", "利好", "利空", "impact", "affect", "risk")
_TECHNICAL_HINTS = ("技术面", "技术分析", "k线", "均线", "macd", "rsi", "technical")
_COMPARE_HINTS = ("对比", "比较", "相比", "vs", "versus", "谁更强", "哪个好", "哪个", "compare")
_REPORT_PEER_CONTEXT_HINTS = (
    "覆盖",
    "包括",
    "结合",
    "竞争",
    "竞品",
    "对手",
    "同业",
    "competitive",
    "competitor",
    "peer",
    "cover",
)
_ALERT_HINTS = ("提醒", "预警", "到达", "触及", "涨到", "跌到", "跌破", "突破", "低于", "高于", "alert", "notify", "remind me")
_PORTFOLIO_HINTS = ("持仓", "组合", "仓位", "调仓", "portfolio", "holdings", "rebalance")
_HOLDINGS_HINTS = (
    "13f",
    "form 4",
    "form4",
    "insider",
    "institutional holdings",
    "superinvestor",
    "buffett",
    "berkshire",
    "名义持仓",
    "机构持仓",
    "名人持仓",
    "内部人交易",
    "增持",
    "减持",
    "加仓",
    "巴菲特",
    "伯克希尔",
)
_PRIVATE_INSIDER_INFO_HINTS = (
    "insider information",
    "inside information",
    "material nonpublic",
    "mnpi",
    "内幕消息",
    "内幕信息",
    "未公开重大信息",
)
_PUBLIC_INSIDER_DISCLOSURE_HINTS = (
    "form 4",
    "form4",
    "insider transaction",
    "insider transactions",
    "insider 买卖",
    "内部人交易",
)
_MACRO_HINTS = (
    "美联储", "联储", "降息", "加息", "利率", "fomc", "fed", "cpi", "ppi", "通胀",
    "国债", "收益率", "宏观", "大盘", "纳指", "公告", "大型科技股", "科技股估值", "market",
)
_THEME_HINTS = ("半导体", "芯片", "ai", "人工智能", "大型科技股", "科技股")
_FALLBACK_HINTS = ("如果不知道", "不知道就", "没持仓就", "没有持仓就", "按等权", "按大型科技股", "fallback")
_LIGHTWEIGHT_COMPARE_HINTS = ("如果不知道", "不知道就", "按", "代表", "先别长篇", "别长篇", "不要长篇", "简单说", "短一点")
# P2 (2026-05-03) — vague subject deixis: when the user says "this stock"
# without naming it AND ui_context.active_symbol is present, do a transparent
# weak fallback (bind active_symbol + warn user it can be corrected).
# Risk: a wrong fallback is corrected by one user message; a missed fallback
# costs an extra clarify round-trip. We bias toward the cheaper failure mode.
_VAGUE_SUBJECT_HINTS = (
    "这只票", "这个票", "那只票", "这只股", "这个股", "那只股",
    "这家公司", "那家公司", "这家", "那家",
    "它", "他", "那它", "那他",
    "这只", "这个", "这支",
    "刚才那个", "刚才说的", "之前那个",
    "this stock", "that stock", "this one", "the company",
)
_ASSET_DEICTIC_HINTS = (
    "这只票", "这个票", "那只票", "这只股", "这个股", "那只股",
    "这家公司", "那家公司", "this stock", "that stock", "the company",
)
_SOCIAL_PREFIX_RE = re.compile(r"^\s*(你好|您好|早|早上好|嗨|哈喽|hello|hi)[，,。\s]*(今天天气不错[，,。\s]*)?", re.IGNORECASE)
_GLOBAL_CHAT_VIEWS = {"chat", "main", "global", "conversation"}
_URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+", re.IGNORECASE)
_FORBIDDEN_DIRECT_REPLY_MARKERS = (
    "本轮问题包含",
    "分析对象：",
    "问题：",
)
_RESEARCH_CONFIRMATION_ASK_TERMS = (
    "你希望",
    "是否",
    "要不要",
    "需要我",
    "我可以",
    "如果你希望",
    "would you like",
    "do you want",
    "should i",
)
_RESEARCH_CONFIRMATION_ACTION_TERMS = (
    "启动研究",
    "开始研究",
    "进入研究",
    "研究链路",
    "研究模式",
    "拉取最新",
    "获取最新",
    "最新实时",
    "start research",
    "research mode",
)


_THEME_HINTS = (*_THEME_HINTS, "semiconductor", "semiconductors", "sector", "chips")


def _contains_any(text: str, hints: tuple[str, ...]) -> bool:
    lowered = text.lower()
    for hint in hints:
        needle = str(hint or "").strip().lower()
        if not needle:
            continue
        if re.fullmatch(r"[a-z0-9]{1,3}", needle):
            if re.search(rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])", lowered):
                return True
            continue
        if needle in lowered:
            return True
    return False


_FRAME_FRAGMENT_SPLIT_RE = re.compile(
    r"[\u3001,\uff0c;\uff1b\u3002.!?\uff1f\uff01]+"
    r"|\b(?:and|then|also)\b"
    r"|(?:\u7136\u540e|\u518d|\u4ee5\u53ca|\u5e76\u4e14)",
    re.IGNORECASE,
)


def _router_hint_frame_query(
    *,
    query: str,
    subject_type: str,
    subject_label: str,
    tickers: list[str],
    params: dict[str, Any],
    operation_name: str,
    comparison_requested: bool,
) -> str:
    """Recover the query text for one router frame before compiling a contract.

    Router task operations are only weak fallback signals.  The contract must be
    compiled from the user's frame text whenever that text can be recovered.
    """
    raw_query = str(query or "").strip()
    if not raw_query or comparison_requested:
        return raw_query

    fragments = [part.strip() for part in _FRAME_FRAGMENT_SPLIT_RE.split(raw_query) if part.strip()]
    labels = [str(subject_label or "").strip(), *[str(ticker or "").strip() for ticker in tickers]]
    for ticker in tickers:
        normalized = normalize_ticker(str(ticker or ""))
        if not normalized:
            continue
        mapped_name = COMPANY_MAP.get(normalized)
        if isinstance(mapped_name, str):
            labels.append(mapped_name)
        for alias, value in COMPANY_MAP.items():
            if str(value).upper() == normalized:
                labels.append(str(alias))
        for alias, value in CN_TO_TICKER.items():
            if normalize_ticker(str(value)) == normalized:
                labels.append(str(alias))
    labels = [label for label in labels if label]

    matched: list[str] = []
    for fragment in fragments:
        fragment_upper = fragment.upper()
        if any(label.upper() in fragment_upper for label in labels):
            matched.append(fragment)

    if not matched and subject_type in {"macro", "theme"}:
        for fragment in fragments:
            if _contains_any(fragment, _MACRO_HINTS + _IMPACT_HINTS):
                matched.append(fragment)

    if matched:
        return " ".join(matched)

    topic = params.get("topic") if isinstance(params.get("topic"), str) else ""
    parts = [subject_label, topic]
    if operation_name not in {"qa", "compare"}:
        parts.append(operation_name)
    frame_query = " ".join(str(part) for part in parts if str(part or "").strip()).strip()
    return frame_query or raw_query


def _is_private_insider_information_request(query: str) -> bool:
    lowered = str(query or "").lower()
    if not any(token in lowered for token in _PRIVATE_INSIDER_INFO_HINTS):
        return False
    return not any(token in lowered for token in _PUBLIC_INSIDER_DISCLOSURE_HINTS)


def _has_holdings_intent(query: str) -> bool:
    if _is_private_insider_information_request(query):
        return False
    if query_requests_investment_opinion(query):
        return False
    return _contains_any(query, _HOLDINGS_HINTS)


def _holder_cik_or_name_from_query(query: str) -> str:
    if _contains_any(query, ("buffett", "berkshire", "巴菲特", "伯克希尔")):
        return "Berkshire Hathaway"
    return ""


def _holdings_intent_params(query: str) -> dict[str, Any]:
    params: dict[str, Any] = {}
    holder = _holder_cik_or_name_from_query(query)
    if holder:
        params["holder_cik_or_name"] = holder
    if _contains_any(query, ("form 4", "form4", "insider", "内部人交易")):
        params["focus"] = "insider_transactions"
    elif _contains_any(query, ("13f", "institutional holdings", "机构持仓", "名人持仓", "名义持仓", "增持", "减持", "加仓")):
        params["focus"] = "institutional_holdings"
    return params


def _is_lightweight_representative_compare(query: str) -> bool:
    return _contains_any(query, _THEME_HINTS) and _contains_any(query, _LIGHTWEIGHT_COMPARE_HINTS)


def _is_explicit_brief_request(query: str) -> bool:
    text = str(query or "")
    return any(token in text for token in ("30秒", "先别做长报告", "不要长篇", "快速"))


def _extract_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in _URL_RE.finditer(str(text or "")):
        url = match.group(0).rstrip(".,，。;；:：!?！？")
        if not url or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls[:3]


def _strip_urls(text: str) -> str:
    return _URL_RE.sub(" ", str(text or ""))


def _is_scoped_active_symbol_context(ui_context: dict[str, Any]) -> bool:
    view = str((ui_context or {}).get("view") or "").strip().lower()
    return bool(view) and view not in _GLOBAL_CHAT_VIEWS


def _has_conversation_subject_anchor(memory_context: dict[str, Any]) -> bool:
    if not isinstance(memory_context, dict):
        return False
    if current_report_context(memory_context):
        return True
    last_focus = current_thread_focus(memory_context)
    if isinstance(last_focus, dict) and (last_focus.get("ticker") or last_focus.get("query")):
        return True
    return False


def _has_prior_dialogue(state: GraphState, current_query: str) -> bool:
    messages = state.get("messages")
    if not isinstance(messages, list):
        return False
    current = str(current_query or "").strip()
    for msg in messages:
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        text = str(content or "").strip()
        if text and text != current:
            return True
    return False


def _history_tickers_from_messages(state: GraphState, current_query: str) -> list[str]:
    messages = state.get("messages")
    if not isinstance(messages, list):
        return []
    current = str(current_query or "").strip()
    tickers: list[str] = []
    for msg in reversed(messages[-8:]):
        content = getattr(msg, "content", None)
        if content is None and isinstance(msg, dict):
            content = msg.get("content")
        text = str(content or "").strip()
        if not text or text == current:
            continue
        tickers.extend(_extract_tickers_from_text(text))
    return dedup_tickers(tickers)


def _can_use_active_symbol_fallback(ui_context: dict[str, Any], memory_context: dict[str, Any]) -> bool:
    if not isinstance(ui_context.get("active_symbol"), str) or not ui_context["active_symbol"].strip():
        return False
    if _is_scoped_active_symbol_context(ui_context):
        return True
    return not _has_conversation_subject_anchor(memory_context)


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
    result: dict[str, Any] = {
        "understanding": understanding,
        "reply_contract": reply_contract,
        "tasks": [],
        "blocked_tasks": [],
        "context_refs": context_refs,
        "subject": _build_subject(None, []),
        "operation": _operation("chat", decision.confidence),
        "output_mode": output_mode,
        "clarify": {"needed": False, "reason": "", "question": "", "suggestions": []},
        "chat_responded": True,
        "artifacts": artifacts,
        "messages": [AIMessage(content=reply or "(response completed)")],
        "trace": trace,
    }
    if decision.execution_route == "out_of_scope":
        result["skip_session_context"] = True
    return result


def _apply_reply_contract_to_tasks(tasks: list[dict[str, Any]], reply_contract: dict[str, Any]) -> None:
    """Apply hard UX constraints before policy/planner see the task list."""
    if not reply_contract_disallows_news({"reply_contract": reply_contract}):
        return
    for task in tasks:
        if not isinstance(task, dict):
            continue
        operation = task.get("operation")
        if not isinstance(operation, dict):
            continue
        op_name = str(operation.get("name") or "").strip()
        if op_name not in {"fetch", "news_impact", "daily_brief", "morning_brief"}:
            continue
        params = dict(operation.get("params") or {})
        topic = str(params.get("topic") or "").strip().lower()
        if op_name == "fetch" and topic and topic != "news":
            continue
        try:
            confidence = float(operation.get("confidence") or 0.0)
        except Exception:
            confidence = 0.0
        task["operation"] = {
            **operation,
            "name": "qa",
            "confidence": max(confidence, 0.68),
            "params": {k: v for k, v in params.items() if k not in {"topic", "include_links"}},
        }
        constraints = list(task.get("constraints") or [])
        if "no_news_or_links" not in constraints:
            constraints.append("no_news_or_links")
        task["constraints"] = constraints


def _explicit_report_mode(state: GraphState, output_mode: str) -> bool:
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    analysis_depth = str((ui_context or {}).get("analysis_depth") or "").strip().lower()
    return output_mode == "investment_report" or analysis_depth == "deep_research"


def _explicit_multi_ticker_compare_requested(query: str) -> bool:
    return _contains_any(query, _COMPARE_HINTS) and not _is_lightweight_representative_compare(query)


def _query_frames_extra_tickers_as_report_context(query: str) -> bool:
    return _contains_any(query, _REPORT_PEER_CONTEXT_HINTS)


def _split_primary_report_tickers(
    query: str,
    tickers: list[str],
    *,
    state: GraphState,
    output_mode: str,
) -> tuple[list[str], list[str]]:
    if (
        len(tickers) < 2
        or not _explicit_report_mode(state, output_mode)
        or _explicit_multi_ticker_compare_requested(query)
        or not _query_frames_extra_tickers_as_report_context(query)
    ):
        return tickers, []
    return [tickers[0]], tickers[1:]


def _subject_type_for_ticker(ticker: str) -> str:
    symbol = str(ticker or "").strip().upper()
    if not symbol:
        return "unknown"
    if symbol.endswith("=F"):
        return "commodity"
    if symbol.startswith("^") or symbol in _INDEX_TICKERS:
        return "index"
    return "company"


def _selection_subject_type(selection_types: list[str]) -> str:
    if not selection_types:
        return "research_doc"
    if len(selection_types) == 1:
        first = selection_types[0]
        if first == "news":
            return "news_item"
        if first == "filing":
            return "filing"
        if first in {"url", "web", "article"}:
            return "research_doc"
        return "research_doc"
    if all(t == "news" for t in selection_types):
        return "news_set"
    if all(t == "filing" for t in selection_types):
        return "filing"
    return "research_doc"


def _time_scope(query: str) -> dict[str, Any]:
    q = query.lower()
    if "昨天" in q or "yesterday" in q:
        return {"kind": "yesterday", "label": "昨天"}
    if "今天" in q or "今日" in q or "today" in q:
        return {"kind": "today", "label": "今天"}
    if "这周" in q or "本周" in q or "this week" in q:
        return {"kind": "this_week", "label": "本周"}
    if "最近" in q or "recent" in q:
        return {"kind": "recent", "label": "最近"}
    if "最新" in q or "latest" in q:
        return {"kind": "latest", "label": "最新"}
    return {"kind": "unspecified", "label": ""}


def _operation(name: str, confidence: float = 0.75, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"name": name, "confidence": confidence, "params": params or {}}


def _operation_with_report_peers(operation: dict[str, Any], peer_tickers: list[str]) -> dict[str, Any]:
    if not peer_tickers:
        return operation
    params = dict(operation.get("params") or {})
    params["peer_tickers"] = list(peer_tickers)
    params.setdefault("comparison_context", "covered_as_competitive_context")
    return {**operation, "params": params}


def _company_operations(
    query: str,
    *,
    tickers: list[str],
    allow_multi_ticker_default_compare: bool = True,
    output_mode: str = "",
) -> list[dict[str, Any]]:
    operations: list[dict[str, Any]] = []
    report_mode = str(output_mode or "").strip().lower() == "investment_report"
    if len(tickers) >= 2 and _is_lightweight_representative_compare(query):
        return [_operation("qa", 0.7)]
    if len(tickers) >= 2 and _contains_any(query, _COMPARE_HINTS):
        operations.append(_operation("compare", 0.86))
        return operations
    if not report_mode and query_requests_earnings_price_impact(query):
        operations.append(
            _operation(
                "earnings_impact",
                0.86,
                {
                    "event_type": "earnings",
                    "target_metric": "stock_price",
                    "required_dimensions": ["financials", "earnings", "price", "news", "risk"],
                },
            )
        )
        return operations
    if not report_mode and query_requests_earnings_performance(query):
        operations.append(_operation("earnings_performance", 0.84))
        return operations
    explicit_technical = _contains_any(query, _TECHNICAL_HINTS)
    if explicit_technical:
        operations.append(_operation("technical", 0.82))
    if not explicit_technical and query_requests_investment_opinion(query):
        operations.append(_operation("investment_opinion", 0.86))
        return operations
    if not explicit_technical and _contains_any(query, _PRICE_HINTS):
        operations.append(_operation("price", 0.82))
    if _contains_any(query, _NEWS_HINTS):
        news_params: dict[str, Any] = {"topic": "news"}
        if query_explicitly_requests_links(query):
            news_params["include_links"] = True
        operations.append(_operation("fetch", 0.78, news_params))
    if _contains_any(query, _IMPACT_HINTS):
        operations.append(_operation("analyze_impact", 0.78))
    if not explicit_technical and _contains_any(query, _TECHNICAL_HINTS):
        operations.append(_operation("technical", 0.82))
    if _contains_any(query, _ALERT_HINTS):
        operations.append(_operation("alert_set", 0.88))
    if operations:
        return operations

    subject = {"subject_type": "company", "tickers": tickers}
    parsed = parse_operation({"query": query, "subject": subject})
    operation = parsed.get("operation") or _operation("qa", 0.45)
    decision_trace = (parsed.get("trace") or {}).get("operation_decision") or {}
    if (
        len(tickers) >= 2
        and not allow_multi_ticker_default_compare
        and decision_trace.get("source") == "multi_ticker_default"
    ):
        return [_operation("price", max(float(operation.get("confidence") or 0.0), 0.62))]
    return [operation]


def _domain_intent_operation(domain_intent: str, confidence: float) -> dict[str, Any]:
    mapping = {
        "quote": "price",
        "news": "fetch",
        "analysis": "qa",
        "report_discussion": "qa",
        "doc_qa": "qa",
        "portfolio": "portfolio_impact",
    }
    return _operation(mapping.get(str(domain_intent or ""), "qa"), confidence)


def _router_guided_analysis_operation(decision: ConversationDecision) -> dict[str, Any]:
    """Use the LLM router's typed decision as the source of truth for analysis.

    Generic new-topic analysis with an explicit company is not automatically a
    long research plan. If the router says the answer needs tools, gather the
    light current context that a conversational user expects; if it says tools
    are not needed, keep it as contextual QA.
    """
    if decision.needs_tools:
        return _operation("daily_brief", max(decision.confidence, 0.7))
    return _operation("qa", max(decision.confidence, 0.68))


def _router_directed_company_operations(
    decision: ConversationDecision | None,
    *,
    fallback_operations: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]] | None:
    """Project the LLM router's typed intent into executable company tasks.

    The router already evaluates the full current turn and context. This small
    bridge keeps later legacy fallbacks from turning "quote these tickers" into
    a generic multi-ticker comparison.
    """
    if decision is None:
        return None
    if decision.execution_route == "alert" or decision.domain_intent == "alert":
        source_ops = [
            operation
            for operation in (fallback_operations or [])
            if isinstance(operation, dict)
            and str(operation.get("name") or "").strip()
            in {"fetch", "price", "news_impact", "analyze_impact", "technical"}
        ]
        if source_ops:
            return [*source_ops, _operation("alert_set", max(decision.confidence, 0.78))]
        return [_operation("alert_set", max(decision.confidence, 0.78))]
    if decision.context_binding.source not in {"none", ""}:
        return None
    if decision.domain_intent in {"quote", "news", "report_discussion", "doc_qa", "portfolio"}:
        primary = _domain_intent_operation(decision.domain_intent, decision.confidence)
        primary_name = str(primary.get("name") or "").strip()
        supplemental_ops = [
            operation
            for operation in (fallback_operations or [])
            if isinstance(operation, dict)
            and str(operation.get("name") or "").strip() in {"price", "fetch", "news_impact", "analyze_impact", "technical"}
            and str(operation.get("name") or "").strip() != primary_name
        ]
        return [primary, *supplemental_ops]
    if decision.domain_intent == "analysis":
        fallback_names = {
            str((operation or {}).get("name") or "").strip()
            for operation in (fallback_operations or [])
            if isinstance(operation, dict)
        }
        if fallback_names - {"", "qa"}:
            return None
        if decision.relation == "compare":
            return None
        return [_router_guided_analysis_operation(decision)]
    return None


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


def _add_per_ticker_company_tasks(
    tasks: list[dict[str, Any]],
    *,
    tickers: list[str],
    operations: list[dict[str, Any]],
    query: str,
    priority: int,
    reason: str,
) -> None:
    for ticker in tickers:
        subject_type = _subject_type_for_ticker(ticker)
        for operation in operations:
            _add_task(
                tasks,
                subject_type=subject_type,
                operation=operation,
                query=query,
                tickers=[ticker],
                subject_label=ticker,
                priority=priority,
                reason=reason,
            )


def _subject_type_for_decision(decision: ConversationDecision) -> str:
    if decision.context_binding.source == "portfolio":
        return "portfolio"
    if decision.context_binding.source == "selection":
        return "research_doc"
    if decision.domain_intent in {"news", "analysis"}:
        return "theme"
    return "unknown"


def _add_unbound_research_task(
    *,
    tasks: list[dict[str, Any]],
    decision: ConversationDecision,
    query: str,
) -> None:
    """Convert an LLM research decision without a ticker into a generic task.

    This keeps the planner gate generic. The LLM router decides that evidence or
    tools are needed; the task only carries that intent forward without adding a
    new keyword table.
    """
    subject_type = _subject_type_for_decision(decision)
    subject_label = decision.context_binding.subject_hint or query[:80]
    _add_task(
        tasks,
        subject_type=subject_type,
        subject_label=subject_label,
        operation=_domain_intent_operation(decision.domain_intent, decision.confidence),
        query=query,
        priority=50,
        reason="conversation_router_unbound_research",
        params={"context_binding": decision.context_binding.model_dump()},
    )


def _add_explicit_url_tasks(
    *,
    tasks: list[dict[str, Any]],
    query: str,
    current_tickers: list[str],
) -> bool:
    urls = _extract_urls(query)
    if not urls:
        return False
    existing_urls: set[str] = set()
    for task in tasks:
        op = task.get("operation") if isinstance(task.get("operation"), dict) else {}
        params = op.get("params") if isinstance(op.get("params"), dict) else {}
        value = str(params.get("url") or "").strip()
        if value:
            existing_urls.add(value)
        raw_urls = params.get("urls")
        if isinstance(raw_urls, list):
            existing_urls.update(str(item or "").strip() for item in raw_urls if str(item or "").strip())
    added = False
    scoped_tickers = dedup_tickers(list(current_tickers or []))
    for idx, url in enumerate(urls, 1):
        if url in existing_urls:
            continue
        _add_task(
            tasks,
            subject_type="research_doc",
            subject_label=url,
            operation=_operation("qa", 0.68, {"url": url}),
            query=query,
            tickers=scoped_tickers,
            priority=17 + idx,
            reason="explicit_url_reference",
            params={"url": url},
        )
        added = True
    return added


def _add_router_task_hints(
    *,
    tasks: list[dict[str, Any]],
    context_refs: list[dict[str, Any]],
    decision: ConversationDecision,
    query: str,
    current_tickers: list[str],
    selection_ids: list[str] | None = None,
    selection_types: list[str] | None = None,
) -> bool:
    """Project LLM-decomposed atomic requests into tasks.

    This is the generic path for compound turns. The LLM router owns the
    semantic split; this function only validates enum-like fields and preserves
    explicit ticker/subject payloads.
    """
    added = False
    bound_tickers: list[str] = []
    if decision.context_binding.source != "selection":
        for task in tasks:
            raw_tickers = task.get("tickers")
            if not isinstance(raw_tickers, list):
                continue
            bound_tickers.extend(normalize_ticker(str(ticker)) for ticker in raw_tickers if str(ticker).strip())
    scoped_current_tickers = dedup_tickers(list(current_tickers or []) + bound_tickers)

    def _has_task(operation_name: str, ticker: str) -> bool:
        wanted = normalize_ticker(str(ticker))
        for task in tasks:
            op = (task.get("operation") or {}).get("name") if isinstance(task.get("operation"), dict) else None
            if str(op or "").strip().lower() != operation_name:
                continue
            if wanted in [normalize_ticker(str(item)) for item in (task.get("tickers") or [])]:
                return True
        return False

    def _add_support_task(
        *,
        ticker: str,
        subject_type: str,
        operation_name: str,
        params: dict[str, Any] | None,
        priority: int,
    ) -> None:
        if _has_task(operation_name, ticker):
            return
        _add_task(
            tasks,
            subject_type=subject_type,
            subject_label=ticker,
            operation=_operation(operation_name, max(decision.confidence, 0.68), params or {}),
            query=query,
            tickers=[ticker],
            priority=priority,
            reason="conversation_router_task_hint_support",
            params=params or {},
        )

    for idx, hint in enumerate(decision.task_hints or (), 1):
        if not isinstance(hint, dict):
            continue
        operation_name = str(hint.get("operation") or "qa").strip().lower()
        if operation_name == "alert_set":
            continue
        subject_type = str(hint.get("subject_type") or "unknown").strip().lower()
        subject_label = str(hint.get("subject_label") or "").strip()
        hint_tickers = [
            normalize_ticker(str(ticker))
            for ticker in (hint.get("tickers") if isinstance(hint.get("tickers"), list) else [])
            if str(ticker).strip()
        ]
        if not hint_tickers and subject_label:
            hint_tickers = [
                normalize_ticker(str(ticker))
                for ticker in (extract_tickers(subject_label).get("tickers") or [])
                if str(ticker).strip()
            ]
        if not hint_tickers and subject_type in {"company", "index", "crypto", "fund"} and len(scoped_current_tickers) == 1:
            hint_tickers = [scoped_current_tickers[0]]
        if (
            decision.context_binding.source
            in {"active_symbol", "last_turn", "recent_focus", "last_report", "unresolved_clarification"}
            and scoped_current_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
        ):
            if hint_tickers:
                scoped = [ticker for ticker in hint_tickers if ticker in set(scoped_current_tickers)]
                if not scoped:
                    continue
                hint_tickers = scoped
            else:
                hint_tickers = list(scoped_current_tickers)

        if (
            operation_name == "qa"
            and decision.needs_tools
            and hint_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
        ):
            projected_operation = _domain_intent_operation(decision.domain_intent, decision.confidence)
            projected_name = str(projected_operation.get("name") or "").strip().lower()
            if projected_name and projected_name != "qa":
                operation_name = projected_name
            elif decision.domain_intent == "analysis":
                operation_name = str(_router_guided_analysis_operation(decision).get("name") or "qa").strip().lower()

        params = dict(hint.get("params") or {}) if isinstance(hint.get("params"), dict) else {}
        if operation_name == "fetch" and not params.get("topic"):
            params["topic"] = "news"
        if operation_name in {"fetch", "news_impact", "daily_brief"} and query_explicitly_requests_links(query):
            params.setdefault("include_links", True)
        if subject_type == "unknown" and _contains_any(f"{subject_label} {query}", _THEME_HINTS):
            subject_type = "theme"
        if decision.context_binding.source != "none":
            params.setdefault("context_binding", decision.context_binding.model_dump())
        task_selection_ids = list(selection_ids or []) if subject_type in {"news_item", "news_set", "filing", "research_doc"} else []
        task_selection_types = list(selection_types or []) if task_selection_ids else []

        if (
            operation_name == "fetch"
            and decision.domain_intent == "analysis"
            and hint_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
        ):
            for ticker in dedup_tickers(hint_tickers):
                _add_support_task(
                    ticker=ticker,
                    subject_type=subject_type,
                    operation_name="price",
                    params={},
                    priority=15,
                )
                added = True

        if (
            operation_name == "price"
            and hint_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
            and query_explicitly_requests_links(query)
            and _contains_any(query, _NEWS_HINTS)
        ):
            for ticker in dedup_tickers(hint_tickers):
                _add_support_task(
                    ticker=ticker,
                    subject_type=subject_type,
                    operation_name="fetch",
                    params={"topic": "news", "include_links": True},
                    priority=16,
                )
                added = True

        if (
            operation_name in {"analyze_impact", "news_impact", "daily_brief"}
            and hint_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
        ):
            for ticker in dedup_tickers(hint_tickers):
                _add_support_task(
                    ticker=ticker,
                    subject_type=subject_type,
                    operation_name="price",
                    params={},
                    priority=15,
                )
                _add_support_task(
                    ticker=ticker,
                    subject_type=subject_type,
                    operation_name="fetch",
                    params={"topic": "news"},
                    priority=16,
                )
                added = True

        if operation_name == "compare" and len(hint_tickers) >= 2:
            aspects = {
                str(item).strip().lower()
                for item in (params.get("aspects") if isinstance(params.get("aspects"), list) else [])
                if str(item).strip()
            }
            wants_price = not aspects or bool(aspects & {"price", "quote", "price_change", "change", "涨跌幅", "价格"})
            wants_news = not aspects or bool(aspects & {"news", "headline", "latest_news", "新闻", "消息"})
            for ticker in dedup_tickers(hint_tickers):
                if wants_price:
                    _add_support_task(
                        ticker=ticker,
                        subject_type=subject_type,
                        operation_name="price",
                        params={},
                        priority=15,
                    )
                    added = True
                if wants_news:
                    _add_support_task(
                        ticker=ticker,
                        subject_type=subject_type,
                        operation_name="fetch",
                        params={"topic": "news"},
                        priority=16,
                    )
                    added = True

        atomic_tickers = dedup_tickers(hint_tickers)
        if (
            operation_name in {"price", "technical"}
            and len(atomic_tickers) > 1
            and subject_type in {"company", "index", "crypto", "fund"}
        ):
            for ticker in atomic_tickers:
                _add_task(
                    tasks,
                    subject_type=subject_type,
                    subject_label=ticker,
                    operation=_operation(operation_name, max(decision.confidence, 0.68), params),
                    query=query,
                    tickers=[ticker],
                    selection_ids=task_selection_ids,
                    selection_types=task_selection_types,
                    priority=18 + idx,
                    reason="conversation_router_task_hint",
                    params=params,
                )
            added = True
            continue

        _add_task(
            tasks,
            subject_type=subject_type,
            subject_label=subject_label or ", ".join(hint_tickers) or subject_type,
            operation=_operation(operation_name, max(decision.confidence, 0.68), params),
            query=query,
            tickers=atomic_tickers,
            selection_ids=task_selection_ids,
            selection_types=task_selection_types,
            priority=18 + idx,
            reason="conversation_router_task_hint",
            params=params,
        )
        added = True

    if added:
        context_refs.append(
            {
                "source": "conversation_router",
                "key": "task_hints",
                "label": "LLM拆分的原子请求",
                "value": len([hint for hint in (decision.task_hints or ()) if isinstance(hint, dict)]),
            }
        )
    return added


def _add_router_task_hints_contract(
    *,
    tasks: list[dict[str, Any]],
    context_refs: list[dict[str, Any]],
    decision: ConversationDecision,
    query: str,
    output_mode: str = "chat",
    current_tickers: list[str],
    selection_ids: list[str] | None = None,
    selection_types: list[str] | None = None,
    intent_contracts: list[dict[str, Any]] | None = None,
) -> bool:
    """Compile router hint frames through the evidence-first intent contract."""
    added = False
    bound_tickers: list[str] = []
    if decision.context_binding.source != "selection":
        for task in tasks:
            raw_tickers = task.get("tickers")
            if isinstance(raw_tickers, list):
                bound_tickers.extend(normalize_ticker(str(ticker)) for ticker in raw_tickers if str(ticker).strip())
    scoped_current_tickers = dedup_tickers(list(current_tickers or []) + bound_tickers)

    def _hint_domain_intent(operation_name: str) -> str:
        if operation_name == "price":
            return "quote"
        if operation_name in {"fetch", "daily_brief", "news_impact"}:
            return "news"
        if operation_name == "technical":
            return "technical"
        if operation_name == "holdings":
            return "holdings"
        if operation_name in {"macro_brief", "fact_check"}:
            return "macro"
        return decision.domain_intent

    def _add_projected_task(
        *,
        contract: dict[str, Any],
        subject_type: str,
        subject_label: str,
        tickers: list[str],
        priority: int,
        params: dict[str, Any] | None = None,
        task_selection_ids: list[str] | None = None,
        task_selection_types: list[str] | None = None,
    ) -> None:
        operation = legacy_operation_for_contract(contract, subject_type=subject_type)
        op_params = dict(operation.get("params") or {})
        if params:
            op_params.update(params)
        operation = {**operation, "params": op_params}
        _add_task(
            tasks,
            subject_type=subject_type,
            subject_label=subject_label or ", ".join(tickers) or subject_type,
            operation=operation,
            query=query,
            tickers=tickers,
            selection_ids=task_selection_ids,
            selection_types=task_selection_types,
            priority=priority,
            reason="intent_contract_projection",
            params=op_params,
        )

    def _add_news_support_from_contract(
        *,
        tickers: list[str],
        subject_type: str,
        subject_label: str,
        priority: int,
        frame_id: str,
        task_selection_ids: list[str] | None = None,
        task_selection_types: list[str] | None = None,
    ) -> None:
        news_contract = derive_intent_contract(
            query=query,
            tickers=tickers,
            output_mode=output_mode,
            comparison_requested=False,
            domain_intent="news",
            subject_type=subject_type,
            frame_id=frame_id,
        )
        if intent_contracts is not None:
            intent_contracts.append(dict(news_contract))
        news_params: dict[str, Any] = {"topic": "news"}
        if query_explicitly_requests_links(query):
            news_params["include_links"] = True
        _add_projected_task(
            contract=news_contract,
            subject_type=subject_type,
            subject_label=subject_label,
            tickers=tickers,
            priority=priority,
            params=news_params,
            task_selection_ids=task_selection_ids,
            task_selection_types=task_selection_types,
        )

    router_compare_requested = bool(
        len(scoped_current_tickers) >= 2
        and (decision.relation == "compare" or _explicit_multi_ticker_compare_requested(query))
    )
    if router_compare_requested:
        first_hint = next((hint for hint in (decision.task_hints or ()) if isinstance(hint, dict)), {})
        subject_type = str(first_hint.get("subject_type") or "company").strip().lower()
        subject_label = str(first_hint.get("subject_label") or ", ".join(scoped_current_tickers)).strip()
        contract = derive_intent_contract(
            query=query,
            tickers=scoped_current_tickers,
            output_mode=output_mode,
            comparison_requested=True,
            domain_intent=decision.domain_intent,
            subject_type=subject_type,
            frame_id="router_compare",
        )
        if intent_contracts is not None:
            intent_contracts.append(dict(contract))
        contract_tickers = list(contract.get("primary_tickers") or scoped_current_tickers)
        if requires_per_ticker_research(contract):
            compare_operation = synthesis_compare_operation(contract)
            _add_task(
                tasks,
                subject_type=subject_type,
                subject_label=subject_label or ", ".join(contract_tickers),
                operation=compare_operation,
                query=query,
                tickers=contract_tickers,
                priority=18,
                reason="intent_contract_synthesis_compare",
                params=dict(compare_operation.get("params") or {}),
            )
            _add_per_ticker_company_tasks(
                tasks,
                tickers=contract_tickers,
                operations=[evidence_focused_operation(contract)],
                query=query,
                priority=22,
                reason="intent_contract_per_ticker_evidence",
            )
        else:
            _add_projected_task(
                contract=contract,
                subject_type=subject_type,
                subject_label=subject_label or ", ".join(contract_tickers),
                tickers=contract_tickers,
                priority=18,
            )
        context_refs.append(
            {
                "source": "conversation_router",
                "key": "task_hints",
                "label": "router compare frame compiled through intent_contract",
                "value": len([hint for hint in (decision.task_hints or ()) if isinstance(hint, dict)]),
            }
        )
        return True

    for idx, hint in enumerate(decision.task_hints or (), 1):
        if not isinstance(hint, dict):
            continue
        operation_name = str(hint.get("operation") or "qa").strip().lower()
        if operation_name == "alert_set":
            continue
        subject_type = str(hint.get("subject_type") or "unknown").strip().lower()
        subject_label = str(hint.get("subject_label") or "").strip()
        hint_tickers = [
            normalize_ticker(str(ticker))
            for ticker in (hint.get("tickers") if isinstance(hint.get("tickers"), list) else [])
            if str(ticker).strip()
        ]
        if not hint_tickers and subject_label:
            hint_tickers = [
                normalize_ticker(str(ticker))
                for ticker in (extract_tickers(subject_label).get("tickers") or [])
                if str(ticker).strip()
            ]
        if not hint_tickers and subject_type in {"company", "index", "crypto", "fund"} and len(scoped_current_tickers) == 1:
            hint_tickers = [scoped_current_tickers[0]]
        if (
            decision.context_binding.source
            in {"active_symbol", "last_turn", "recent_focus", "last_report", "unresolved_clarification"}
            and scoped_current_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
        ):
            if hint_tickers:
                scoped = [ticker for ticker in hint_tickers if ticker in set(scoped_current_tickers)]
                if not scoped:
                    continue
                hint_tickers = scoped
            else:
                hint_tickers = list(scoped_current_tickers)

        params = dict(hint.get("params") or {}) if isinstance(hint.get("params"), dict) else {}
        if operation_name == "fetch" and not params.get("topic"):
            params["topic"] = "news"
        if operation_name in {"fetch", "news_impact", "daily_brief"} and query_explicitly_requests_links(query):
            params.setdefault("include_links", True)
        if subject_type == "unknown" and _contains_any(f"{subject_label} {query}", _THEME_HINTS):
            subject_type = "theme"
        if decision.context_binding.source != "none":
            params.setdefault("context_binding", decision.context_binding.model_dump())

        task_selection_ids = list(selection_ids or []) if subject_type in {"news_item", "news_set", "filing", "research_doc"} else []
        task_selection_types = list(selection_types or []) if task_selection_ids else []
        atomic_tickers = dedup_tickers(hint_tickers)
        comparison_requested = bool(
            len(atomic_tickers) >= 2
            and (
                operation_name == "compare"
                or decision.relation == "compare"
                or _explicit_multi_ticker_compare_requested(query)
            )
        )
        frame_query = _router_hint_frame_query(
            query=query,
            subject_type=subject_type,
            subject_label=subject_label,
            tickers=atomic_tickers,
            params=params,
            operation_name=operation_name,
            comparison_requested=comparison_requested,
        )
        contract = derive_intent_contract(
            query=frame_query,
            tickers=atomic_tickers,
            output_mode=output_mode,
            comparison_requested=comparison_requested,
            domain_intent=decision.domain_intent,
            subject_type=subject_type,
            frame_id=f"router_hint_{idx}",
        )
        if not contract.get("required_evidence") and operation_name not in {"qa", "compare"}:
            contract = derive_intent_contract(
                query=frame_query,
                tickers=atomic_tickers,
                output_mode=output_mode,
                comparison_requested=comparison_requested,
                domain_intent=_hint_domain_intent(operation_name),
                subject_type=subject_type,
                frame_id=f"router_hint_{idx}",
            )
        if intent_contracts is not None:
            intent_contracts.append(dict(contract))

        if comparison_requested and requires_per_ticker_research(contract):
            contract_tickers = list(contract.get("primary_tickers") or atomic_tickers)
            compare_operation = synthesis_compare_operation(contract)
            _add_task(
                tasks,
                subject_type=subject_type,
                subject_label=subject_label or ", ".join(contract_tickers),
                operation=compare_operation,
                query=query,
                tickers=contract_tickers,
                priority=18 + idx,
                reason="intent_contract_synthesis_compare",
                params=dict(compare_operation.get("params") or {}),
            )
            _add_per_ticker_company_tasks(
                tasks,
                tickers=contract_tickers,
                operations=[evidence_focused_operation(contract)],
                query=query,
                priority=22 + idx,
                reason="intent_contract_per_ticker_evidence",
            )
            added = True
            continue

        if len(atomic_tickers) > 1 and subject_type in {"company", "index", "crypto", "fund"} and not comparison_requested:
            for ticker in atomic_tickers:
                single_contract = derive_intent_contract(
                    query=frame_query,
                    tickers=[ticker],
                    output_mode=output_mode,
                    comparison_requested=False,
                    domain_intent=decision.domain_intent,
                    subject_type=subject_type,
                    frame_id=f"router_hint_{idx}_{ticker}",
                )
                if not single_contract.get("required_evidence") and operation_name not in {"qa", "compare"}:
                    single_contract = derive_intent_contract(
                        query=frame_query,
                        tickers=[ticker],
                        output_mode=output_mode,
                        comparison_requested=False,
                        domain_intent=_hint_domain_intent(operation_name),
                        subject_type=subject_type,
                        frame_id=f"router_hint_{idx}_{ticker}",
                    )
                if intent_contracts is not None:
                    intent_contracts.append(dict(single_contract))
                _add_projected_task(
                    contract=single_contract,
                    subject_type=subject_type,
                    subject_label=ticker,
                    tickers=[ticker],
                    priority=18 + idx,
                    params=params,
                    task_selection_ids=task_selection_ids,
                    task_selection_types=task_selection_types,
                )
                if (
                    operation_name == "price"
                    and query_explicitly_requests_links(query)
                    and _contains_any(query, _NEWS_HINTS)
                ):
                    _add_news_support_from_contract(
                        tickers=[ticker],
                        subject_type=subject_type,
                        subject_label=ticker,
                        priority=19 + idx,
                        frame_id=f"router_hint_{idx}_{ticker}_news",
                        task_selection_ids=task_selection_ids,
                        task_selection_types=task_selection_types,
                    )
            added = True
            continue

        _add_projected_task(
            contract=contract,
            subject_type=subject_type,
            subject_label=subject_label or ", ".join(atomic_tickers) or subject_type,
            tickers=atomic_tickers,
            priority=18 + idx,
            params=params,
            task_selection_ids=task_selection_ids,
            task_selection_types=task_selection_types,
        )
        if (
            operation_name == "price"
            and atomic_tickers
            and subject_type in {"company", "index", "crypto", "fund"}
            and query_explicitly_requests_links(query)
            and _contains_any(query, _NEWS_HINTS)
        ):
            _add_news_support_from_contract(
                tickers=atomic_tickers,
                subject_type=subject_type,
                subject_label=subject_label or ", ".join(atomic_tickers),
                priority=19 + idx,
                frame_id=f"router_hint_{idx}_news",
                task_selection_ids=task_selection_ids,
                task_selection_types=task_selection_types,
            )
        added = True

    if added:
        context_refs.append(
            {
                "source": "conversation_router",
                "key": "task_hints",
                "label": "router frames compiled through intent_contract",
                "value": len([hint for hint in (decision.task_hints or ()) if isinstance(hint, dict)]),
            }
        )
    return added


def _macro_operation(query: str) -> dict[str, Any]:
    q = str(query or "").lower()
    if any(token in q for token in ("为什么", "为何", "怎么", "如何", "why", "mechanism")):
        return _operation("qa", 0.72)
    if any(h in query for h in ("降息没", "有没有降息", "概率", "变了吗", "事实", "核查")):
        return _operation("fact_check", 0.76)
    if _contains_any(query, _IMPACT_HINTS) or "估值" in query:
        return _operation("analyze_impact", 0.78)
    if _contains_any(query, _NEWS_HINTS):
        return _operation("fetch", 0.72, {"topic": "macro_news"})
    return _operation("macro_brief", 0.68)


def _macro_subject_label(query: str) -> str:
    q = str(query or "").lower()
    indicators = [
        ("cpi", "CPI"),
        ("ppi", "PPI"),
        ("fomc", "FOMC"),
        ("fed", "美联储"),
        ("美联储", "美联储"),
        ("联储", "美联储"),
        ("降息", "利率路径"),
        ("加息", "利率路径"),
        ("利率", "利率路径"),
        ("通胀", "通胀"),
        ("收益率", "国债收益率"),
        ("国债", "国债收益率"),
        ("纳指", "纳指"),
        ("大型科技股", "大型科技股"),
        ("科技股", "科技股"),
    ]
    labels: list[str] = []
    for token, label in indicators:
        if token in q and label not in labels:
            labels.append(label)
    return " / ".join(labels[:3]) if labels else "宏观环境"


def _social_prefix(query: str) -> str:
    match = _SOCIAL_PREFIX_RE.match(query or "")
    return match.group(0).strip(" ，,。") if match else ""


def _direct_reply(query: str) -> str:
    if is_greeting(query):
        return "你好！你可以直接告诉我股票、公司、宏观主题或持仓问题，我会先识别任务再开始分析。"
    return "我主要负责金融投研问题。你可以输入股票代码、公司名称、宏观主题，或让我比较多只股票。"


def _query_explicitly_requests_price_data(query: str) -> bool:
    text = str(query or "")
    if wants_no_news_or_links(text):
        return False
    lowered = text.lower()
    return bool(
        re.search(r"\b(?:what|which|where)\s+(?:is|are)?\s*(?:the\s+)?(?:current\s+)?(?:stock\s+)?(?:price|quote)\b", lowered)
        or re.search(r"\b(?:current|real-time|realtime|latest)\s+(?:stock\s+)?(?:price|quote)\b", lowered)
        or re.search(r"\b(?:price|prices|quote)\s+now\b", lowered)
        or re.search(r"\b(?:current|latest|recent|today'?s?)\s+(?:stock\s+)?performance\b", lowered)
        or re.search(r"\bperformance\s+(?:now|today|recently)\b", lowered)
        or re.search(r"\bhow\s+much\s+(?:is|are)\b", lowered)
        or re.search(r"\b(?:trading|trade)\s+at\b", lowered)
        or _contains_any(
            text,
            (
                "最新股价",
                "实时股价",
                "当前股价",
                "现在股价",
                "股价多少",
                "价格多少",
                "现在多少钱",
                "当前价格",
                "实时报价",
                "报价",
                "行情",
                "最新表现",
                "近期表现",
                "今天表现",
                "今日表现",
                "涨了多少",
                "跌了多少",
                "涨幅",
                "跌幅",
            ),
        )
    )


def _direct_decision_contract_requires_evidence(
    query: str,
    decision: ConversationDecision,
    *,
    current_tickers: list[str] | None = None,
) -> bool:
    tickers = dedup_tickers(
        list(current_tickers or [])
        or [
            str(ticker)
            for ticker in (extract_tickers(_strip_urls(query)).get("tickers") or [])
            if str(ticker).strip()
        ]
    )
    if not tickers:
        return False
    contract = derive_intent_contract(
        query=query,
        tickers=tickers,
        output_mode="chat",
        comparison_requested=False,
        domain_intent=decision.domain_intent,
        subject_type="company",
        frame_id="direct_projection_probe",
    )
    facets = {str(facet) for facet in (contract.get("facets") or []) if str(facet).strip()}
    return bool("external_entity_impact" in facets and contract.get("required_evidence"))


def _direct_decision_must_project_tasks(
    query: str,
    decision: ConversationDecision,
    *,
    current_tickers: list[str] | None = None,
) -> bool:
    """Prevent an LLM direct route from swallowing explicit tool/data requests."""
    if wants_no_news_or_links(query):
        return False
    return bool(
        _extract_urls(query)
        or query_explicitly_requests_sources(query)
        or _contains_any(query, _NEWS_HINTS)
        or _contains_any(query, _TECHNICAL_HINTS)
        or query_requests_investment_opinion(query)
        or _query_explicitly_requests_price_data(query)
        or _contains_any(query, _PORTFOLIO_HINTS)
        or decision.needs_tools
        or _task_hints_require_execution(decision.task_hints, query, allow_subject_label_refs=True)
        or _direct_decision_contract_requires_evidence(query, decision, current_tickers=current_tickers)
        or (decision.domain_intent == "quote" and _query_explicitly_requests_price_data(query))
        or decision.domain_intent in {"news", "doc_qa", "portfolio", "alert"}
    )


def _force_grounded_research_decision(decision: ConversationDecision) -> ConversationDecision:
    return replace(
        decision,
        execution_route="research",
        needs_tools=True,
        confidence=max(decision.confidence, 0.74),
        reason=decision.reason or "explicit current-data/tool request must project tasks",
    )


def _query_requests_company_side_data(query: str) -> bool:
    text = _strip_urls(str(query or ""))
    if wants_no_news_or_links(text):
        return False
    return bool(
        _query_explicitly_requests_price_data(text)
        or _contains_any(text, _NEWS_HINTS)
        or _contains_any(text, _TECHNICAL_HINTS)
        or _contains_any(text, _PORTFOLIO_HINTS)
    )


def _query_can_fallback_to_direct_finance_answer(query: str) -> bool:
    text = _strip_urls(str(query or "")).strip()
    if not text:
        return False
    if _extract_urls(text) or query_explicitly_requests_sources(text) or query_explicitly_requests_links(text):
        return False
    if _query_explicitly_requests_price_data(text) or _contains_any(text, _TECHNICAL_HINTS) or query_requests_investment_opinion(text) or _contains_any(text, _PORTFOLIO_HINTS):
        return False
    if not wants_no_news_or_links(text) and _contains_any(text, _NEWS_HINTS):
        return False
    return bool(has_financial_intent(text) or _contains_any(text, _THEME_HINTS))


def _prune_url_only_company_context_tasks(
    tasks: list[dict[str, Any]],
    *,
    query: str,
    explicit_urls: list[str],
) -> list[dict[str, Any]]:
    """Keep explicit URL reading focused on the URL unless side data was requested."""
    if not explicit_urls or _query_requests_company_side_data(query):
        return tasks
    has_url_task = any(
        isinstance((task.get("operation") or {}).get("params"), dict)
        and (
            (task.get("operation") or {}).get("params", {}).get("url")
            or (task.get("operation") or {}).get("params", {}).get("urls")
        )
        for task in tasks
        if isinstance(task, dict)
    )
    if not has_url_task:
        return tasks
    pruned: list[dict[str, Any]] = []
    for task in tasks:
        if not isinstance(task, dict):
            continue
        op_name = str((task.get("operation") or {}).get("name") or "").strip()
        subject_type = str(task.get("subject_type") or "").strip().lower()
        reason = str(task.get("reason") or "").strip()
        if (
            reason == "conversation_router_intent"
            and subject_type in {"company", "index", "crypto", "fund"}
            and op_name in {"qa", "daily_brief", "fetch", "analyze_impact", "news_impact"}
        ):
            continue
        pruned.append(task)
    return pruned


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


def _sanitize_blocked_task_questions(query: str, blocked_tasks: list[dict[str, Any]]) -> None:
    for task in blocked_tasks:
        if not isinstance(task, dict):
            continue
        task["question"] = _natural_clarify_question(query, str(task.get("question") or ""))




def _normalize_selection(ui_context: dict[str, Any]) -> tuple[list[str], list[str], list[dict[str, Any]]]:
    raw = ui_context.get("selections")
    if not raw and isinstance(ui_context.get("selection"), dict):
        raw = [ui_context["selection"]]
    selections = raw if isinstance(raw, list) else []
    payload = [item for item in selections if isinstance(item, dict)]
    ids: list[str] = []
    types: list[str] = []
    seen_ids: set[str] = set()
    for item in payload:
        item_id = str(item.get("id") or "").strip()
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "report":
            item_type = "doc"
        if item_id and item_id not in seen_ids:
            seen_ids.add(item_id)
            ids.append(item_id)
        if item_type:
            types.append(item_type)
    return ids, types, payload


def _selection_urls(ui_context: dict[str, Any]) -> list[str]:
    raw = ui_context.get("selections")
    if not raw and isinstance(ui_context.get("selection"), dict):
        raw = [ui_context["selection"]]
    selections = raw if isinstance(raw, list) else []
    urls: list[str] = []
    seen: set[str] = set()
    for item in selections:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip().rstrip(".,，。；;!?！？")
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls[:3]


def _portfolio_context_available(query: str, ui_context: dict[str, Any]) -> bool:
    if "我持有" in query or "持有" in query and bool(extract_tickers(query).get("tickers")):
        return True
    for key in ("portfolio", "positions", "holdings"):
        value = ui_context.get(key)
        if isinstance(value, (list, tuple, dict)) and len(value) > 0:
            return True
    return False


def _add_task(
    tasks: list[dict[str, Any]],
    *,
    subject_type: str,
    operation: dict[str, Any],
    query: str,
    tickers: list[str] | None = None,
    subject_label: str = "",
    selection_ids: list[str] | None = None,
    selection_types: list[str] | None = None,
    priority: int = 50,
    reason: str = "rule_match",
    constraints: list[str] | None = None,
    params: dict[str, Any] | None = None,
) -> None:
    task_id = f"task_{len(tasks) + 1}"
    tasks.append(
        {
            "id": task_id,
            "subject_type": subject_type,
            "subject_label": subject_label,
            "tickers": tickers or [],
            "selection_ids": selection_ids or [],
            "selection_types": selection_types or [],
            "operation": operation,
            "time_scope": _time_scope(query),
            "priority": priority,
            "status": "ready",
            "reason": reason,
            "constraints": constraints or [],
            "params": params or {},
        }
    )


def _build_subject(
    primary: dict[str, Any] | None,
    selection_payload: list[dict[str, Any]],
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not primary:
        return {
            "subject_type": "unknown",
            "tickers": [],
            "selection_ids": [],
            "selection_types": [],
            "selection_payload": [],
            "binding_tier": "understanding_none",
        }
    merged_tickers = dedup_tickers(
        [
            str(ticker)
            for task in (tasks or [])
            if isinstance(task, dict)
            for ticker in (task.get("tickers") or [])
            if str(ticker or "").strip()
        ]
    )
    if not merged_tickers:
        merged_tickers = list(primary.get("tickers") or [])
    return {
        "subject_type": primary.get("subject_type") or "unknown",
        "tickers": merged_tickers,
        "selection_ids": list(primary.get("selection_ids") or []),
        "selection_types": list(primary.get("selection_types") or []),
        "selection_payload": selection_payload if primary.get("selection_ids") else [],
        "binding_tier": "understanding",
        "is_comparison": (primary.get("operation") or {}).get("name") == "compare",
    }


def _extract_tickers_from_text(text: str) -> list[str]:
    if not str(text or "").strip():
        return []
    return dedup_tickers(
        [
            str(t)
            for t in (extract_tickers(str(text)).get("tickers") or [])
            if str(t).strip() and str(t).strip().upper() not in _NON_ASSET_TOKENS
        ]
    )


def _portfolio_tickers_from_context(ui_context: dict[str, Any]) -> list[str]:
    raw_items: list[Any] = []
    for key in ("portfolio", "positions", "holdings"):
        value = ui_context.get(key)
        if isinstance(value, dict):
            raw_items.extend(value.keys())
            raw_items.extend(value.values())
        elif isinstance(value, (list, tuple)):
            raw_items.extend(value)

    candidates: list[str] = []
    for item in raw_items:
        if isinstance(item, dict):
            candidates.extend(
                str(item.get(key) or "")
                for key in ("ticker", "symbol", "asset", "id")
                if item.get(key)
            )
        elif isinstance(item, str):
            candidates.append(item)

    tickers: list[str] = []
    for candidate in candidates:
        tickers.extend(_extract_tickers_from_text(candidate) or [normalize_ticker(candidate)])
    return dedup_tickers([ticker for ticker in tickers if ticker])


def _positions_from_ui_context(ui_context: dict[str, Any]) -> list[dict[str, Any]]:
    """Return normalized visible portfolio positions without inventing holdings."""
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()

    for key in ("positions", "holdings", "portfolio"):
        value = ui_context.get(key)
        if isinstance(value, dict):
            iterable: list[Any] = []
            for raw_key, raw_value in value.items():
                if isinstance(raw_value, dict):
                    item = dict(raw_value)
                    item.setdefault("ticker", raw_key)
                    iterable.append(item)
                else:
                    iterable.append({"ticker": raw_key, "weight": raw_value})
        elif isinstance(value, (list, tuple)):
            iterable = list(value)
        else:
            continue

        for item in iterable:
            if isinstance(item, dict):
                ticker = normalize_ticker(str(item.get("ticker") or item.get("symbol") or item.get("asset") or item.get("id") or ""))
                if not ticker or ticker in seen:
                    continue
                normalized = dict(item)
                normalized["ticker"] = ticker
                rows.append(normalized)
                seen.add(ticker)
            elif isinstance(item, str):
                ticker = normalize_ticker(item)
                if ticker and ticker not in seen:
                    rows.append({"ticker": ticker})
                    seen.add(ticker)
    return rows


def _holdings_portfolio_context_available(
    query: str,
    ui_context: dict[str, Any],
    tickers: list[str],
) -> bool:
    if _portfolio_context_available(query, ui_context):
        return True
    lowered = str(query or "").lower()
    if tickers and ("我的" in query or "my " in lowered) and _contains_any(query, ("组合", "portfolio")):
        return True
    return False


def _add_holdings_intent_tasks(
    tasks: list[dict[str, Any]],
    *,
    query: str,
    tickers: list[str],
    ui_context: dict[str, Any],
) -> bool:
    if not _has_holdings_intent(query):
        return False

    params = _holdings_intent_params(query)
    operation = _operation("holdings", 0.84, params)
    if _holdings_portfolio_context_available(query, ui_context, tickers):
        portfolio_tickers = tickers or _portfolio_tickers_from_context(ui_context)
        _add_task(
            tasks,
            subject_type="portfolio",
            subject_label="当前组合",
            operation=operation,
            query=query,
            tickers=portfolio_tickers,
            priority=18,
            reason="holdings_intent_portfolio",
            params={**params, "positions": _positions_from_ui_context(ui_context)},
        )
        return True

    if tickers:
        for ticker in tickers[:6]:
            _add_task(
                tasks,
                subject_type=_subject_type_for_ticker(ticker),
                subject_label=ticker,
                operation=operation,
                query=query,
                tickers=[ticker],
                priority=20,
                reason="holdings_intent_company",
                params=params,
            )
        return True

    holder = params.get("holder_cik_or_name")
    if holder:
        _add_task(
            tasks,
            subject_type="company",
            subject_label=str(holder),
            operation=operation,
            query=query,
            tickers=[],
            priority=20,
            reason="holdings_intent_institution",
            params=params,
        )
        return True

    return False


def _binding_context_ref(binding: Any, *, value: Any = "") -> dict[str, Any]:
    return {
        "source": "conversation_context",
        "key": getattr(binding, "source", "none"),
        "label": getattr(binding, "subject_hint", "") or getattr(binding, "source", "conversation_context"),
        "value": value or getattr(binding, "reason", ""),
    }


def _context_tickers_from_binding(
    *,
    binding: Any,
    ui_context: dict[str, Any],
    memory_context: dict[str, Any],
) -> list[str]:
    source = str(getattr(binding, "source", "") or "")
    candidates: list[str] = []
    subject_hint = str(getattr(binding, "subject_hint", "") or "")
    if subject_hint:
        candidates.append(subject_hint)

    if source == "active_symbol":
        candidates.append(str(ui_context.get("active_symbol") or ""))
    elif source == "last_report":
        report = current_report_context(memory_context) or {}
        candidates.append(str(report.get("ticker") or ""))
        candidates.append(str(report.get("title") or ""))

    tickers: list[str] = []
    for candidate in candidates:
        if not candidate.strip():
            continue
        extracted = _extract_tickers_from_text(candidate)
        tickers.extend(extracted or [normalize_ticker(candidate)])
    return dedup_tickers([ticker for ticker in tickers if re.match(r"^[A-Z0-9^][A-Z0-9.\-=]{0,14}$", ticker)])


def _add_context_bound_research_task(
    *,
    tasks: list[dict[str, Any]],
    context_refs: list[dict[str, Any]],
    decision: ConversationDecision,
    query: str,
    ui_context: dict[str, Any],
    memory_context: dict[str, Any],
    current_tickers: list[str] | None,
    selection_ids: list[str],
    selection_types: list[str],
) -> bool:
    """Map a contextual router decision into executable work.

    The switch is by context source, not by bespoke follow-up kind. A follow-up
    can bind to a report, active symbol, selected document, portfolio, or recent
    focus while still sharing one route schema.
    """
    binding = decision.context_binding
    source = binding.source

    if source == "selection" and selection_ids:
        subject_type = _selection_subject_type(selection_types)
        if subject_type == "research_doc" and decision.domain_intent == "news":
            subject_type = "news_item" if len(selection_ids) == 1 else "news_set"
        operation_name = "summarize" if decision.relation == "summarize" else "qa"
        if decision.domain_intent in {"news", "analysis"} and decision.relation != "summarize":
            operation_name = "analyze_impact" if decision.needs_tools else "qa"
        params = {"context_binding": binding.model_dump()}
        urls = _selection_urls(ui_context)
        if len(urls) == 1:
            params["url"] = urls[0]
        elif len(urls) > 1:
            params["urls"] = urls
        selection_tickers = dedup_tickers(list(current_tickers or []))
        if not selection_tickers and isinstance(ui_context.get("active_symbol"), str):
            active = normalize_ticker(str(ui_context.get("active_symbol") or ""))
            if active:
                selection_tickers = [active]
        _add_task(
            tasks,
            subject_type=subject_type,
            operation=_operation(operation_name, decision.confidence, params),
            query=query,
            tickers=selection_tickers,
            selection_ids=selection_ids,
            selection_types=selection_types,
            priority=15,
            reason="context_router_binding",
            params=params,
        )
        context_refs.append(_binding_context_ref(binding, value=selection_ids))
        return True

    if source == "portfolio":
        portfolio_tickers = _portfolio_tickers_from_context(ui_context)
        positions = _positions_from_ui_context(ui_context)
        if portfolio_tickers or _portfolio_context_available(query, ui_context):
            _add_task(
                tasks,
                subject_type="portfolio",
                subject_label="当前持仓",
                operation=_domain_intent_operation(decision.domain_intent, decision.confidence),
                query=query,
                tickers=portfolio_tickers,
                priority=20,
                reason="context_router_binding",
                params={"context_binding": binding.model_dump(), "positions": positions},
            )
            context_refs.append(_binding_context_ref(binding, value=portfolio_tickers or "portfolio"))
            return True
        return False

    tickers = _context_tickers_from_binding(
        binding=binding,
        ui_context=ui_context,
        memory_context=memory_context,
    )
    if tickers:
        for ticker in tickers[:3]:
            _add_task(
                tasks,
                subject_type=_subject_type_for_ticker(ticker),
                operation=_domain_intent_operation(decision.domain_intent, decision.confidence),
                query=query,
                tickers=[ticker],
                subject_label=ticker,
                priority=25,
                reason="context_router_binding",
                params={"context_binding": binding.model_dump()},
            )
        context_refs.append(_binding_context_ref(binding, value=tickers))
        return True

    return False


async def _emit_understanding_trace(understanding: dict[str, Any]) -> None:
    await emit_event(
        {
            "type": "trace",
            "visibility": "user",
            "stage": "understanding",
            "status": "done",
            "title": "已理解请求",
            "summary": understanding.get("user_visible_summary") or "",
            "tasks": [
                {
                    "id": task.get("id"),
                    "subject_type": task.get("subject_type"),
                    "tickers": task.get("tickers") or [],
                    "operation": (task.get("operation") or {}).get("name"),
                    "time_scope": (task.get("time_scope") or {}).get("kind"),
                }
                for task in (understanding.get("tasks") or [])[:8]
            ],
            "blocked_tasks": [
                {"id": task.get("id"), "reason": task.get("reason")}
                for task in (understanding.get("blocked_tasks") or [])[:4]
            ],
        }
    )


async def understand_request(state: GraphState) -> dict[str, Any]:
    query = (state.get("query") or "").strip()
    ui_context = dict(state.get("ui_context") or {}) if isinstance(state.get("ui_context"), dict) else {}
    output_mode = (decide_output_mode(state).get("output_mode") or "chat")

    tasks: list[dict[str, Any]] = []
    blocked_tasks: list[dict[str, Any]] = []
    context_refs: list[dict[str, Any]] = []
    fallback_assumptions: list[str] = []
    memory_context = state.get("memory_context") if isinstance(state.get("memory_context"), dict) else {}
    artifacts = dict(state.get("artifacts") or {})
    state = {**state, "ui_context": ui_context, "artifacts": artifacts}
    trace = dict(state.get("trace") or {})
    selection_ids, selection_types, selection_payload = _normalize_selection(ui_context)
    social_prefix = _social_prefix(query)
    query_for_tickers = _strip_urls(query)
    ticker_meta = extract_tickers(query_for_tickers)
    tickers = dedup_tickers(
        [str(t) for t in (ticker_meta.get("tickers") or []) if str(t).strip().upper() not in _NON_ASSET_TOKENS]
    )
    conversation_decision: ConversationDecision | None = None
    intent_contract: dict[str, Any] | None = None
    intent_contracts: list[dict[str, Any]] = []
    context_router_research_bound = False

    if not query:
        blocked_tasks.append(
            {
                "id": "blocked_1",
                "subject_type": "unknown",
                "subject_label": "",
                "operation": _operation("qa", 0.0),
                "reason": "empty_query",
                "question": "请先输入你的问题。",
                "suggestions": ["输入股票代码、公司名称、宏观主题，或选择新闻/财报后提问"],
                "fallback_allowed": False,
            }
        )

    if query and not blocked_tasks and is_casual_chat(query):
        # Keep this local path only for obvious social turns. Broader open-chat
        # questions still go through the LLM router before planner.
        decision = ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(),
            relation="new_topic",
            domain_intent="smalltalk",
            confidence=1.0,
            needs_tools=False,
            reason="纯社交问候，直接回答",
        )
        result = _direct_conversation_result(
            query=query,
            output_mode=output_mode,
            decision=decision,
            reply=_direct_reply(query),
            context_refs=context_refs,
            artifacts=artifacts,
            trace=trace,
            memory_context=memory_context,
        )
        await _emit_understanding_trace(result["understanding"])
        return result

    if (
        query
        and not blocked_tasks
        and not _explicit_report_mode(state, output_mode)
        and (output_mode == "brief" or _is_explicit_brief_request(query) or bool(_extract_urls(query)))
        and tickers
        and not selection_ids
        and not _has_prior_dialogue(state, query)
    ):
        conversation_decision = ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(
                source="none",
                confidence=0.0,
                reason="brief turn has explicit current-turn subject and no prior context to bind",
                subject_hint=", ".join(tickers[:3]),
            ),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.72,
            needs_tools=True,
            reason="explicit brief request can be decomposed by request understanding without context binding",
        )
        trace["conversation_router"] = conversation_decision.model_dump()

    explicit_urls = _extract_urls(query)
    if (
        query
        and explicit_urls
        and not blocked_tasks
        and not _explicit_report_mode(state, output_mode)
        and conversation_decision is None
    ):
        conversation_decision = ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(
                source="none",
                confidence=0.0,
                reason="current user turn contains explicit URL(s), so the URL must be fetched before answering",
                subject_hint=explicit_urls[0],
            ),
            relation="new_topic",
            domain_intent="doc_qa",
            confidence=0.9,
            needs_tools=True,
            reason="explicit URL reference requires source-grounded document retrieval",
        )
        trace["conversation_router"] = conversation_decision.model_dump()

    if query and not blocked_tasks and not _explicit_report_mode(state, output_mode) and conversation_decision is None:
        conversation_decision = await route_conversation(state, tickers=tickers, selection_ids=selection_ids)
        if conversation_decision is not None:
            if tickers and conversation_decision.context_binding.source == "none":
                tickers = _effective_current_turn_tickers(query, tickers, conversation_decision)
            trace["conversation_router"] = conversation_decision.model_dump()
            if conversation_decision.execution_route in {"direct_answer", "out_of_scope"}:
                if _direct_decision_must_project_tasks(query, conversation_decision, current_tickers=tickers):
                    conversation_decision = _force_grounded_research_decision(conversation_decision)
                    trace["conversation_router"] = conversation_decision.model_dump()
                else:
                    direct_context_refs = list(context_refs)
                    binding = conversation_decision.context_binding
                    if binding.source != "none":
                        direct_context_refs.append(
                            {
                                "source": "conversation_context",
                                "key": binding.source,
                                "label": binding.subject_hint or binding.source,
                                "value": binding.reason,
                            }
                        )
                    reply = await generate_contextual_reply(state, conversation_decision)
                    result = _direct_conversation_result(
                        query=query,
                        output_mode=output_mode,
                        decision=conversation_decision,
                        reply=reply,
                        context_refs=direct_context_refs,
                        artifacts=artifacts,
                        trace=trace,
                        memory_context=memory_context,
                    )
                    await _emit_understanding_trace(result["understanding"])
                    return result
            if (
                conversation_decision.execution_route == "research"
            ):
                if conversation_decision.context_binding.source != "none":
                    context_router_research_bound = _add_context_bound_research_task(
                        tasks=tasks,
                        context_refs=context_refs,
                        decision=conversation_decision,
                        query=query,
                        ui_context=ui_context,
                        memory_context=memory_context,
                        current_tickers=tickers,
                        selection_ids=selection_ids,
                        selection_types=selection_types,
                    )
                if conversation_decision.task_hints:
                    hint_bound = _add_router_task_hints_contract(
                        tasks=tasks,
                        context_refs=context_refs,
                        decision=conversation_decision,
                        query=query,
                        output_mode=output_mode,
                        current_tickers=tickers,
                        selection_ids=selection_ids,
                        selection_types=selection_types,
                        intent_contracts=intent_contracts,
                    )
                    context_router_research_bound = context_router_research_bound or hint_bound
            if conversation_decision.execution_route == "clarify":
                blocked_tasks.append(_context_router_clarify_block(conversation_decision))
                tickers = []
                selection_ids = []

    context_binding_source = (
        conversation_decision.context_binding.source
        if conversation_decision is not None
        else "none"
    )

    if not blocked_tasks and context_binding_source != "selection":
        _add_explicit_url_tasks(tasks=tasks, query=query, current_tickers=tickers)

    if (
        not blocked_tasks
        and
        (not context_router_research_bound or context_binding_source == "selection")
        and not tickers
        and _can_use_active_symbol_fallback(ui_context, memory_context)
        and has_financial_intent(query)
    ):
        tickers = [normalize_ticker(str(ui_context["active_symbol"]))]
        context_refs.append({"source": "ui_context", "key": "active_symbol", "label": "当前标的", "value": tickers[0]})

    # P2 weak fallback — query lacks tickers AND lacks financial intent, but
    # contains a vague subject deixis ("这只票", "this stock", ...) and
    # ui_context.active_symbol is present. Bind the active symbol and surface
    # the assumption to the user so they can correct it in one turn.
    if (
        not blocked_tasks
        and
        (not context_router_research_bound or context_binding_source == "selection")
        and
        not tickers
        and _can_use_active_symbol_fallback(ui_context, memory_context)
        and _contains_any(query, _VAGUE_SUBJECT_HINTS)
        and (
            _contains_any(query, _ASSET_DEICTIC_HINTS)
            or has_financial_intent(query)
            or _contains_any(query, _NEWS_HINTS + _PRICE_HINTS + _IMPACT_HINTS + _TECHNICAL_HINTS)
        )
    ):
        active = normalize_ticker(str(ui_context["active_symbol"]))
        if active:
            tickers = [active]
            context_refs.append(
                {
                    "source": "ui_context",
                    "key": "active_symbol",
                    "label": "当前标的(弱兜底)",
                    "value": active,
                }
            )
            fallback_assumptions.append(
                f"按你正在看的 {active} 处理，如不是请告诉我具体哪只。"
            )

    holdings_intent_handled = False
    if not blocked_tasks and (not context_router_research_bound or context_binding_source == "selection"):
        holdings_intent_handled = _add_holdings_intent_tasks(
            tasks,
            query=query,
            tickers=tickers,
            ui_context=ui_context,
        )

    if not blocked_tasks and not context_router_research_bound and selection_ids and context_binding_source != "selection":
        selection_tickers = tickers
        if (
            not selection_tickers
            and isinstance(ui_context.get("active_symbol"), str)
            and ui_context["active_symbol"].strip()
        ):
            selection_tickers = [normalize_ticker(str(ui_context["active_symbol"]))]
        subject_type = _selection_subject_type(selection_types)
        parsed = parse_operation(
            {
                "query": query,
                "subject": {
                    "subject_type": subject_type,
                    "tickers": selection_tickers,
                    "selection_ids": selection_ids,
                    "selection_types": selection_types,
                },
            }
        )
        _add_task(
            tasks,
            subject_type=subject_type,
            operation=parsed.get("operation") or _operation("summarize", 0.65),
            query=query,
            tickers=selection_tickers,
            selection_ids=selection_ids,
            selection_types=selection_types,
            priority=10,
            reason="ui_selection",
        )

    if (
        not blocked_tasks
        and not holdings_intent_handled
        and (not context_router_research_bound or context_binding_source == "selection")
        and tickers
    ):
        report_tickers, report_peer_tickers = _split_primary_report_tickers(
            query,
            tickers,
            state=state,
            output_mode=output_mode,
        )
        scoped_tickers = report_tickers or tickers
        multi_ticker_report = len(scoped_tickers) >= 2 and _explicit_report_mode(state, output_mode)
        comparison_requested = (
            _explicit_multi_ticker_compare_requested(query)
            or (
                has_comparison_relation(query, scoped_tickers)
                and not _is_lightweight_representative_compare(query)
            )
        )
        multi_ticker_compare = len(scoped_tickers) >= 2 and (
            comparison_requested
            or multi_ticker_report
        )
        intent_contract = derive_intent_contract(
            query=query,
            tickers=scoped_tickers,
            output_mode=output_mode,
            comparison_requested=multi_ticker_compare,
            domain_intent=(conversation_decision.domain_intent if conversation_decision is not None else ""),
            lightweight_requested=_is_explicit_brief_request(query) or _is_lightweight_representative_compare(query),
            subject_type="company",
            frame_id="primary_company",
        )
        intent_contracts.append(dict(intent_contract))
        trace["intent_contract"] = intent_contract
        if multi_ticker_compare:
            contract_tickers = list(intent_contract.get("primary_tickers") or scoped_tickers)
            if requires_per_ticker_research(intent_contract):
                _add_task(
                    tasks,
                    subject_type="company",
                    operation=synthesis_compare_operation(intent_contract),
                    query=query,
                    tickers=contract_tickers,
                    priority=20,
                    reason="intent_contract_synthesis_compare",
                )
                _add_per_ticker_company_tasks(
                    tasks,
                    tickers=contract_tickers,
                    operations=[evidence_focused_operation(intent_contract)],
                    query=query,
                    priority=24,
                    reason="intent_contract_per_ticker_evidence",
                )
            else:
                _add_task(
                    tasks,
                    subject_type="company",
                    operation=_operation("compare", 0.86),
                    query=query,
                    tickers=contract_tickers,
                    priority=20,
                    reason="multi_ticker_report" if multi_ticker_report and not comparison_requested else "multi_ticker_compare",
                )
                extra_operations: list[dict[str, Any]] = []
                if _contains_any(query, _PRICE_HINTS) or multi_ticker_report:
                    extra_operations.append(_operation("price", 0.82))
                if _contains_any(query, _NEWS_HINTS) or multi_ticker_report:
                    extra_operations.append(_operation("fetch", 0.78, {"topic": "news"}))
                if (
                    _contains_any(query, _IMPACT_HINTS)
                    and (multi_ticker_report or len(tickers) == 1)
                    and not re.search(r"(哪个|谁).{0,8}(风险|risk)", query, re.IGNORECASE)
                ):
                    extra_operations.append(_operation("analyze_impact", 0.78))
                for ticker in contract_tickers:
                    subject_type = _subject_type_for_ticker(ticker)
                    for operation in extra_operations:
                        _add_task(
                            tasks,
                            subject_type=subject_type,
                            operation=operation,
                            query=query,
                            tickers=[ticker],
                            subject_label=ticker,
                            priority=26,
                            reason="compare_subtask",
                        )
        else:
            fallback_operations = _company_operations(
                query,
                tickers=scoped_tickers,
                allow_multi_ticker_default_compare=(
                    multi_ticker_report
                    or (
                        conversation_decision is not None
                        and conversation_decision.relation == "compare"
                    )
                ),
                output_mode=output_mode,
            )
            contract_operations = (
                [legacy_operation_for_contract(intent_contract, subject_type="company")]
                if intent_contract.get("required_evidence") and output_mode != "investment_report"
                else []
            )
            if contract_operations:
                contract_operation_names = {
                    str(operation.get("name") or "").strip()
                    for operation in contract_operations
                    if isinstance(operation, dict)
                }
                for operation in fallback_operations:
                    op_name = str((operation or {}).get("name") or "").strip()
                    if op_name == "alert_set" and op_name not in contract_operation_names:
                        contract_operations.append(operation)
                        contract_operation_names.add(op_name)
            router_operations = None if contract_operations else _router_directed_company_operations(
                conversation_decision,
                fallback_operations=fallback_operations,
            )
            operations = [
                _operation_with_report_peers(operation, report_peer_tickers)
                for operation in (contract_operations or router_operations or fallback_operations)
            ]
            if len(scoped_tickers) >= 2 and _is_lightweight_representative_compare(query):
                _add_task(
                    tasks,
                    subject_type="company",
                    operation=_operation("qa", 0.7),
                    query=query,
                    tickers=scoped_tickers,
                    subject_label=", ".join(scoped_tickers),
                    priority=25,
                    reason="representative_basket_qa",
                )
            elif (
                router_operations is None
                and len(scoped_tickers) >= 2
                and any((operation.get("name") or "") == "compare" for operation in operations)
            ):
                _add_task(
                    tasks,
                    subject_type="company",
                    operation=_operation("compare", 0.7),
                    query=query,
                    tickers=scoped_tickers,
                    priority=25,
                    reason="multi_ticker_operation",
                )
            else:
                _add_per_ticker_company_tasks(
                    tasks,
                    tickers=scoped_tickers,
                    operations=operations,
                    query=query,
                    priority=25,
                    reason=(
                        "primary_report_ticker"
                        if report_peer_tickers
                        else ("conversation_router_intent" if router_operations else "ticker_or_alias")
                    ),
                )

    has_macro = _contains_any(query, _MACRO_HINTS)
    if not blocked_tasks and not context_router_research_bound and has_macro:
        _add_task(
            tasks,
            subject_type="macro",
            subject_label=_macro_subject_label(query),
            operation=_macro_operation(query),
            query=query,
            priority=30,
            reason="macro_hint",
        )

    url_only_doc_turn = bool(explicit_urls) and not _query_requests_company_side_data(query)
    if (
        not blocked_tasks
        and not context_router_research_bound
        and _contains_any(query, _THEME_HINTS)
        and not has_macro
        and not tickers
        and not wants_no_news_or_links(query)
        and not url_only_doc_turn
    ):
        if not any(task.get("subject_type") == "theme" for task in tasks):
            _add_task(
                tasks,
                subject_type="theme",
                subject_label=conversation_decision.context_binding.subject_hint if conversation_decision else "主题/行业",
                operation=_operation("news_impact" if _contains_any(query, _IMPACT_HINTS) else "fetch", 0.7),
                query=query,
                priority=35,
                reason="theme_hint",
            )

    has_portfolio = _contains_any(query, _PORTFOLIO_HINTS)
    if not blocked_tasks and not holdings_intent_handled and not context_router_research_bound and has_portfolio:
        if _portfolio_context_available(query, ui_context):
            portfolio_tickers = tickers or _portfolio_tickers_from_context(ui_context)
            positions = _positions_from_ui_context(ui_context)
            _add_task(
                tasks,
                subject_type="portfolio",
                subject_label="当前持仓",
                operation=_operation("rebalance_check" if "调仓" in query else "portfolio_impact", 0.74),
                query=query,
                tickers=portfolio_tickers,
                priority=40,
                reason="portfolio_context_available",
                params={"positions": positions},
            )
        elif _contains_any(query, _FALLBACK_HINTS):
            fallback_assumptions.append("用户允许在缺少持仓明细时使用查询中的替代假设。")
            _add_task(
                tasks,
                subject_type="portfolio",
                subject_label="持仓替代假设",
                operation=_operation("portfolio_fallback", 0.58),
                query=query,
                tickers=tickers,
                priority=80,
                reason="user_allowed_fallback",
                params={"fallback": True},
            )
        else:
            blocked_tasks.append(
                {
                    "id": f"blocked_{len(blocked_tasks) + 1}",
                    "subject_type": "portfolio",
                    "subject_label": "我的持仓",
                    "operation": _operation("portfolio_impact", 0.0),
                    "reason": "missing_portfolio_holdings",
                    "question": "要判断持仓影响或调仓，需要你的持仓列表、权重或允许我按假设组合估算。",
                    "suggestions": ["补充持仓和大致权重", "或说明按等权科技股组合估算"],
                    "fallback_allowed": True,
                }
            )

    if not tasks and not blocked_tasks:
        if conversation_decision is None:
            conversation_decision = await route_conversation(state, tickers=tickers, selection_ids=selection_ids)
        if conversation_decision is not None:
            trace["conversation_router"] = conversation_decision.model_dump()
            if conversation_decision.execution_route in {"direct_answer", "out_of_scope"}:
                if _direct_decision_must_project_tasks(query, conversation_decision, current_tickers=tickers):
                    conversation_decision = _force_grounded_research_decision(conversation_decision)
                    trace["conversation_router"] = conversation_decision.model_dump()
                else:
                    direct_context_refs = list(context_refs)
                    binding = conversation_decision.context_binding
                    if binding.source != "none":
                        direct_context_refs.append(
                            {
                                "source": "conversation_context",
                                "key": binding.source,
                                "label": binding.subject_hint or binding.source,
                                "value": binding.reason,
                            }
                        )
                    reply = await generate_contextual_reply(state, conversation_decision)
                    result = _direct_conversation_result(
                        query=query,
                        output_mode=output_mode,
                        decision=conversation_decision,
                        reply=reply,
                        context_refs=direct_context_refs,
                        artifacts=artifacts,
                        trace=trace,
                        memory_context=memory_context,
                    )
                    await _emit_understanding_trace(result["understanding"])
                    return result
            if conversation_decision.execution_route == "research":
                if conversation_decision.task_hints:
                    hint_bound = _add_router_task_hints_contract(
                        tasks=tasks,
                        context_refs=context_refs,
                        decision=conversation_decision,
                        query=query,
                        output_mode=output_mode,
                        current_tickers=tickers,
                        selection_ids=selection_ids,
                        selection_types=selection_types,
                        intent_contracts=intent_contracts,
                    )
                    context_router_research_bound = context_router_research_bound or hint_bound
                if not tasks:
                    _add_context_bound_research_task(
                        tasks=tasks,
                        context_refs=context_refs,
                        decision=conversation_decision,
                        query=query,
                        ui_context=ui_context,
                        memory_context=memory_context,
                        current_tickers=tickers,
                        selection_ids=selection_ids,
                        selection_types=selection_types,
                    )
                if not tasks:
                    if conversation_decision.context_binding.source == "none":
                        _add_unbound_research_task(
                            tasks=tasks,
                            decision=conversation_decision,
                            query=query,
                        )
                    else:
                        blocked_tasks.append(
                            {
                                "id": "blocked_1",
                                "subject_type": "unknown",
                                "subject_label": conversation_decision.context_binding.subject_hint,
                                "operation": _domain_intent_operation(
                                    conversation_decision.domain_intent,
                                    conversation_decision.confidence,
                                ),
                                "reason": "context_binding_unresolved",
                                "question": conversation_decision.reply_guidance
                                or "我理解这是接着上下文问，但还不能确定要绑定哪个对象。",
                                "suggestions": ["补充具体公司、股票代码、选中文档、持仓，或说明你指的是哪份报告"],
                                "fallback_allowed": False,
                            }
                        )
            if not tasks and conversation_decision.execution_route == "clarify":
                blocked_tasks.append(
                    {
                        "id": "blocked_1",
                        "subject_type": "unknown",
                        "subject_label": conversation_decision.context_binding.subject_hint,
                        "operation": _operation("qa", 0.0),
                        "reason": "context_router_clarify",
                        "question": conversation_decision.reply_guidance or "我需要你补充想看的对象或上下文。",
                        "suggestions": ["补充公司、股票代码、宏观主题、持仓，或说明你指的是哪条消息/哪份报告"],
                        "fallback_allowed": False,
                    }
                )

    tasks = _prune_url_only_company_context_tasks(tasks, query=query, explicit_urls=explicit_urls)

    if (
        not tasks
        and not blocked_tasks
        and conversation_decision is None
        and _history_tickers_from_messages(state, query)
    ):
        history_tickers = _history_tickers_from_messages(state, query)
        conversation_decision = ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(
                source="last_turn",
                confidence=0.62,
                reason="same-thread history provides the subject while router is unavailable",
                subject_hint=", ".join(history_tickers[:3]),
            ),
            relation="follow_up",
            domain_intent="analysis",
            confidence=0.58,
            needs_tools=False,
            reason="deterministic same-thread direct fallback without tools",
        )
        trace["conversation_router"] = conversation_decision.model_dump()
        reply = await generate_contextual_reply(state, conversation_decision)
        result = _direct_conversation_result(
            query=query,
            output_mode=output_mode,
            decision=conversation_decision,
            reply=reply,
            context_refs=[*context_refs, _binding_context_ref(conversation_decision.context_binding)],
            artifacts=artifacts,
            trace=trace,
            memory_context=memory_context,
        )
        await _emit_understanding_trace(result["understanding"])
        return result

    if (
        not tasks
        and not blocked_tasks
        and conversation_decision is None
        and _query_can_fallback_to_direct_finance_answer(query)
    ):
        conversation_decision = ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(source="none", confidence=0.0),
            relation="new_topic",
            domain_intent="finance_concept",
            confidence=0.58,
            needs_tools=False,
            reason="deterministic finance concept fallback without tools",
        )
        trace["conversation_router"] = conversation_decision.model_dump()
        reply = await generate_contextual_reply(state, conversation_decision)
        result = _direct_conversation_result(
            query=query,
            output_mode=output_mode,
            decision=conversation_decision,
            reply=reply,
            context_refs=list(context_refs),
            artifacts=artifacts,
            trace=trace,
            memory_context=memory_context,
        )
        await _emit_understanding_trace(result["understanding"])
        return result

    has_alert_task = any((task.get("operation") or {}).get("name") == "alert_set" for task in tasks)
    pending_research_after_alert = has_alert_task and any(
        (task.get("operation") or {}).get("name") != "alert_set" for task in tasks
    )

    if not tasks and blocked_tasks:
        route = "clarify"
    elif tasks and has_alert_task and (pending_research_after_alert or all((task.get("operation") or {}).get("name") == "alert_set" for task in tasks)):
        route = "alert"
    elif tasks:
        route = "research"
    else:
        route = "clarify"
        blocked_tasks.append(
            {
                "id": "blocked_1",
                "subject_type": "unknown",
                "subject_label": "",
                "operation": _operation("qa", 0.0),
                "reason": "missing_analysis_target",
                "question": "我需要知道你想分析的公司、股票、宏观主题、新闻、财报或持仓。",
                "suggestions": ["输入公司名或 ticker，例如 谷歌 / GOOGL", "输入宏观主题，例如 美联储利率路径"],
                "fallback_allowed": False,
            }
        )

    if blocked_tasks:
        _sanitize_blocked_task_questions(query, blocked_tasks)

    if route == "clarify":
        first_blocked = blocked_tasks[0] if blocked_tasks else {}
        suggestions = list(first_blocked.get("suggestions") or [])
        question = str(first_blocked.get("question") or "请补充分析对象。")
        if conversation_decision is not None and conversation_decision.execution_route == "clarify":
            suggestions = suggestions[:2]
        if suggestions:
            artifacts["draft_markdown"] = "\n".join([question, "", "可以补充：", *[f"- {s}" for s in suggestions]]).strip()
        else:
            artifacts["draft_markdown"] = question

    if _is_explicit_brief_request(query):
        output_mode = "brief"

    if intent_contract is None and intent_contracts:
        intent_contract = intent_contracts[0]

    reply_contract = build_reply_contract(
        query=query,
        output_mode=output_mode,
        tasks=tasks,
        blocked_tasks=blocked_tasks,
        conversation_decision=conversation_decision,
        memory_context=memory_context,
    )
    _apply_reply_contract_to_tasks(tasks, reply_contract)
    reply_contract = build_reply_contract(
        query=query,
        output_mode=output_mode,
        tasks=tasks,
        blocked_tasks=blocked_tasks,
        conversation_decision=conversation_decision,
        memory_context=memory_context,
    )

    primary = tasks[0] if tasks else None
    operation = (primary or {}).get("operation") or _operation("qa", 0.0)
    subject = _build_subject(primary, selection_payload, tasks)
    clarify = {
        "needed": route == "clarify",
        "reason": str((blocked_tasks[0] if blocked_tasks else {}).get("reason") or ""),
        "question": str((blocked_tasks[0] if blocked_tasks else {}).get("question") or ""),
        "suggestions": list((blocked_tasks[0] if blocked_tasks else {}).get("suggestions") or []),
    }
    summary_bits = []
    if tasks:
        for task in tasks[:5]:
            op_name = (task.get("operation") or {}).get("name")
            subject_label = task.get("subject_label") or ",".join(task.get("tickers") or []) or task.get("subject_type")
            summary_bits.append(f"{subject_label}:{op_name}")
    if blocked_tasks:
        summary_bits.append(f"阻塞项:{len(blocked_tasks)}")
    user_visible_summary = "；".join(summary_bits) if summary_bits else "需要补充信息。"

    understanding = {
        "route": route,
        "original_query": query,
        "cleaned_query": query,
        "language": "zh" if re.search(r"[\u4e00-\u9fff]", query) else "en",
        "social_prefix": social_prefix,
        "user_visible_summary": user_visible_summary,
        "confidence": 0.78 if tasks else 0.42,
        "tasks": tasks,
        "blocked_tasks": blocked_tasks,
        "context_refs": context_refs,
        "fallback_assumptions": fallback_assumptions,
    }
    understanding_v2_mode = str(os.getenv("FINSIGHT_UNDERSTANDING_V2_MODE") or "shadow").strip().lower()
    understanding_v2 = {}
    if understanding_v2_mode != "off":
        understanding_v2 = build_understanding_v2(
            query=query,
            output_mode=output_mode,
            tasks=tasks,
            blocked_tasks=blocked_tasks,
            subject=subject,
            operation=operation,
            reply_contract=reply_contract,
            context_refs=context_refs,
            fallback_assumptions=fallback_assumptions,
        )
        understanding["v2"] = understanding_v2
    trace["understanding"] = understanding
    if intent_contract is not None:
        trace["intent_contract"] = intent_contract
    if intent_contracts:
        trace["intent_contracts"] = intent_contracts
    if understanding_v2:
        trace["understanding_v2"] = understanding_v2
    trace["reply_contract"] = reply_contract
    await _emit_understanding_trace(understanding)

    result = {
        "understanding": understanding,
        "understanding_v2": understanding_v2,
        "reply_contract": reply_contract,
        "tasks": tasks,
        "blocked_tasks": blocked_tasks,
        "context_refs": context_refs,
        "subject": subject,
        "operation": operation,
        "output_mode": output_mode,
        "clarify": clarify,
        "chat_responded": route == "direct",
        "pending_research_after_alert": pending_research_after_alert,
        "artifacts": artifacts,
        "trace": trace,
    }
    if intent_contract is not None:
        result["intent_contract"] = intent_contract
    if intent_contracts:
        result["intent_contracts"] = intent_contracts
    return result


__all__ = ["understand_request"]

# -*- coding: utf-8 -*-
"""Contextual conversation routing for the LangGraph chat entry.

The router separates three questions that were previously conflated:

1. Which execution path should this turn take?
2. Which prior context, if any, is the user referring to?
3. What domain action does the user want now?

This keeps follow-up handling generic. A report, an active ticker, a selected
document, the last assistant answer, and an unresolved clarification are all
possible context bindings; none of them gets a bespoke route function.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, replace
from typing import Any, Literal

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend.config.ticker_mapping import extract_tickers
from backend.graph.json_utils import json_dumps_safe
from backend.graph.request_task_contract import query_explicitly_requests_sources, wants_no_news_or_links
from backend.graph.state import GraphState

logger = logging.getLogger(__name__)

_IMPLICIT_HISTORY_SOURCES: set[str] = {"last_turn", "recent_focus", "unresolved_clarification"}
_INHERITED_CONTEXT_SOURCES: set[str] = {"none", "last_turn", "last_report", "active_symbol", "recent_focus", "unresolved_clarification"}
_GLOBAL_CHAT_VIEWS: set[str] = {"chat", "main", "global", "conversation"}
_TASK_HINT_SUBJECT_TYPES: set[str] = {
    "company",
    "index",
    "crypto",
    "fund",
    "macro",
    "theme",
    "portfolio",
    "research_doc",
    "news_item",
    "unknown",
}
_TASK_HINT_OPERATIONS: set[str] = {
    "price",
    "fetch",
    "technical",
    "analyze_impact",
    "news_impact",
    "qa",
    "compare",
    "portfolio_impact",
    "rebalance_check",
    "alert_set",
    "macro_brief",
    "fact_check",
}
_STRUCTURAL_DEIXIS_RE = re.compile(
    r"("
    r"第二|第[一二三四五六七八九十0-9]+|继续|展开|上面|刚才|上一条|前面|那它|它"
    r"|\b(?:this|that|its)\b"
    r"|\b(?:do|does|did|can|could|would|will|should|is|was|were|has|have|had)\s+it\b"
    r"|\bit\s+(?:mean|means|imply|implies|change|changes|affect|affects|impact|impacts|matter|matters)\b"
    r")",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://[^\s<>\]\)\"']+", re.IGNORECASE)
ExecutionRoute = Literal["direct_answer", "research", "alert", "clarify", "out_of_scope"]
ContextSource = Literal[
    "none",
    "last_turn",
    "last_report",
    "active_symbol",
    "selection",
    "portfolio",
    "recent_focus",
    "unresolved_clarification",
]
Relation = Literal[
    "new_topic",
    "follow_up",
    "elaborate",
    "compare",
    "correct",
    "apply_constraint",
    "continue_previous",
    "summarize",
]
DomainIntent = Literal[
    "smalltalk",
    "finance_concept",
    "quote",
    "news",
    "analysis",
    "report_discussion",
    "doc_qa",
    "portfolio",
    "alert",
    "unknown",
]


@dataclass(frozen=True)
class ContextBinding:
    source: ContextSource = "none"
    confidence: float = 0.0
    reason: str = ""
    subject_hint: str = ""

    def model_dump(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "confidence": self.confidence,
            "reason": self.reason,
            "subject_hint": self.subject_hint,
        }


@dataclass(frozen=True)
class ConversationDecision:
    execution_route: ExecutionRoute
    context_binding: ContextBinding
    relation: Relation = "new_topic"
    domain_intent: DomainIntent = "unknown"
    confidence: float = 0.0
    needs_tools: bool = False
    reason: str = ""
    reply_guidance: str = ""
    task_hints: tuple[dict[str, Any], ...] = ()

    def model_dump(self) -> dict[str, Any]:
        return {
            "execution_route": self.execution_route,
            "context_binding": self.context_binding.model_dump(),
            "relation": self.relation,
            "domain_intent": self.domain_intent,
            "confidence": self.confidence,
            "needs_tools": self.needs_tools,
            "reason": self.reason,
            "reply_guidance": self.reply_guidance,
            "task_hints": [dict(item) for item in self.task_hints],
        }


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(str(raw).strip())
    except Exception:
        return default


def _coerce_confidence(value: Any, default: float = 0.0) -> float:
    try:
        confidence = float(value)
    except Exception:
        confidence = default
    if confidence > 1:
        confidence = confidence / 100.0
    return max(0.0, min(1.0, confidence))


def _query_explicitly_requests_grounding(query: str) -> bool:
    text = str(query or "")
    if wants_no_news_or_links(text):
        return False
    lowered = text.lower()
    return (
        bool(_URL_RE.search(text))
        or query_explicitly_requests_sources(text)
        or bool(re.search(r"\b(?:what|which)\s+(?:is\s+)?(?:the\s+)?(?:current\s+)?(?:price|quote)\b", lowered))
        or bool(re.search(r"\bhow\s+much\s+(?:is|are)\b", lowered))
        or any(
            token in lowered
            for token in (
                "url",
                "urls",
                "headline",
                "headlines",
                "news",
                "latest",
                "quote",
                "price now",
                "stock price",
                "trading at",
            )
        )
    )


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object found")
    parsed = json.loads(text[start : end + 1])
    if not isinstance(parsed, dict):
        raise ValueError("router output is not an object")
    return parsed


def _coerce_literal(value: Any, allowed: set[str], default: str) -> str:
    text = str(value or "").strip().lower()
    return text if text in allowed else default


def _coerce_task_hints(raw: Any) -> tuple[dict[str, Any], ...]:
    rows = raw if isinstance(raw, list) else []
    hints: list[dict[str, Any]] = []
    for row in rows[:8]:
        if not isinstance(row, dict):
            continue
        subject_label = str(row.get("subject_label") or row.get("subject_hint") or row.get("label") or "").strip()[:160]
        raw_tickers = row.get("tickers")
        tickers: list[str] = []
        if isinstance(raw_tickers, list):
            tickers.extend(str(item).strip().upper() for item in raw_tickers if str(item).strip())
        if subject_label:
            tickers.extend(str(item).strip().upper() for item in (extract_tickers(subject_label).get("tickers") or []))
        deduped_tickers = _dedupe_preserve_order([ticker for ticker in tickers if ticker])
        params = row.get("params") if isinstance(row.get("params"), dict) else {}
        operation = _coerce_literal(row.get("operation"), _TASK_HINT_OPERATIONS, "qa")
        hint_text = " ".join(
            str(part or "")
            for part in (
                subject_label,
                row.get("reason"),
                params.get("topic"),
                params.get("type"),
                params.get("intent"),
            )
        ).lower()
        if operation == "qa" and any(token in hint_text for token in ("新闻", "消息", "headline", "latest news", "news")):
            operation = "fetch"
            params = {**params, "topic": params.get("topic") or "news"}
        elif operation == "qa" and any(token in hint_text for token in ("价格", "股价", "price", "quote")):
            operation = "price"
        hints.append(
            {
                "subject_type": _coerce_literal(row.get("subject_type"), _TASK_HINT_SUBJECT_TYPES, "unknown"),
                "subject_label": subject_label,
                "tickers": deduped_tickers[:6],
                "operation": operation,
                "params": params,
                "reason": str(row.get("reason") or "")[:240],
            }
        )
    return tuple(hints)


def _coerce_decision(payload: dict[str, Any]) -> ConversationDecision:
    execution_route = _coerce_literal(
        payload.get("execution_route") or payload.get("route"),
        {"direct_answer", "research", "alert", "clarify", "out_of_scope"},
        "clarify",
    )
    relation = _coerce_literal(
        payload.get("relation"),
        {"new_topic", "follow_up", "elaborate", "compare", "correct", "apply_constraint", "continue_previous", "summarize"},
        "new_topic",
    )
    domain_intent = _coerce_literal(
        payload.get("domain_intent"),
        {"smalltalk", "finance_concept", "quote", "news", "analysis", "report_discussion", "doc_qa", "portfolio", "alert", "unknown"},
        "unknown",
    )
    raw_binding = payload.get("context_binding")
    binding = raw_binding if isinstance(raw_binding, dict) else {}
    source = _coerce_literal(
        binding.get("source"),
        {"none", "last_turn", "last_report", "active_symbol", "selection", "portfolio", "recent_focus", "unresolved_clarification"},
        "none",
    )
    context_binding = ContextBinding(
        source=source,  # type: ignore[arg-type]
        confidence=_coerce_confidence(binding.get("confidence"), default=0.0),
        reason=str(binding.get("reason") or "")[:240],
        subject_hint=str(binding.get("subject_hint") or "")[:160],
    )

    if relation == "new_topic" and source in {"last_turn", "last_report", "recent_focus", "unresolved_clarification"}:
        # A new topic should not inherit stale conversational focus. Keep
        # explicit UI anchors (selection / active_symbol / portfolio) because
        # those are user-visible context, not implicit history.
        context_binding = ContextBinding(
            source="none",
            confidence=0.0,
            reason="new_topic does not bind implicit conversation history",
            subject_hint="",
        )

    return ConversationDecision(
        execution_route=execution_route,  # type: ignore[arg-type]
        context_binding=context_binding,
        relation=relation,  # type: ignore[arg-type]
        domain_intent=domain_intent,  # type: ignore[arg-type]
        confidence=_coerce_confidence(payload.get("confidence"), default=0.0),
        needs_tools=bool(payload.get("needs_tools")),
        reason=str(payload.get("reason") or "")[:240],
        reply_guidance=str(payload.get("reply_guidance") or "")[:800],
        task_hints=_coerce_task_hints(payload.get("task_hints")),
    )


def _bound_context_is_resolved(
    *,
    source: ContextSource,
    binding: ContextBinding,
    ui_context: dict[str, Any],
    memory_context: dict[str, Any],
    recent_history: list[dict[str, str]],
    selection_ids: list[str],
) -> bool:
    """Whether a non-none context binding is concrete enough to continue.

    A clarification is only valid when the missing piece is the conversation
    anchor itself. Once the router has a concrete anchor, the answer layer can
    decide whether to calculate, explain, rewrite, or ask a narrower follow-up
    without losing the already-resolved subject.
    """
    if source in {"none", "unresolved_clarification"}:
        return False
    if source == "selection":
        return bool(selection_ids or _selection_summary(ui_context))
    if source == "portfolio":
        return _has_portfolio_context(ui_context) or bool(binding.subject_hint)
    if source == "last_report":
        return bool(_compact_last_report(memory_context) or binding.subject_hint)
    if source == "active_symbol":
        active_symbol = ui_context.get("active_symbol")
        return bool(binding.subject_hint or (isinstance(active_symbol, str) and active_symbol.strip()))
    if source in {"last_turn", "recent_focus"}:
        return bool(recent_history and binding.subject_hint)
    return bool(binding.subject_hint)


def _task_hints_require_execution(task_hints: tuple[dict[str, Any], ...]) -> bool:
    for hint in task_hints:
        if not isinstance(hint, dict):
            continue
        operation = str(hint.get("operation") or "").strip().lower()
        if operation in {"alert_set", "portfolio_impact", "rebalance_check"}:
            return True
    return False


def _research_decision_can_answer_as_chat(decision: ConversationDecision, query: str) -> bool:
    """Whether a router research decision is actually an ordinary chat answer.

    The LLM router owns the semantic read of the turn, but execution has a hard
    product boundary: only explicit evidence/data/tool requests should enter the
    grounded lane. This guard keeps generic mechanism explanations from being
    promoted into search because a finance term also happens to be a tradable
    subject.
    """
    if decision.execution_route != "research":
        return False
    if decision.domain_intent not in {"analysis", "finance_concept"}:
        return False
    if _query_explicitly_requests_grounding(query):
        return False
    if _task_hints_require_execution(decision.task_hints):
        return False
    return True


def normalize_context_decision(
    decision: ConversationDecision,
    state: GraphState,
    *,
    tickers: list[str],
    selection_ids: list[str],
) -> ConversationDecision:
    """Resolve conflicts between LLM-selected context and explicit user state.

    The LLM decides intent and likely binding. This deterministic pass only
    fixes source precedence: current-turn subjects and visible UI anchors are
    more reliable than implicit historical focus. It deliberately does not
    classify follow-up types by keywords.
    """
    binding = decision.context_binding
    source = binding.source
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    memory_context = state.get("memory_context") if isinstance(state.get("memory_context"), dict) else {}
    recent_history = _recent_history(state)
    query = str(state.get("query") or "").strip()
    has_thread_history = bool(recent_history)

    if decision.relation == "new_topic" and source in {
        "last_turn",
        "recent_focus",
        "unresolved_clarification",
    }:
        return replace(
            decision,
            context_binding=ContextBinding(
                source="none",
                confidence=0.0,
                reason="new_topic does not bind implicit conversation history",
                subject_hint="",
            ),
        )

    can_downgrade_unbound_research = (
        decision.relation == "new_topic"
        or (
            decision.relation == "elaborate"
            and source == "none"
            and not _STRUCTURAL_DEIXIS_RE.search(query)
        )
    )
    if (
        _research_decision_can_answer_as_chat(decision, query)
        and can_downgrade_unbound_research
        and not tickers
        and source not in {"selection", "portfolio"}
    ):
        return replace(
            decision,
            execution_route="direct_answer",
            needs_tools=False,
            task_hints=(),
            confidence=max(decision.confidence, 0.72),
            reason=decision.reason
            or "ordinary financial explanation does not require current data, sources, URL reading, or tools",
            reply_guidance=decision.reply_guidance
            or "Answer naturally from financial reasoning; do not fetch news, links, quotes, or sources unless the user asks for them.",
        )

    if (
        tickers
        and decision.execution_route == "research"
        and decision.relation != "new_topic"
        and decision.domain_intent == "analysis"
        and has_thread_history
        and source in {"none", *_IMPLICIT_HISTORY_SOURCES}
        and _STRUCTURAL_DEIXIS_RE.search(query)
    ):
        effective_tickers = _effective_current_turn_tickers(query, tickers, decision)
        return replace(
            decision,
            execution_route="direct_answer",
            context_binding=ContextBinding(
                source="last_turn",
                confidence=max(binding.confidence, 0.72),
                reason="current turn names the subject, while the analytical follow-up depends on the same-thread context",
                subject_hint=", ".join(effective_tickers[:3] or tickers[:3]),
            ),
            needs_tools=False,
            confidence=max(decision.confidence, 0.72),
        )

    if (
        tickers
        and not selection_ids
        and decision.execution_route == "research"
        and decision.domain_intent in {"analysis", "finance_concept"}
        and source in {"none", *_IMPLICIT_HISTORY_SOURCES}
        and not _query_explicitly_requests_grounding(query)
        and not _has_portfolio_context(ui_context)
    ):
        effective_tickers = _effective_current_turn_tickers(query, tickers, decision)
        label = ", ".join(effective_tickers[:3] or tickers[:3])
        return replace(
            decision,
            execution_route="direct_answer",
            context_binding=ContextBinding(
                source="none",
                confidence=0.0,
                reason="explicit ticker analysis did not ask for current data, links, sources, URL reading, or report mode",
                subject_hint=label,
            ),
            needs_tools=False,
            task_hints=(),
            confidence=max(decision.confidence, 0.74),
            reply_guidance=decision.reply_guidance
            or "Answer naturally from financial reasoning; do not run evidence tools unless current data or sources are requested.",
        )

    if tickers and source not in {"portfolio", "selection"}:
        effective_tickers = _effective_current_turn_tickers(query, tickers, decision)
        if decision.relation == "correct":
            label = ", ".join(effective_tickers[:3] or tickers[:3])
            if _query_explicitly_requests_grounding(query) or decision.domain_intent in {"quote", "news", "doc_qa"}:
                return replace(
                    decision,
                    execution_route="research",
                    context_binding=ContextBinding(
                        source="none",
                        confidence=0.0,
                        reason="current user turn corrects the subject but still asks for grounded data",
                        subject_hint=label,
                    ),
                    confidence=max(decision.confidence, 0.74),
                    needs_tools=True,
                )
            return replace(
                decision,
                execution_route="direct_answer",
                context_binding=ContextBinding(
                    source="none",
                    confidence=0.0,
                    reason="current user turn explicitly corrects the subject",
                    subject_hint=label,
                ),
                confidence=max(decision.confidence, 0.74),
                needs_tools=False,
                reply_guidance=f"确认改按 {label} 处理，不沿用被纠正的标的。",
            )
        return replace(
            decision,
            context_binding=ContextBinding(
                source="none",
                confidence=0.0,
                reason="current user turn contains explicit subject(s), so implicit history was ignored",
                subject_hint=", ".join(effective_tickers[:3] or tickers[:3]),
            ),
        )

    if selection_ids and source in _INHERITED_CONTEXT_SOURCES:
        return replace(
            decision,
            context_binding=ContextBinding(
                source="selection",
                confidence=max(binding.confidence, 0.72),
                reason="current UI selection is more explicit than implicit conversation history",
                subject_hint=", ".join(selection_ids[:3]),
            ),
        )

    if (
        not tickers
        and not selection_ids
        and source == "recent_focus"
        and has_thread_history
        and decision.relation != "new_topic"
        and _STRUCTURAL_DEIXIS_RE.search(query)
    ):
        last_tickers = _last_user_history_tickers(recent_history)
        return replace(
            decision,
            context_binding=ContextBinding(
                source="last_turn",
                confidence=max(binding.confidence, 0.76),
                reason="same-session last turn is stronger than user-level recent focus for deictic follow-ups",
                subject_hint=", ".join(last_tickers) or binding.subject_hint,
            ),
            confidence=max(decision.confidence, 0.72),
        )

    portfolio_context_present = _has_portfolio_context(ui_context)
    portfolio_hint_present = any(
        isinstance(hint, dict)
        and (
            str(hint.get("subject_type") or "").strip().lower() == "portfolio"
            or str(hint.get("operation") or "").strip().lower() in {"portfolio_impact", "rebalance_check"}
        )
        for hint in decision.task_hints
    )
    if portfolio_context_present and source == "portfolio":
        return replace(
            decision,
            execution_route="research",
            context_binding=ContextBinding(
                source="portfolio",
                confidence=max(binding.confidence, 0.74),
                reason=binding.reason or "visible portfolio context is available for this turn",
                subject_hint=binding.subject_hint or "current portfolio",
            ),
            domain_intent="portfolio" if decision.domain_intent == "unknown" or portfolio_hint_present else decision.domain_intent,
            confidence=max(decision.confidence, 0.72),
            needs_tools=True,
        )

    if (
        not tickers
        and source in {"none", *_IMPLICIT_HISTORY_SOURCES}
        and (
            decision.domain_intent == "portfolio"
            or (portfolio_context_present and decision.relation != "new_topic")
        )
    ):
        return replace(
            decision,
            execution_route="research",
            context_binding=ContextBinding(
                source="portfolio",
                confidence=max(binding.confidence, 0.74),
                reason="portfolio context is a stronger visible anchor than implicit conversation history",
                subject_hint=binding.subject_hint or "current portfolio",
            ),
            confidence=max(decision.confidence, 0.72),
            needs_tools=True,
        )

    if (
        not tickers
        and not selection_ids
        and decision.relation != "new_topic"
        and source in {"none", *_IMPLICIT_HISTORY_SOURCES}
        and _compact_last_report(memory_context)
        and (
            decision.domain_intent == "report_discussion"
            or (source == "none" and decision.domain_intent in {"news", "analysis"})
        )
    ):
        report = _compact_last_report(memory_context) or {}
        return replace(
            decision,
            context_binding=ContextBinding(
                source="last_report",
                confidence=max(binding.confidence, 0.74),
                reason="recent report is the strongest available follow-up anchor",
                subject_hint=str(report.get("title") or report.get("ticker") or "recent report")[:160],
            ),
        )

    active_symbol = ui_context.get("active_symbol")
    if (
        source in {"none", *_IMPLICIT_HISTORY_SOURCES}
        and decision.relation != "new_topic"
        and isinstance(active_symbol, str)
        and active_symbol.strip()
    ):
        view = str(ui_context.get("view") or "").strip().lower()
        if view not in _GLOBAL_CHAT_VIEWS:
            symbol = active_symbol.strip().upper()
            return replace(
                decision,
                context_binding=ContextBinding(
                    source="active_symbol",
                    confidence=max(binding.confidence, 0.72),
                    reason="scoped UI active_symbol is more explicit than implicit conversation history",
                    subject_hint=symbol,
                ),
            )

    if (
        not tickers
        and not selection_ids
        and decision.relation != "new_topic"
        and (
            source in {"none", "unresolved_clarification"}
            or (source in {"last_turn", "recent_focus"} and not binding.subject_hint)
        )
        and has_thread_history
        and (
            decision.execution_route == "clarify"
            or _STRUCTURAL_DEIXIS_RE.search(query)
        )
    ):
        subject_hint = _history_subject_hint(recent_history)
        if subject_hint:
            should_research = (
                bool(decision.task_hints and _task_hints_require_execution(decision.task_hints))
                or (decision.needs_tools and _query_explicitly_requests_grounding(query))
            )
            return replace(
                decision,
                execution_route="research" if should_research else "direct_answer",
                context_binding=ContextBinding(
                    source="last_turn",
                    confidence=max(binding.confidence, 0.76),
                    reason="same-thread history provides a concrete anchor for this follow-up",
                    subject_hint=subject_hint,
                ),
                confidence=max(decision.confidence, 0.72),
                needs_tools=should_research,
                task_hints=decision.task_hints if should_research else (),
                reason=decision.reason
                or "the follow-up was bound to same-thread history before deciding whether tools are needed",
                reply_guidance=decision.reply_guidance
                or "Use the recent conversation context to answer naturally; ask for clarification only if the requested action remains impossible.",
            )

    if (
        not tickers
        and not selection_ids
        and source in {"none", *_IMPLICIT_HISTORY_SOURCES}
        and not has_thread_history
        and _STRUCTURAL_DEIXIS_RE.search(query)
    ):
        return replace(
            decision,
            execution_route="clarify",
            context_binding=ContextBinding(
                source="none",
                confidence=0.0,
                reason="thread has no prior turns, so this deictic follow-up cannot be bound safely",
                subject_hint="",
            ),
            confidence=min(decision.confidence, 0.45),
            needs_tools=False,
            reply_guidance="我这里没有足够的当前会话上下文判断你指的哪一点；请告诉我具体是哪家公司、哪条新闻或哪份报告。",
        )

    if (
        decision.execution_route == "clarify"
        and decision.relation != "new_topic"
        and _bound_context_is_resolved(
            source=source,
            binding=binding,
            ui_context=ui_context,
            memory_context=memory_context,
            recent_history=recent_history,
            selection_ids=selection_ids,
        )
    ):
        continue_route: ExecutionRoute = "research" if decision.needs_tools or bool(decision.task_hints) else "direct_answer"
        return replace(
            decision,
            execution_route=continue_route,
            confidence=max(decision.confidence, 0.72),
            needs_tools=continue_route == "research",
            reason=decision.reason
            or "clarify was downgraded because the follow-up already has a resolved context binding",
            reply_guidance=decision.reply_guidance
            or "Use the bound conversation context to answer naturally; only ask again if the action itself is still impossible.",
        )

    if (
        decision.execution_route == "research"
        and decision.relation != "new_topic"
        and decision.domain_intent not in {"news", "doc_qa", "portfolio", "alert"}
        and not _query_explicitly_requests_grounding(query)
        and not _task_hints_require_execution(decision.task_hints)
        and _bound_context_is_resolved(
            source=source,
            binding=binding,
            ui_context=ui_context,
            memory_context=memory_context,
            recent_history=recent_history,
            selection_ids=selection_ids,
        )
    ):
        return replace(
            decision,
            execution_route="direct_answer",
            confidence=max(decision.confidence, 0.72),
            needs_tools=False,
            task_hints=(),
            reason=decision.reason
            or "research was downgraded because the follow-up already has a resolved context binding and did not request fresh evidence",
            reply_guidance=decision.reply_guidance
            or "Use recent conversation context to answer naturally; do not fetch news, links, quotes, or sources unless the user asks for them.",
        )

    if (
        decision.execution_route == "clarify"
        and decision.domain_intent == "finance_concept"
        and source == "none"
        and not tickers
        and not selection_ids
        and not _STRUCTURAL_DEIXIS_RE.search(query)
    ):
        return replace(
            decision,
            execution_route="direct_answer",
            confidence=max(decision.confidence, 0.72),
            needs_tools=False,
            reply_guidance=decision.reply_guidance or "Answer the financial concept naturally; no ticker is required.",
        )

    if source not in _IMPLICIT_HISTORY_SOURCES:
        return decision

    if source in {"last_turn", "recent_focus"} and not has_thread_history:
        return replace(
            decision,
            execution_route="clarify" if _STRUCTURAL_DEIXIS_RE.search(query) else decision.execution_route,
            context_binding=ContextBinding(
                source="none",
                confidence=0.0,
                reason="thread has no prior turns, so user-level recent focus cannot bind this follow-up",
                subject_hint="",
            ),
            confidence=min(decision.confidence, 0.45),
            needs_tools=False if _STRUCTURAL_DEIXIS_RE.search(query) else decision.needs_tools,
            reply_guidance=(
                "我这里没有足够的当前会话上下文判断你指的哪一点；请告诉我具体是哪家公司、哪条新闻或哪份报告。"
                if _STRUCTURAL_DEIXIS_RE.search(query)
                else decision.reply_guidance
            ),
        )

    return decision


def _effective_current_turn_tickers(
    query: str,
    tickers: list[str],
    decision: ConversationDecision | None = None,
) -> list[str]:
    """Return the current effective explicit tickers, not every corrected-away mention.

    The LLM router decides the semantic subject in ``subject_hint``. This helper
    only narrows explicit ticker mentions when the user uses a correction/switch
    pattern such as "not A, actually B"; it never invents a ticker not present in
    the current turn.
    """
    detected = {ticker.upper() for ticker in tickers}
    hint = str((decision.context_binding.subject_hint if decision else "") or "").strip()
    hinted = [
        str(item).upper()
        for item in (extract_tickers(hint).get("tickers") or [])
        if str(item).upper() in detected
    ]
    if hinted:
        return _dedupe_preserve_order(hinted)

    return tickers


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _has_portfolio_context(ui_context: dict[str, Any]) -> bool:
    for key in ("portfolio", "positions", "holdings"):
        value = ui_context.get(key)
        if isinstance(value, dict) and value:
            return True
        if isinstance(value, (list, tuple)) and len(value) > 0:
            return True
    return False


def _recent_history(state: GraphState, *, limit: int = 8) -> list[dict[str, str]]:
    query = str(state.get("query") or "").strip()
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    messages = state.get("messages") or []
    rows: list[dict[str, str]] = []
    for msg in messages:
        role = ""
        if isinstance(msg, HumanMessage):
            role = "user"
        elif isinstance(msg, AIMessage):
            role = "assistant"
        else:
            continue
        content = msg.content if isinstance(msg.content, str) else str(msg.content)
        content = " ".join(content.strip().split())
        if not content:
            continue
        if role == "user" and content == query:
            continue
        rows.append({"role": role, "content": content[:600]})

    raw_session_history = ui_context.get("session_history") if isinstance(ui_context, dict) else None
    if isinstance(raw_session_history, list):
        for item in raw_session_history:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            if role not in {"user", "assistant"}:
                continue
            content = " ".join(str(item.get("content") or "").strip().split())
            if not content:
                continue
            if role == "user" and content == query:
                continue
            row: dict[str, str] = {"role": role, "content": content[:900 if role == "assistant" else 600]}
            tickers = str(item.get("tickers") or "").strip()
            if tickers and role == "user":
                row["tickers"] = tickers[:120]
            rows.append(row)

    deduped: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (row.get("role", ""), row.get("content", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped[-limit:]


def _last_user_history_tickers(recent_history: list[dict[str, str]]) -> list[str]:
    for row in reversed(recent_history or []):
        if row.get("role") != "user":
            continue
        raw = str(row.get("tickers") or "").strip()
        if not raw:
            continue
        tickers: list[str] = []
        seen: set[str] = set()
        for item in re.split(r"[,，\s]+", raw):
            ticker = item.strip().upper()
            if not ticker or ticker in seen:
                continue
            seen.add(ticker)
            tickers.append(ticker)
        if tickers:
            return tickers[:3]
    return []


def _history_subject_hint(recent_history: list[dict[str, str]]) -> str:
    """Return a compact anchor from same-thread history for follow-up binding."""
    tickers = _last_user_history_tickers(recent_history)
    if tickers:
        return ", ".join(tickers[:3])

    for preferred_role in ("user", "assistant"):
        for row in reversed(recent_history or []):
            if row.get("role") != preferred_role:
                continue
            content = str(row.get("content") or "").strip()
            if not content:
                continue
            extracted = [
                str(ticker).upper()
                for ticker in (extract_tickers(content).get("tickers") or [])
                if str(ticker).strip()
            ]
            if extracted:
                return ", ".join(_dedupe_preserve_order(extracted)[:3])

    for preferred_role in ("assistant", "user"):
        for row in reversed(recent_history or []):
            if row.get("role") != preferred_role:
                continue
            content = " ".join(str(row.get("content") or "").strip().split())
            if content:
                return content[:160]
    return ""


def _compact_last_report(memory_context: dict[str, Any]) -> dict[str, Any] | None:
    report = memory_context.get("last_report") if isinstance(memory_context, dict) else None
    if not isinstance(report, dict):
        return None
    compact: dict[str, Any] = {}
    for key in ("report_id", "ticker", "title", "summary", "sentiment", "generated_at", "section_titles", "risks"):
        value = report.get(key)
        if value is not None:
            compact[key] = value
    return compact or None


def _compact_recent_focuses(memory_context: dict[str, Any]) -> list[dict[str, Any]]:
    raw = memory_context.get("recent_focuses") if isinstance(memory_context, dict) else None
    rows = raw if isinstance(raw, list) else []
    compact: list[dict[str, Any]] = []
    for item in rows[:3]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "ticker": item.get("ticker"),
                "query": str(item.get("query") or "")[:160],
                "summary": str(item.get("summary") or "")[:500],
                "updated_at": item.get("updated_at"),
            }
        )
    return compact


def _portfolio_summary(ui_context: dict[str, Any]) -> dict[str, Any] | None:
    raw: Any = None
    for key in ("positions", "holdings", "portfolio"):
        candidate = ui_context.get(key) if isinstance(ui_context, dict) else None
        if candidate:
            raw = candidate
            break
    if raw is None:
        return None

    rows: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for item in raw[:12]:
            if not isinstance(item, dict):
                continue
            ticker = str(item.get("ticker") or item.get("symbol") or "").strip().upper()
            if not ticker:
                continue
            row: dict[str, Any] = {"ticker": ticker}
            if item.get("weight") is not None:
                row["weight"] = item.get("weight")
            if item.get("shares") is not None:
                row["shares"] = item.get("shares")
            rows.append(row)
    elif isinstance(raw, dict):
        for key, value in list(raw.items())[:12]:
            ticker = str(key or "").strip().upper()
            if not ticker:
                continue
            row = {"ticker": ticker}
            if isinstance(value, dict):
                if value.get("weight") is not None:
                    row["weight"] = value.get("weight")
                if value.get("shares") is not None:
                    row["shares"] = value.get("shares")
            else:
                row["weight"] = value
            rows.append(row)

    if not rows:
        return {"available": True, "positions": []}
    return {"available": True, "positions": rows, "tickers": [row["ticker"] for row in rows]}


def _selection_summary(ui_context: dict[str, Any]) -> list[dict[str, str]]:
    raw = ui_context.get("selections")
    if not raw and isinstance(ui_context.get("selection"), dict):
        raw = [ui_context["selection"]]
    selections = raw if isinstance(raw, list) else []
    rows: list[dict[str, str]] = []
    for item in selections[:5]:
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "id": str(item.get("id") or "")[:80],
                "type": str(item.get("type") or "")[:40],
                "title": str(item.get("title") or item.get("headline") or "")[:160],
                "source": str(item.get("source") or "")[:80],
                "url": str(item.get("url") or "")[:300],
                "snippet": str(item.get("snippet") or item.get("summary") or item.get("content") or "")[:1200],
            }
        )
    return rows


def _router_inputs(
    state: GraphState,
    *,
    tickers: list[str],
    selection_ids: list[str],
) -> dict[str, Any]:
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    memory_context = state.get("memory_context") if isinstance(state.get("memory_context"), dict) else {}
    recent_history = _recent_history(state)
    return {
        "query": str(state.get("query") or "").strip(),
        "output_mode": state.get("output_mode") or "chat",
        "tickers_detected": tickers,
        "selection_ids": selection_ids,
        "active_symbol": ui_context.get("active_symbol"),
        "selections": _selection_summary(ui_context),
        "portfolio": _portfolio_summary(ui_context),
        "last_report": _compact_last_report(memory_context),
        "last_focus": None,
        "recent_focuses": _compact_recent_focuses(memory_context),
        "recent_history": recent_history,
    }


def _deictic_query_has_no_available_context(
    state: GraphState,
    *,
    tickers: list[str],
    selection_ids: list[str],
) -> bool:
    """Fast-path truly unbound follow-ups before spending a router LLM call."""
    query = str(state.get("query") or "").strip()
    if tickers or selection_ids or not _STRUCTURAL_DEIXIS_RE.search(query):
        return False
    ui_context = state.get("ui_context") if isinstance(state.get("ui_context"), dict) else {}
    memory_context = state.get("memory_context") if isinstance(state.get("memory_context"), dict) else {}
    if _recent_history(state):
        return False
    if _selection_summary(ui_context) or _has_portfolio_context(ui_context):
        return False
    if _compact_last_report(memory_context):
        return False
    active_symbol = ui_context.get("active_symbol")
    if isinstance(active_symbol, str) and active_symbol.strip():
        return False
    return True


def _fallback_decision(
    state: GraphState,
    *,
    tickers: list[str],
    selection_ids: list[str],
) -> ConversationDecision | None:
    """Fail-open fallback.

    It is intentionally narrow: obvious subjects go to research, explicit report
    mode goes to research, otherwise the deterministic understanding node keeps
    handling the turn. It does not try to replace the LLM router with another
    keyword classifier.
    """
    output_mode = str(state.get("output_mode") or "").strip().lower()
    if output_mode == "investment_report":
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(),
            domain_intent="analysis",
            confidence=0.72,
            needs_tools=True,
            reason="explicit report mode",
        )
    alert_decision = _alert_decision_from_extractor(state, tickers=tickers)
    if alert_decision is not None:
        return alert_decision
    query = str(state.get("query") or "").strip()
    if selection_ids or (tickers and _query_explicitly_requests_grounding(query)):
        source: ContextSource = "selection" if selection_ids else "none"
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source=source, confidence=0.6),
            domain_intent="analysis",
            confidence=0.62,
            needs_tools=True,
            reason="explicit subject context",
        )
    if tickers:
        return ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(
                source="none",
                confidence=0.6,
                subject_hint=", ".join(tickers[:3]),
            ),
            domain_intent="analysis",
            confidence=0.62,
            needs_tools=False,
            reason="explicit subject context without grounded data request",
        )
    return None


def _alert_decision_from_extractor(
    state: GraphState,
    *,
    tickers: list[str],
    base: ConversationDecision | None = None,
) -> ConversationDecision | None:
    """Preserve an explicitly extractable alert action.

    This is not a keyword classifier: the alert extractor validates an actionable
    threshold plus ticker before this override can fire. If the user also asks a
    secondary research question, ``remaining_query`` stays in the alert params
    and the alert action can surface that continuation naturally.
    """
    try:
        from backend.graph.nodes.alert_extractor import alert_extractor

        alert_probe = alert_extractor({**state, "subject": {"tickers": tickers}})
    except Exception:
        return None
    if not isinstance(alert_probe, dict) or alert_probe.get("alert_valid") is not True:
        return None

    params = alert_probe.get("alert_params") if isinstance(alert_probe.get("alert_params"), dict) else {}
    remaining_query = str(params.get("remaining_query") or "").strip()
    base_binding = base.context_binding if base is not None else ContextBinding()
    guidance = "先设置提醒。"
    if remaining_query:
        guidance += f" 用户还问到“{remaining_query}”，提醒完成后保留为可继续研究的上下文。"
    return ConversationDecision(
        execution_route="alert",
        context_binding=base_binding,
        relation=base.relation if base is not None else "new_topic",
        domain_intent="alert",
        confidence=max(base.confidence if base is not None else 0.0, 0.82),
        needs_tools=False,
        reason="current turn contains an extractable alert trigger",
        reply_guidance=guidance,
        task_hints=base.task_hints if base is not None else (),
    )


async def route_conversation(
    state: GraphState,
    *,
    tickers: list[str],
    selection_ids: list[str],
) -> ConversationDecision | None:
    """Return a contextual conversation decision, or ``None`` on fail-open."""
    query = str(state.get("query") or "").strip()
    if not query:
        return ConversationDecision(
            execution_route="clarify",
            context_binding=ContextBinding(),
            relation="new_topic",
            domain_intent="unknown",
            confidence=1.0,
            reason="empty query",
        )

    if not _env_bool("FINSIGHT_CONTEXT_ROUTER_ENABLED", True):
        return _fallback_decision(state, tickers=tickers, selection_ids=selection_ids)

    if _deictic_query_has_no_available_context(state, tickers=tickers, selection_ids=selection_ids):
        return ConversationDecision(
            execution_route="clarify",
            context_binding=ContextBinding(
                source="none",
                confidence=0.0,
                reason="thread has no prior turns, so this deictic follow-up cannot be bound safely",
                subject_hint="",
            ),
            relation="follow_up",
            domain_intent="unknown",
            confidence=0.45,
            needs_tools=False,
            reason="deictic follow-up has no same-thread or visible UI context",
            reply_guidance="I do not have enough current conversation context to know which point you mean. Send the relevant point, company, news item, document, or report and I will continue from there.",
        )

    inputs = _router_inputs(state, tickers=tickers, selection_ids=selection_ids)
    timeout_sec = max(2.0, _env_float("FINSIGHT_CONTEXT_ROUTER_TIMEOUT_SEC", 90.0))
    max_tokens = int(max(512, _env_float("FINSIGHT_CONTEXT_ROUTER_MAX_TOKENS", 2200.0)))

    system = """你是 FinSight 的会话上下文路由器。请根据当前用户问题、最近对话、UI 状态、最近报告和最近关注对象，判断本轮应该怎么处理。

不要按关键词表机械匹配；关键词只能作为弱信号。重点是：用户是不是在追问、追问的是哪个上下文、现在想做什么、是否需要实时工具。

只返回一行 JSON，不要代码块：
{
  "execution_route": "direct_answer|research|alert|clarify|out_of_scope",
  "context_binding": {
    "source": "none|last_turn|last_report|active_symbol|selection|portfolio|recent_focus|unresolved_clarification",
    "confidence": 0.0,
    "reason": "为什么绑定这个上下文",
    "subject_hint": "被指代的对象，如 NVDA / 最近报告 / 选中文档"
  },
  "relation": "new_topic|follow_up|elaborate|compare|correct|apply_constraint|continue_previous|summarize",
  "domain_intent": "smalltalk|finance_concept|quote|news|analysis|report_discussion|doc_qa|portfolio|alert|unknown",
  "confidence": 0.0,
  "needs_tools": false,
  "reason": "简短理由",
  "reply_guidance": "如果可直接回答，应如何回答",
  "task_hints": [
    {
      "subject_type": "company|index|crypto|fund|macro|theme|portfolio|research_doc|news_item|unknown",
      "subject_label": "AAPL / MSFT / 美联储利率 / 当前持仓",
      "tickers": ["AAPL"],
      "operation": "price|fetch|technical|analyze_impact|news_impact|qa|compare|portfolio_impact|rebalance_check|alert_set|macro_brief|fact_check",
      "params": {},
      "reason": "为什么这个原子任务存在"
    }
  ]
}

判断标准：
- execution_route 只表达执行路径，不表达具体 follow-up 类型。
- 所有追问都用 relation + context_binding 表达，不要按报告、新闻、报价等上下文来源拆出新的 execution_route。
- direct_answer：普通对话、金融概念解释、无需实时证据的报告讨论/摘要/展开。
- research：需要行情、新闻、公司/宏观/组合/文档证据或工具执行。
- alert：用户要设置提醒/预警/触发条件。
- clarify：无法安全绑定上下文或缺少必要对象。
- out_of_scope：当前请求不是金融投研任务，也不需要工具或 planner。开放闲聊、生活娱乐、身份边界类问题应由直接回复层自然回答或说明边界；不要为了非金融请求构造研究计划。
- 对“你是谁/你能做什么/怎么用”等能力或身份问题，用 direct_answer，不要进入 planner。
- 如果用户问“那它呢/第二点/继续/展开/刚才那个”，优先从 recent_history、last_report、active_symbol、selection 找 context_binding。
- recent_focuses/last_focus 属于用户级长期记忆，只能做背景参考，不能在没有当前线程 recent_history 时拿来绑定“它/第二点”。
- 如果 portfolio/positions/holdings 存在，说明 UI 已给出当前持仓上下文；用户问“我的持仓/组合/这些新闻对我影响”时优先绑定 portfolio，不要再要求用户重复给持仓。
- 如果 selection 存在，它是强 UI 锚点；如果 active_symbol 来自 MiniChat/标的页等局部入口，它也是强 UI 锚点；普通全局 chat 的 active_symbol 只能作为弱背景，不应抢走可靠会话上下文。
- 如果用户直接给 URL，URL 本身是用户给的外部证据源。需要读网页内容时走 research，让 planner 使用 fetch_url_content 或 search；不要在未读取内容前假装知道网页是什么。
- 如果 query 已清楚说明 URL 是金融新闻、公告、研报或网页文档，可在 task_hints 里保留 URL 参数并选择合适 subject_type；如果内容领域不明，用 research 先取证，不要靠 URL 字符串臆断结论。
- 如果 relation 是 new_topic，不要绑定 last_turn / recent_focus / last_report；新的宏观、行业、公司或概念问题应按新话题处理。
- 如果最近报告存在，用户追问报告结论、章节、风险、摘要或假设，context_binding.source 应为 last_report，domain_intent 通常为 report_discussion；是否需要工具看用户是否要求更新/重新查/最新。
- “为什么/怎么影响/机制是什么”这类金融机制解释通常用 direct_answer；只有用户明确需要最新行情、新闻、数据、报告、组合测算或实时验证时才用 research。
- 用户要求保证收益、确定性涨跌或“直接给必涨/稳赚标的”时，用 direct_answer，needs_tools=false；回答层会自然拒绝确定性承诺，并转成风险框架或候选池比较。不要为了这种请求进入搜索或 planner。
- 如果一条消息里有多个明确请求，例如“AAPL 价格、MSFT 新闻、再解释利率影响”，execution_route 仍只选一个，但 task_hints 要列出每个原子请求，不要只给一个笼统 domain_intent。
- 如果用户要求设置提醒/预警且已经给出 ticker 和阈值，即使同一句还问新闻，也优先 execution_route=alert、domain_intent=alert；secondary query 写入 reply_guidance。
"""
    prompt = "<context>\n" + json_dumps_safe(inputs, ensure_ascii=False, indent=2) + "\n</context>"

    try:
        from backend.llm_config import create_llm

        llm = create_llm(temperature=0.0, max_tokens=max_tokens, request_timeout=int(timeout_sec) + 2)
        messages = [SystemMessage(content=system), HumanMessage(content=prompt)]
        response = await asyncio.wait_for(llm.ainvoke(messages), timeout=timeout_sec)
        raw_output = str(getattr(response, "content", "") or "")
        try:
            payload = _extract_json_object(raw_output)
        except Exception as parse_exc:
            if not raw_output.strip() and (tickers or selection_ids):
                logger.info("[conversation_router] empty LLM output; using explicit-subject fail-open decision")
                return _fallback_decision(state, tickers=tickers, selection_ids=selection_ids)
            if tickers or selection_ids:
                logger.info("[conversation_router] invalid JSON with explicit subject; using fail-open decision: %s", parse_exc)
                return _fallback_decision(state, tickers=tickers, selection_ids=selection_ids)
            max_attempts = int(max(1, _env_float("FINSIGHT_CONTEXT_ROUTER_MAX_ATTEMPTS", 2.0)))
            if max_attempts <= 1:
                raise
            logger.info(
                "[conversation_router] invalid JSON, retrying once: %s raw=%r",
                parse_exc,
                raw_output[:500],
            )
            retry_prompt = (
                prompt
                + "\n\n上一轮输出不是合法 JSON。请只返回一个 JSON object，不要解释、不要 markdown、不要代码块。"
                + "\n上一轮输出片段：\n"
                + raw_output[:1600]
            )
            retry_response = await asyncio.wait_for(
                llm.ainvoke([SystemMessage(content=system), HumanMessage(content=retry_prompt)]),
                timeout=timeout_sec,
            )
            raw_output = str(getattr(retry_response, "content", "") or "")
            payload = _extract_json_object(raw_output)
        decision = normalize_context_decision(
            _coerce_decision(payload),
            state,
            tickers=tickers,
            selection_ids=selection_ids,
        )
        alert_decision = _alert_decision_from_extractor(state, tickers=tickers, base=decision)
        if alert_decision is not None:
            decision = alert_decision
        logger.info(
            "[conversation_router] route=%s binding=%s relation=%s domain=%s conf=%.2f",
            decision.execution_route,
            decision.context_binding.source,
            decision.relation,
            decision.domain_intent,
            decision.confidence,
        )
        return decision
    except Exception as exc:
        logger.info("[conversation_router] fail-open: %s", exc)
        return _fallback_decision(state, tickers=tickers, selection_ids=selection_ids)


def _fallback_finance_concept_reply(query: str) -> str:
    query_text = str(query or "").strip()
    if query_text:
        return (
            f"这题可以先按机制理解：{query_text} 的关键是看它会改变现金流、估值倍数还是风险偏好。"
            "如果只是概念解释，不需要先给 ticker；如果要判断当前市场影响，再结合最新行情和新闻会更稳。"
        )
    return "这是一个金融概念问题，不需要先给 ticker；你可以直接问概念本身，我会先用简短机制解释。"


def _fallback_direct_reply(decision: ConversationDecision, state: GraphState) -> str:
    query = str(state.get("query") or "").strip()
    memory_context = state.get("memory_context") if isinstance(state.get("memory_context"), dict) else {}
    last_report = _compact_last_report(memory_context)
    subject_hint = str(decision.context_binding.subject_hint or "").strip()

    if decision.execution_route == "out_of_scope":
        return "这个问题不太属于金融投研范围。你可以把它转成市场、行业或相关公司的问题，我再接着分析。"
    if decision.context_binding.source == "last_report" and last_report:
        title = str(last_report.get("title") or "刚才那份报告").strip()
        summary = str(last_report.get("summary") or "").strip()
        risks = last_report.get("risks") if isinstance(last_report.get("risks"), list) else []
        lines = [f"可以，我们接着《{title}》聊。"]
        if summary:
            lines.extend(["", summary[:900]])
        if risks:
            lines.extend(["", "报告里已记录的主要风险："])
            lines.extend(f"- {str(item).strip()}" for item in risks[:4] if str(item).strip())
        return "\n".join(lines).strip()
    if decision.domain_intent == "finance_concept":
        return _fallback_finance_concept_reply(query)
    return "我在。你可以继续直接问，也可以给我一个股票、公司、宏观主题或刚才报告里的具体点。"


async def generate_contextual_reply(
    state: GraphState,
    decision: ConversationDecision,
) -> str:
    """Generate a natural direct-answer reply."""
    timeout_sec = max(2.0, _env_float("FINSIGHT_CONTEXT_REPLY_TIMEOUT_SEC", 120.0))
    max_tokens = int(max(512, _env_float("FINSIGHT_CONTEXT_REPLY_MAX_TOKENS", 3000.0)))
    inputs = _router_inputs(state, tickers=[], selection_ids=[])
    inputs["decision"] = decision.model_dump()

    system = """你是 FinSight，一个自然对话式金融投研助手。根据 decision 和上下文直接回答用户。

风格要求：
- 像正常 ChatGPT 对话，不要套“问题/后续关注/分析对象/本轮包含”等模板。
- 不要暴露工具名、路由名、trace、内部字段。
- context_binding 表示用户接的是哪个上下文；不是只有报告才有追问。
- 如果 context_binding.source=last_report，基于 last_report 接着聊；可以引用报告标题、摘要、风险，但不要假装重新跑了实时数据。
- 如果 domain_intent=finance_concept，用清楚自然的解释，必要时给一个简单例子；不要要求用户先给 ticker。
- 如果 out_of_scope，直接用金融助手身份简短说明不能做该非金融请求，可以自然给一个转成金融视角的方向；不要列模板标题。
- 如果用户要求保证收益、确定性涨跌或“必涨/稳赚标的”，不要承诺结果，不要假装能预测；自然说明边界，并转成“候选池 + 可验证证据 + 风险控制”的分析方式。
- 如果 relation=correct，简短确认用户纠正后的对象，之后按纠正后的对象继续；不要要求用户重复确认已经明确的 ticker。
- 如果用户是省略式追问，优先结合 recent_history 和 context_binding 推断对象与动作；上下文足够时直接回答、计算、改写或展开，不要让用户重复对象。
- 如果用户给了数字或要求计算，先看最近对话里是否已有可用数值；缺少必要数值时，只说明缺哪一个，不要忘掉已绑定的对象。
- 不要虚构最新市场事实；需要实时数据时说明要进入研究链路。
"""
    prompt = "<context>\n" + json_dumps_safe(inputs, ensure_ascii=False, indent=2) + "\n</context>"

    try:
        from backend.llm_config import create_llm

        llm = create_llm(temperature=0.35, max_tokens=max_tokens, request_timeout=int(timeout_sec) + 2)
        response = await asyncio.wait_for(
            llm.ainvoke([SystemMessage(content=system), HumanMessage(content=prompt)]),
            timeout=timeout_sec,
        )
        text = str(getattr(response, "content", "") or "").strip()
        text = re.sub(r"^```(?:markdown)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text).strip()
        return text or _fallback_direct_reply(decision, state)
    except Exception as exc:
        logger.info("[conversation_router] direct reply fallback: %s", exc)
        return _fallback_direct_reply(decision, state)


__all__ = [
    "ContextBinding",
    "ConversationDecision",
    "ContextSource",
    "DomainIntent",
    "ExecutionRoute",
    "Relation",
    "generate_contextual_reply",
    "normalize_context_decision",
    "route_conversation",
]

# -*- coding: utf-8 -*-
"""确定性请求路由使用的轻量决策合同。"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


ExecutionRoute = Literal["direct_answer", "research", "clarify", "out_of_scope"]
ContextSource = Literal[
    "none",
    "last_turn",
    "last_report",
    "active_symbol",
    "selection",
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
    decision_source: str = "deterministic_rules"

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
            "decision_source": self.decision_source,
        }


__all__ = [
    "ContextBinding",
    "ContextSource",
    "ConversationDecision",
    "DomainIntent",
    "ExecutionRoute",
    "Relation",
]

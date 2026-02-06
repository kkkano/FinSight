# -*- coding: utf-8 -*-
"""
Graph state contract (SSOT):
docs/06_LANGGRAPH_REFACTOR_GUIDE.md
"""

from __future__ import annotations

from typing import Annotated, Literal, NotRequired, TypedDict

from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages

from backend.contracts import GRAPH_STATE_SCHEMA_VERSION

SubjectType = Literal[
    "news_item",
    "news_set",
    "company",
    "filing",
    "research_doc",
    "portfolio",
    "unknown",
]

OutputMode = Literal["chat", "brief", "investment_report"]


class Subject(TypedDict):
    subject_type: SubjectType
    tickers: list[str]
    selection_ids: list[str]
    selection_types: list[str]
    selection_payload: list[dict]


class Operation(TypedDict):
    name: str
    confidence: float
    params: dict


class Clarify(TypedDict):
    """
    Clarification request state.

    Only the `Clarify` node is allowed to write this field.
    """

    needed: bool
    reason: str
    question: str
    suggestions: list[str]


class GraphState(MessagesState):
    """
    Extend MessagesState with FinSight-specific fields.

    Notes:
    - `messages` uses langgraph's `add_messages` reducer to append.
    - UI context (selection/active_symbol) is ephemeral per request.
    """

    # MessagesState already defines:
    # messages: Annotated[list[AnyMessage], add_messages]
    messages: Annotated[list, add_messages]

    thread_id: str
    schema_version: NotRequired[str]
    query: str

    ui_context: NotRequired[dict]
    subject: NotRequired[Subject]
    operation: NotRequired[Operation]
    output_mode: NotRequired[OutputMode]
    strict_selection: NotRequired[bool]
    clarify: NotRequired[Clarify]

    policy: NotRequired[dict]
    plan_ir: NotRequired[dict]
    artifacts: NotRequired[dict]
    trace: NotRequired[dict]


__all__ = ["GRAPH_STATE_SCHEMA_VERSION", "GraphState", "Subject", "Operation", "Clarify"]

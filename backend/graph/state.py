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


class Policy(TypedDict, total=False):
    """Policy gate output: budget limits and guardrails.

    Actual structure produced by policy_gate node:
    - budget: nested dict with max_rounds, max_tools, max_seconds, etc.
    - allowed_tools: list of tool name strings
    - tool_schemas: dict mapping tool name -> JSON schema
    - allowed_agents: list of agent name strings
    - agent_selection: dict with required/max_agents/min_agents
    - agent_schemas: dict mapping agent name -> JSON schema
    """

    budget: dict
    allowed_tools: list[str]
    tool_schemas: dict
    allowed_agents: list[str]
    agent_selection: dict
    agent_schemas: dict


class PlanIR(TypedDict, total=False):
    """Planner intermediate representation."""

    steps: list[dict]
    required_agents: list[str]
    estimated_cost: str
    rationale: str
    prompt_variant: str


class Artifacts(TypedDict, total=False):
    """Executor output artifacts."""

    evidence_pool: list[dict]
    agent_outputs: dict
    render_vars: dict
    report: dict
    response: str


class Trace(TypedDict, total=False):
    """Observability trace for the graph run."""

    events: list[dict]
    timings: dict
    failures: list[dict]
    runtime: dict


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

    policy: NotRequired[Policy]
    plan_ir: NotRequired[PlanIR]
    artifacts: NotRequired[Artifacts]
    trace: NotRequired[Trace]


__all__ = [
    "GRAPH_STATE_SCHEMA_VERSION",
    "GraphState",
    "Subject",
    "Operation",
    "Clarify",
    "Policy",
    "PlanIR",
    "Artifacts",
    "Trace",
]

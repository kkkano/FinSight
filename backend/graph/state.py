# -*- coding: utf-8 -*-
"""
Graph state contract (SSOT):
docs/06a_LANGGRAPH_DESIGN_SPEC.md
docs/plans/2026-05-03_request_understanding_task_graph_spec.md
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, NotRequired, TypedDict

from langgraph.graph import MessagesState
from langgraph.graph.message import add_messages

from backend.contracts import GRAPH_STATE_SCHEMA_VERSION
from backend.graph.confirmation_policy import ConfirmationMode

SubjectType = Literal[
    "news_item",
    "news_set",
    "company",
    "index",
    "commodity",
    "macro",
    "theme",
    "filing",
    "research_doc",
    "portfolio",
    "unknown",
]

OutputMode = Literal["chat", "brief", "investment_report"]
UnderstandingRoute = Literal["direct", "research", "alert", "clarify"]
UnderstandingTaskStatus = Literal["ready", "blocked"]
TimeScopeKind = Literal[
    "today",
    "yesterday",
    "this_week",
    "latest",
    "recent",
    "explicit_range",
    "unspecified",
]


class Subject(TypedDict):
    subject_type: SubjectType
    tickers: list[str]
    selection_ids: list[str]
    selection_types: list[str]
    selection_payload: list[dict]
    binding_tier: str
    is_comparison: NotRequired[bool]


class Operation(TypedDict):
    name: str
    confidence: float
    params: dict


class TimeScope(TypedDict, total=False):
    kind: TimeScopeKind
    label: str
    start: str
    end: str


class ContextRef(TypedDict, total=False):
    source: str
    key: str
    label: str
    value: Any


class UnderstandingTask(TypedDict, total=False):
    id: str
    subject_type: SubjectType
    subject_label: str
    tickers: list[str]
    selection_ids: list[str]
    selection_types: list[str]
    operation: Operation
    time_scope: TimeScope
    priority: int
    status: UnderstandingTaskStatus
    reason: str
    constraints: list[str]
    params: dict[str, Any]


class BlockedTask(TypedDict, total=False):
    id: str
    subject_type: SubjectType
    subject_label: str
    operation: Operation
    reason: str
    question: str
    suggestions: list[str]
    fallback_allowed: bool


class Understanding(TypedDict, total=False):
    route: UnderstandingRoute
    original_query: str
    cleaned_query: str
    language: str
    social_prefix: str
    user_visible_summary: str
    confidence: float
    tasks: list[UnderstandingTask]
    blocked_tasks: list[BlockedTask]
    context_refs: list[ContextRef]
    fallback_assumptions: list[str]


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

    goal: str
    subject: dict
    output_mode: OutputMode
    tasks: list[dict]
    steps: list[dict]
    synthesis: dict
    budget: dict


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
    user_email: NotRequired[str]
    subject: NotRequired[Subject]
    operation: NotRequired[Operation]
    alert_params: NotRequired[dict[str, Any]]
    alert_valid: NotRequired[bool]
    skip_session_context: NotRequired[bool]
    output_mode: NotRequired[OutputMode]
    strict_selection: NotRequired[bool]
    clarify: NotRequired[Clarify]
    chat_responded: NotRequired[bool]
    memory_context: NotRequired[dict[str, Any]]
    understanding: NotRequired[Understanding]
    tasks: NotRequired[list[UnderstandingTask]]
    blocked_tasks: NotRequired[list[BlockedTask]]
    context_refs: NotRequired[list[ContextRef]]

    policy: NotRequired[Policy]
    plan_ir: NotRequired[PlanIR]
    artifacts: NotRequired[Artifacts]
    trace: NotRequired[Trace]

    # --- Gate-1: human-in-the-loop confirmation ---
    require_confirmation: NotRequired[bool | None]
    confirmation_mode: NotRequired[ConfirmationMode]
    confirmation_options: NotRequired[list[str]]
    user_confirmation: NotRequired[Any]
    confirmation_intent: NotRequired[str]
    confirmation_instruction: NotRequired[str | None]


__all__ = [
    "GRAPH_STATE_SCHEMA_VERSION",
    "GraphState",
    "ConfirmationMode",
    "Subject",
    "Operation",
    "TimeScope",
    "ContextRef",
    "UnderstandingTask",
    "BlockedTask",
    "Understanding",
    "Clarify",
    "Policy",
    "PlanIR",
    "Artifacts",
    "Trace",
]

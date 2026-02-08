# -*- coding: utf-8 -*-
from __future__ import annotations

from backend.graph.json_utils import json_dumps_safe
from backend.graph.state import GraphState


def build_planner_prompt(state: GraphState, variant: str = "A") -> str:
    """
    Build a constrained Planner prompt that asks the model to output PlanIR JSON only.

    Phase 3: prompt exists + is testable; the actual LLM call will be wired later.
    """
    subject = state.get("subject") or {}
    operation = state.get("operation") or {}
    output_mode = state.get("output_mode") or "brief"
    policy = state.get("policy") or {}
    op_name = operation.get("name") if isinstance(operation, dict) else None
    op_name = str(op_name) if isinstance(op_name, str) and op_name else "qa"

    budget = policy.get("budget") if isinstance(policy, dict) else None
    allowed_tools = policy.get("allowed_tools") if isinstance(policy, dict) else None
    tool_schemas = policy.get("tool_schemas") if isinstance(policy, dict) else None
    allowed_agents = policy.get("allowed_agents") if isinstance(policy, dict) else None
    agent_schemas = policy.get("agent_schemas") if isinstance(policy, dict) else None

    planner_variant = str(variant or "A").strip().upper()
    if planner_variant not in {"A", "B"}:
        planner_variant = "A"

    selection_payload = subject.get("selection_payload") if isinstance(subject, dict) else None
    has_selection = bool(selection_payload)

    inputs = {
        "query": state.get("query") or "",
        "subject": subject,
        "operation": operation,
        "output_mode": output_mode,
        "budget": budget,
        "allowed_tools": allowed_tools,
        "tool_schemas": tool_schemas,
        "allowed_agents": allowed_agents,
        "agent_schemas": agent_schemas,
    }

    variant_guidance = (
        "- Variant A: prioritize minimal-step plans with strong determinism and low execution cost.\n"
        "- Prefer fewer required steps unless operation constraints demand more."
    )
    if planner_variant == "B":
        variant_guidance = (
            "- Variant B: prioritize explainability and plan robustness while keeping budget discipline.\n"
            "- Make decision rationale explicit in `why`, and prefer parallel_group when safe."
        )

    return f"""<role>FinSight Planner</role>

<task>
You will create a structured execution plan (PlanIR) for a finance assistant.
Return JSON ONLY. No markdown, no commentary.
</task>

<planner_variant>{planner_variant}</planner_variant>

<inputs>
{json_dumps_safe(inputs, ensure_ascii=False, indent=2)}
</inputs>

<output_format>
Return a single JSON object with keys:
- goal (string)
- subject (object)
- output_mode ("chat"|"brief"|"investment_report")
- steps (array of steps)
- synthesis (object)
- budget (object)
</output_format>

<step_schema>
Each step must follow:
{{"id":"s1","kind":"tool|agent|llm","name":"...","inputs":{{...}},"parallel_group":null,"why":"...","optional":false}}
</step_schema>

<constraints>
1) You MUST only use tool/agent names from allowlists in inputs.
2) If has selection (selection_payload non-empty), the FIRST step MUST summarize selection.
3) If output_mode != "investment_report", DO NOT add any "report section fill" style steps.
4) Keep the plan minimal: do not default to running all tools/agents.
</constraints>

<guidelines>
- operation="{op_name}"
- If operation == "price": include get_stock_price (required).
- If operation == "technical": include get_stock_price + get_technical_snapshot (required).
- If operation == "fetch": prefer get_company_news or search for recency.
{variant_guidance}
</guidelines>
"""


__all__ = ["build_planner_prompt"]

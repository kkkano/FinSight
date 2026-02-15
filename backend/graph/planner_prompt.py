# -*- coding: utf-8 -*-
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage

from backend.graph.json_utils import json_dumps_safe
from backend.graph.state import GraphState

# Maximum number of recent messages to include in planner context.
# Each turn = 1 Human + 1 AI, so 12 messages ≈ 6 rounds.
_MAX_HISTORY_MESSAGES = 12


def _format_conversation_history(state: GraphState) -> str:
    """
    Extract recent conversation history from state messages for planner context.

    Returns an XML block if history exists, empty string otherwise.
    Only includes messages BEFORE the current query (i.e., history, not the
    current turn's HumanMessage which is already in inputs.query).
    """
    messages = state.get("messages") or []
    if not messages:
        return ""

    current_query = (state.get("query") or "").strip()

    # Filter to Human/AI messages, skip current query's message
    history_msgs = []
    for msg in messages:
        if isinstance(msg, HumanMessage):
            content = msg.content.strip() if isinstance(msg.content, str) else str(msg.content).strip()
            # Skip the current query (it's the last HumanMessage matching query text)
            if content == current_query and not any(
                isinstance(m, HumanMessage) and
                (m.content.strip() if isinstance(m.content, str) else str(m.content).strip()) == current_query
                for m in messages[messages.index(msg) + 1:]
                if isinstance(m, HumanMessage)
            ):
                continue
            history_msgs.append(("user", content))
        elif isinstance(msg, AIMessage):
            content = msg.content.strip() if isinstance(msg.content, str) else str(msg.content).strip()
            if content:
                # Truncate long AI responses for context
                if len(content) > 300:
                    content = content[:300] + "..."
                history_msgs.append(("assistant", content))

    if not history_msgs:
        return ""

    # Take last N messages
    recent = history_msgs[-_MAX_HISTORY_MESSAGES:]

    lines = []
    for role, content in recent:
        lines.append(f"[{role}]: {content}")

    return (
        "<conversation_history>\n"
        "以下是用户与助手之前的对话记录，用于理解指代和上下文：\n"
        + "\n".join(lines)
        + "\n</conversation_history>\n"
    )


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
        "- Variant A: 优先最小化步骤数，强确定性，低执行成本。\n"
        "- 除非 operation 约束明确要求，否则倾向更少的必需步骤。"
    )
    if planner_variant == "B":
        variant_guidance = (
            "- Variant B: 优先计划的可解释性和健壮性，同时保持预算纪律。\n"
            "- 在 'why' 中详细说明决策依据，安全时优先使用 parallel_group 并行执行。"
        )

    return f"""<role>FinSight Planner — 负责为金融助手创建最优执行计划</role>

<task>
根据用户查询和可用资源，生成一份结构化执行计划 (PlanIR)。
仅返回 JSON，禁止 markdown、注释或任何非 JSON 内容。
</task>

<planner_variant>{planner_variant}</planner_variant>

{_format_conversation_history(state)}<inputs>
{json_dumps_safe(inputs, ensure_ascii=False, indent=2)}
</inputs>

<output_format>
返回单个 JSON 对象，包含以下键：
- goal (string): 一句话描述计划目标
- subject (object): 包含 ticker、name 等标的信息
- output_mode ("chat"|"brief"|"investment_report"): 输出模式
- steps (array): 执行步骤数组
- synthesis (object): 合成策略，如 {{"strategy":"merge","template":"company_report"}}
- budget (object): 资源预算，如 {{"max_steps":6,"max_tokens":4000}}
</output_format>

<step_schema>
每个 step 必须遵循此结构：
{{"id":"s1","kind":"tool|agent|llm","name":"<allowlist中的名称>","inputs":{{...}},"parallel_group":null,"why":"<一句话理由>","optional":false}}

kind 类型说明：
- "tool": 调用数据获取工具（get_stock_price, get_company_news 等）
- "agent": 调用分析 Agent（price_agent, news_agent, technical_agent 等）
- "llm": 直接 LLM 推理步骤
</step_schema>

<constraints>
1) 仅使用 inputs.allowed_tools 和 inputs.allowed_agents 中列出的名称，禁止编造工具/Agent 名。
2) 若 selection_payload 非空，第一步必须为 summarize_selection（汇总用户选中的内容）。
3) 当 output_mode != "investment_report" 时，禁止添加"报告章节填充"类步骤。
4) 计划应最小化：不要默认运行所有工具/Agent，仅包含回答用户问题所必需的步骤。
5) 可并行的步骤应设置相同的 parallel_group 值（如 "p1"）以提升执行效率。
6) 每个步骤的 "why" 字段必须说明该步骤对回答用户问题的必要性。
7) 若存在 conversation_history，利用对话上下文理解代词指代和隐含意图（如"它的PE"→"之前讨论的标的的PE"）。
</constraints>

<operation_guidelines>
当前 operation="{op_name}"

操作类型 → 必需步骤映射：
- "price" → 必须包含 get_stock_price
- "technical" → 必须包含 get_stock_price + get_technical_snapshot（可并行）
- "fundamental" → 必须包含 fundamental_agent
- "news"/"fetch" → 优先 get_company_news 或 search（获取时效性信息）
- "macro" → 必须包含 macro_agent
- "qa"/"general" → 根据查询内容选择最少量工具
- "investment_report" → 至少包含 price_agent + 2 个分析 Agent

预算纪律：
- chat/brief 模式: 1-3 步，快速响应
- investment_report 模式: 3-6 步，全面分析
</operation_guidelines>

<variant_guidance>
{variant_guidance}
</variant_guidance>
"""


__all__ = ["build_planner_prompt"]

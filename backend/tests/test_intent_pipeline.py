# -*- coding: utf-8 -*-
"""WP2-T3：意图管线——LLM 唯一决策者 + 规则兜底。"""
import pytest
from unittest.mock import AsyncMock, patch

from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision


def make_decision(route: str, task_hints: tuple = (), **kw) -> ConversationDecision:
    return ConversationDecision(
        execution_route=route,
        context_binding=kw.pop("context_binding", ContextBinding()),
        relation=kw.pop("relation", "new_topic"),
        domain_intent=kw.pop("domain_intent", "analysis"),
        confidence=kw.pop("confidence", 0.9),
        needs_tools=kw.pop("needs_tools", route == "research"),
        reason=kw.pop("reason", "test"),
        task_hints=task_hints,
        **kw,
    )


@pytest.mark.asyncio
async def test_llm_research_decision_is_authoritative():
    """LLM 判 research + task_hints → 任务来自 hints 投影，关键词瀑布不得另起炉灶。"""
    from backend.graph.intent import pipeline

    decision = make_decision(
        "research",
        task_hints=({"operation": "price", "tickers": ["AAPL"], "subject_type": "company"},),
    )
    with patch.object(pipeline, "route_conversation", new=AsyncMock(return_value=decision)):
        frame, result = await pipeline.build_intent_result({"query": "AAPL 现在多少钱", "ui_context": {}})
    assert frame.source == "llm_router"
    assert frame.route in {"research", "alert"}
    assert [t.operation for t in frame.tasks] == ["price"]
    assert result["understanding"]["route"] == "research"


@pytest.mark.asyncio
async def test_llm_direct_decision_cannot_become_research():
    """direct 决策复核只能保持或降级 clarify——绝不允许被规则强改为 research（ORC-02 修复）。"""
    from backend.graph.intent import pipeline

    decision = make_decision("direct_answer", domain_intent="finance_concept", needs_tools=False)
    with patch.object(pipeline, "route_conversation", new=AsyncMock(return_value=decision)), \
         patch.object(
             pipeline._ur(), "generate_contextual_reply", new=AsyncMock(return_value="市盈率是……")
         ):
        frame, result = await pipeline.build_intent_result({"query": "PE 是什么意思", "ui_context": {}})
    assert frame.route in {"direct", "clarify"}
    assert result["understanding"].get("tasks") in ([], None) or frame.route == "direct"


@pytest.mark.asyncio
async def test_router_unavailable_falls_back_to_rules():
    """LLM 不可用 → 整体委托 legacy 关键词瀑布，行为与金样一致。"""
    from backend.graph.intent import pipeline

    with patch.object(pipeline, "route_conversation", new=AsyncMock(side_effect=TimeoutError)):
        frame, result = await pipeline.build_intent_result({"query": "AAPL 现在多少钱", "ui_context": {}})
    assert frame.source == "rules_fallback"
    assert any(t.operation == "price" for t in frame.tasks)
    assert result["understanding"]["route"] == "research"


@pytest.mark.asyncio
async def test_research_without_hints_delegates_to_fallback():
    """research 但无 hints → mixed 兜底（legacy 全逻辑），不产出空转 research。"""
    from backend.graph.intent import pipeline

    decision = make_decision("research", task_hints=())
    with patch.object(pipeline, "route_conversation", new=AsyncMock(return_value=decision)):
        frame, result = await pipeline.build_intent_result(
            {"query": "对比 AAPL 和 MSFT 的估值", "ui_context": {}}
        )
    assert frame.source == "mixed"
    assert result["understanding"]["tasks"], "fallback 必须产出任务"


@pytest.mark.asyncio
async def test_casual_greeting_short_circuits_without_llm():
    from backend.graph.intent import pipeline

    called = AsyncMock(side_effect=AssertionError("router must not be called for smalltalk"))
    with patch.object(pipeline, "route_conversation", new=called):
        frame, result = await pipeline.build_intent_result({"query": "你好", "ui_context": {}})
    assert frame.route == "direct"
    assert result["chat_responded"] is True

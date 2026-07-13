# -*- coding: utf-8 -*-
"""WP2-T3：意图管线——LLM 唯一决策者 + 规则兜底。"""
import pytest
from unittest.mock import AsyncMock, patch

from backend.graph.intent.router import ContextBinding, ConversationDecision


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


@pytest.mark.asyncio
async def test_compare_query_keeps_non_company_hints(monkeypatch):
    """WP2-T11 验收 bug：compare 分支不得吞掉 router 给的 macro 等非公司 hints。"""
    decision = make_decision(
        "research",
        relation="compare",
        task_hints=(
            {"subject_type": "company", "subject_label": "AAPL", "tickers": ["AAPL"],
             "operation": "valuation_sanity", "params": {"compare_with": "MSFT"}},
            {"subject_type": "company", "subject_label": "MSFT", "tickers": ["MSFT"],
             "operation": "valuation_sanity", "params": {"compare_with": "AAPL"}},
            {"subject_type": "macro", "subject_label": "美联储下次议息", "tickers": [],
             "operation": "macro_brief", "params": {"topic": "FOMC next meeting date"}},
        ),
    )
    from backend.graph.intent.pipeline import build_intent_frame

    with patch("backend.graph.intent.pipeline.route_conversation", new=AsyncMock(return_value=decision)):
        frame = await build_intent_frame(
            {"query": "对比 AAPL 和 MSFT 的估值，另外美联储下次议息是什么时候", "ui_context": {}}
        )
    subject_types = {t.subject_type for t in frame.tasks}
    assert "macro" in subject_types, f"macro hint 被丢弃: {[(t.subject_type, t.operation) for t in frame.tasks]}"
    assert "company" in subject_types


@pytest.mark.asyncio
async def test_llm_compare_projection_preserves_top_level_intent_contract(monkeypatch):
    """生产 renderer 依赖顶层合同；管线不能只把合同埋在 task params 里。"""
    from backend.graph.intent import pipeline

    monkeypatch.setenv("FINSIGHT_INTENT_CONTRACT_MODE", "enforce")
    decision = make_decision(
        "research",
        relation="compare",
        task_hints=(
            {
                "subject_type": "company",
                "subject_label": "NVDA",
                "tickers": ["NVDA"],
                "operation": "valuation_sanity",
            },
            {
                "subject_type": "company",
                "subject_label": "AMD",
                "tickers": ["AMD"],
                "operation": "valuation_sanity",
            },
        ),
    )

    with patch.object(pipeline, "route_conversation", new=AsyncMock(return_value=decision)):
        _frame, result = await pipeline.build_intent_result(
            {"query": "NVDA 和 AMD 哪个估值更合理", "ui_context": {}, "output_mode": "chat"}
        )

    contract = result.get("intent_contract") or {}
    assert contract.get("facets") == ["valuation"]
    assert contract.get("primary_tickers") == ["NVDA", "AMD"]
    assert contract.get("per_ticker_required") is True
    assert (contract.get("render_intent") or {}).get("shape") == "compare"
    assert (result.get("understanding") or {}).get("intent_contract") == contract


@pytest.mark.asyncio
async def test_heuristic_fallback_decision_is_not_authoritative():
    """router 的 fail-open 启发式决策（decision_source=heuristic_fallback）
    不得拥有 LLM 权威——投资类 query 必须交回规则 fallback 产生 research 任务。"""
    decision = make_decision(
        "direct_answer",
        reason="explicit subject context without grounded data request",
        decision_source="heuristic_fallback",
    )
    from backend.graph.intent.pipeline import build_intent_frame

    with patch("backend.graph.intent.pipeline.route_conversation", new=AsyncMock(return_value=decision)):
        # legacy 的 _TRADE_DECISION_RE 动词表不含「投资」——「值得买」才触发 must_project 兜底；
        # 本测试验证的是"启发式决策交回 legacy 兜底"这条机制本身。
        frame = await build_intent_frame({"query": "AAPL 值得买吗", "ui_context": {}})
    assert frame.source == "rules_fallback"
    assert frame.route == "research"

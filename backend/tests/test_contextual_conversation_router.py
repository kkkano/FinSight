# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import importlib


def _run(coro):
    return asyncio.run(coro)


def _task_required_evidence(task: dict) -> set[str]:
    operation = task.get("operation") if isinstance(task, dict) else {}
    params = operation.get("params") if isinstance(operation, dict) else {}
    if not isinstance(params, dict):
        params = {}
    return set(params.get("required_evidence") or [])


def _assert_evidence_task(result: dict, tickers: tuple[str, ...], expected: set[str]) -> None:
    for task in result.get("tasks") or []:
        if tuple(task.get("tickers") or []) == tickers and expected.issubset(_task_required_evidence(task)):
            return
    raise AssertionError(f"missing evidence task for {tickers}: {sorted(expected)}")


def test_context_router_schema_separates_execution_from_followup_context():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        _coerce_decision,
    )

    decision = _coerce_decision(
        {
            "execution_route": "direct_answer",
            "context_binding": {
                "source": "last_report",
                "confidence": 0.91,
                "reason": "用户在追问上一份报告",
                "subject_hint": "NVDA report",
            },
            "relation": "follow_up",
            "domain_intent": "report_discussion",
            "confidence": 0.88,
            "needs_tools": False,
            "reason": "基于最近报告回答即可",
        }
    )

    assert isinstance(decision, ConversationDecision)
    assert isinstance(decision.context_binding, ContextBinding)
    assert decision.execution_route == "direct_answer"
    assert decision.context_binding.source == "last_report"
    assert decision.relation == "follow_up"
    assert decision.domain_intent == "report_discussion"


def test_context_router_coerces_compound_task_hints():
    from backend.graph.nodes.conversation_router import _coerce_decision

    decision = _coerce_decision(
        {
            "execution_route": "research",
            "context_binding": {"source": "none"},
            "relation": "new_topic",
            "domain_intent": "analysis",
            "confidence": 0.86,
            "needs_tools": True,
            "task_hints": [
                {"subject_type": "company", "subject_label": "AAPL", "operation": "price"},
                {"subject_type": "company", "subject_label": "MSFT", "operation": "fetch", "params": {"topic": "news"}},
                {"subject_type": "macro", "subject_label": "高估值怕利率", "operation": "analyze_impact"},
            ],
        }
    )

    assert [hint["operation"] for hint in decision.task_hints] == ["price", "fetch", "analyze_impact"]
    assert decision.task_hints[0]["tickers"] == ["AAPL"]
    assert decision.task_hints[1]["tickers"] == ["MSFT"]


def test_theme_matching_does_not_treat_again_as_ai_topic():
    from backend.graph.nodes.understand_request import _THEME_HINTS, _contains_any

    assert _contains_any("AI sector pressure", _THEME_HINTS)
    assert not _contains_any("Use 307 as my reference level and calculate the gap again.", _THEME_HINTS)


def test_context_router_rejects_bespoke_followup_routes():
    from backend.graph.nodes.conversation_router import _coerce_decision

    decision = _coerce_decision(
        {
            "route": "report_followup",
            "context_binding": {"source": "last_report"},
            "relation": "follow_up",
            "domain_intent": "report_discussion",
            "confidence": 0.9,
        }
    )

    assert decision.execution_route == "clarify"
    assert decision.context_binding.source == "last_report"


def test_context_router_preserves_extractable_alert_when_llm_picks_news(monkeypatch):
    import backend.llm_config as llm_config
    from backend.graph.nodes.conversation_router import route_conversation

    class _Resp:
        content = """
        {
          "execution_route": "research",
          "context_binding": {"source": "none", "confidence": 0.0, "reason": "", "subject_hint": "TSLA"},
          "relation": "follow_up",
          "domain_intent": "news",
          "confidence": 0.9,
          "needs_tools": true,
          "reason": "用户还问新闻",
          "reply_guidance": "先确认提醒，再查新闻。"
        }
        """

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return _Resp()

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "true")
    monkeypatch.setattr(llm_config, "create_llm", lambda *_args, **_kwargs: _FakeLLM())

    decision = _run(
        route_conversation(
            {"query": "TSLA 跌破 180 提醒我，顺便说说最近新闻。", "ui_context": {}},
            tickers=["TSLA"],
            selection_ids=[],
        )
    )

    assert decision is not None
    assert decision.execution_route == "alert"
    assert decision.domain_intent == "alert"
    assert "最近新闻" in decision.reply_guidance


def test_context_router_empty_llm_output_uses_explicit_subject_fallback(monkeypatch):
    import backend.llm_config as llm_config
    from backend.graph.nodes.conversation_router import route_conversation

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "true")

    class _Resp:
        content = ""

    class _FakeLLM:
        calls = 0

        async def ainvoke(self, _messages):
            self.calls += 1
            return _Resp()

    fake = _FakeLLM()
    monkeypatch.setattr(llm_config, "create_llm", lambda *_args, **_kwargs: fake)

    decision = _run(
        route_conversation(
            {"query": "30秒告诉我 GOOGL 和 MSFT 今天谁更强", "ui_context": {}},
            tickers=["GOOGL", "MSFT"],
            selection_ids=[],
        )
    )

    assert fake.calls == 1
    assert decision is not None
    assert decision.execution_route == "direct_answer"
    assert decision.needs_tools is False


def test_context_router_invalid_json_with_explicit_subject_does_not_retry(monkeypatch):
    import backend.llm_config as llm_config
    from backend.graph.nodes.conversation_router import route_conversation

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "true")

    class _Resp:
        content = '{"execution_route":"research","task_hints":['

    class _FakeLLM:
        calls = 0

        async def ainvoke(self, _messages):
            self.calls += 1
            return _Resp()

    fake = _FakeLLM()
    monkeypatch.setattr(llm_config, "create_llm", lambda *_args, **_kwargs: fake)

    decision = _run(
        route_conversation(
            {"query": "GOOGL MSFT quick brief", "ui_context": {}},
            tickers=["GOOGL", "MSFT"],
            selection_ids=[],
        )
    )

    assert fake.calls == 1
    assert decision is not None
    assert decision.execution_route == "direct_answer"
    assert decision.needs_tools is False


def test_context_router_downgrades_llm_macro_proxy_hint_for_mechanism_question(monkeypatch):
    import backend.llm_config as llm_config
    from backend.graph.nodes.conversation_router import route_conversation

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "true")

    class _Resp:
        content = """
        {
          "execution_route": "research",
          "context_binding": {"source": "none", "confidence": 0.0, "reason": "", "subject_hint": "oil prices"},
          "relation": "new_topic",
          "domain_intent": "finance_concept",
          "confidence": 0.7,
          "needs_tools": true,
          "reason": "mechanism explanation, no tools needed",
          "reply_guidance": "Explain the mechanism directly.",
          "task_hints": [
            {"subject_type": "macro", "subject_label": "oil prices", "tickers": ["CL=F"], "operation": "analyze_impact", "params": {}}
          ]
        }
        """

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return _Resp()

    monkeypatch.setattr(llm_config, "create_llm", lambda *_args, **_kwargs: _FakeLLM())

    decision = _run(
        route_conversation(
            {"query": "Why can oil prices affect inflation expectations and airlines?", "ui_context": {}},
            tickers=[],
            selection_ids=[],
        )
    )

    assert decision is not None
    assert decision.execution_route == "direct_answer"
    assert decision.needs_tools is False
    assert decision.task_hints == ()


def test_finance_concept_fallback_answers_macro_mechanism():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        _fallback_direct_reply,
    )

    reply = _fallback_direct_reply(
        ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(),
            relation="new_topic",
            domain_intent="finance_concept",
            confidence=0.9,
            needs_tools=False,
        ),
        {"query": "美联储降息预期变化会怎么影响大型科技股？"},
    )

    assert "机制" in reply
    assert "现金流" in reply
    assert "估值" in reply
    assert "科技股" in reply
    assert "怎么算" not in reply
    assert "衡量什么" not in reply


def test_context_router_inputs_include_visible_portfolio():
    from backend.graph.nodes.conversation_router import _router_inputs

    inputs = _router_inputs(
        {
            "query": "这些新闻对我的持仓影响大吗？",
            "ui_context": {
                "positions": [
                    {"ticker": "AAPL", "weight": 0.35},
                    {"ticker": "MSFT", "weight": 0.25},
                    {"ticker": "NVDA", "weight": 0.15},
                ],
                "view": "portfolio",
            },
        },
        tickers=[],
        selection_ids=[],
    )

    assert inputs["portfolio"]["available"] is True
    assert inputs["portfolio"]["tickers"] == ["AAPL", "MSFT", "NVDA"]


def test_context_router_new_topic_clears_implicit_history_binding():
    from backend.graph.nodes.conversation_router import _coerce_decision

    decision = _coerce_decision(
        {
            "execution_route": "research",
            "context_binding": {
                "source": "recent_focus",
                "confidence": 0.81,
                "reason": "模型错误地把新宏观问题接到了上一轮股票",
                "subject_hint": "NVDA",
            },
            "relation": "new_topic",
            "domain_intent": "analysis",
            "confidence": 0.8,
            "needs_tools": True,
        }
    )

    assert decision.relation == "new_topic"
    assert decision.context_binding.source == "none"


def test_context_router_keeps_global_chat_history_over_active_symbol():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )
    from langchain_core.messages import AIMessage, HumanMessage

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(
            source="recent_focus",
            confidence=0.82,
            subject_hint="AAPL",
            reason="用户接着上一轮会话追问",
        ),
        relation="follow_up",
        domain_intent="news",
        confidence=0.8,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "那它最近有什么新闻？",
            "ui_context": {"active_symbol": "NVDA", "view": "chat"},
            "messages": [
                HumanMessage(content="AAPL 最近有什么新闻？"),
                AIMessage(content="AAPL 主要看新品、服务收入和监管新闻。"),
            ],
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.context_binding.source == "last_turn"
    assert normalized.context_binding.subject_hint == "AAPL"


def test_context_router_uses_scoped_active_symbol_over_implicit_history():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(
            source="recent_focus",
            confidence=0.8,
            subject_hint="AAPL",
            reason="模型把局部输入误接到了历史焦点",
        ),
        relation="follow_up",
        domain_intent="news",
        confidence=0.79,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "那它最近有什么新闻？",
            "ui_context": {"active_symbol": "NVDA", "view": "dashboard"},
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.context_binding.source == "active_symbol"
    assert normalized.context_binding.subject_hint == "NVDA"


def test_context_router_corrected_ticker_becomes_direct_acknowledgement():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="clarify",
        context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="AAPL"),
        relation="correct",
        domain_intent="unknown",
        confidence=0.7,
        needs_tools=False,
        reply_guidance="确认用户指的是 AAPL。",
    )

    normalized = normalize_context_decision(
        decision,
        {"query": "刚刚不是说看苹果吗？我说的是 AAPL，不是 MSFT。", "ui_context": {"active_symbol": "MSFT", "view": "chat"}},
        tickers=["AAPL", "MSFT"],
        selection_ids=[],
    )

    assert normalized.execution_route == "direct_answer"
    assert normalized.relation == "correct"
    assert normalized.context_binding.subject_hint == "AAPL"
    assert normalized.needs_tools is False


def test_context_router_current_turn_ticker_overrides_implicit_history():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(source="recent_focus", confidence=0.8, subject_hint="MSFT"),
        relation="follow_up",
        domain_intent="analysis",
        confidence=0.77,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {"query": "AAPL 最近新闻怎么看？", "ui_context": {"active_symbol": "MSFT", "view": "dashboard"}},
        tickers=["AAPL"],
        selection_ids=[],
    )

    assert normalized.context_binding.source == "none"
    assert normalized.context_binding.subject_hint == "AAPL"


def test_context_router_portfolio_context_overrides_implicit_history():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(
            source="recent_focus",
            confidence=0.8,
            subject_hint="NVDA",
            reason="模型沿用了上一轮标的",
        ),
        relation="follow_up",
        domain_intent="portfolio",
        confidence=0.82,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "那对我的仓位影响大吗？",
            "ui_context": {"positions": [{"ticker": "AAPL"}, {"ticker": "MSFT"}]},
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.context_binding.source == "portfolio"
    assert normalized.context_binding.subject_hint == "NVDA"


def test_context_router_report_refresh_followup_uses_last_report_when_router_unbound():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(source="none", confidence=0.0),
        relation="follow_up",
        domain_intent="news",
        confidence=0.8,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "用最新新闻更新这个风险判断",
            "ui_context": {},
            "memory_context": {
                "current_report": {
                    "ticker": "AAPL",
                    "title": "AAPL risk report",
                    "summary": "估值和供应链风险",
                }
            },
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.context_binding.source == "last_report"
    assert normalized.context_binding.subject_hint == "AAPL risk report"


def test_context_router_historical_last_report_without_current_thread_clarifies():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(source="last_report", confidence=0.86, subject_hint="AAPL old report"),
        relation="follow_up",
        domain_intent="report_discussion",
        confidence=0.82,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "Continue expanding point three.",
            "ui_context": {},
            "memory_context": {
                "historical_focus_memory": {
                    "last_report": {
                        "ticker": "AAPL",
                        "title": "AAPL old report",
                        "summary": "This report belongs to another thread.",
                    }
                }
            },
            "messages": [],
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "clarify"
    assert normalized.context_binding.source == "none"
    assert normalized.needs_tools is False


def test_context_router_missing_last_report_falls_back_to_same_thread_report_history():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(source="last_report", confidence=0.86, subject_hint="AAPL report"),
        relation="follow_up",
        domain_intent="report_discussion",
        confidence=0.82,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "Update the report with the latest news.",
            "ui_context": {
                "session_history": [
                    {"role": "user", "content": "Generate an investment report for AAPL.", "tickers": "AAPL"},
                    {
                        "role": "assistant",
                        "content": "## Investment report for AAPL\n\nAAPL risks include valuation and demand.",
                    },
                ]
            },
            "memory_context": {},
            "messages": [],
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "research"
    assert normalized.context_binding.source == "last_turn"
    assert "AAPL" in normalized.context_binding.subject_hint
    assert normalized.needs_tools is True


def test_context_router_current_turn_ticker_overrides_last_report_followup():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(source="last_report", confidence=0.85, subject_hint="AAPL report"),
        relation="follow_up",
        domain_intent="news",
        confidence=0.8,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "NVDA 最新新闻怎么看？",
            "ui_context": {},
            "memory_context": {"current_report": {"ticker": "AAPL", "title": "AAPL report"}},
        },
        tickers=["NVDA"],
        selection_ids=[],
    )

    assert normalized.context_binding.source == "none"
    assert normalized.context_binding.subject_hint == "NVDA"


def test_context_router_current_turn_ticker_overrides_all_inherited_contexts():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(source="last_report", confidence=0.88, subject_hint="AAPL report"),
        relation="follow_up",
        domain_intent="analysis",
        confidence=0.82,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "TSLA 最近新闻怎么看？",
            "ui_context": {"active_symbol": "NVDA", "view": "dashboard"},
            "memory_context": {"current_report": {"ticker": "AAPL", "title": "AAPL report"}},
        },
        tickers=["TSLA"],
        selection_ids=[],
    )

    assert normalized.context_binding.source == "none"
    assert normalized.context_binding.subject_hint == "TSLA"


def test_context_router_does_not_bind_user_level_recent_focus_without_thread_history():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(
            source="recent_focus",
            confidence=0.7,
            subject_hint="NVDA",
            reason="用户级最近关注对象是 NVDA",
        ),
        relation="follow_up",
        domain_intent="news",
        confidence=0.7,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "第二点展开一下。",
            "memory_context": {
                "historical_focus_memory": {
                    "last_focus": {"ticker": "NVDA", "query": "NVDA 新闻"}
                }
            },
            "messages": [],
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "clarify"
    assert normalized.context_binding.source == "none"
    assert normalized.needs_tools is False


def test_context_router_deictic_none_binding_without_thread_history_clarifies():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(source="none", confidence=0.0),
        relation="follow_up",
        domain_intent="analysis",
        confidence=0.8,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {"query": "第二点展开一下。", "messages": []},
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "clarify"
    assert normalized.context_binding.source == "none"
    assert normalized.needs_tools is False


def test_context_router_unbound_clarify_uses_same_thread_history():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )
    from langchain_core.messages import AIMessage, HumanMessage

    decision = ConversationDecision(
        execution_route="clarify",
        context_binding=ContextBinding(source="none", confidence=0.0),
        relation="follow_up",
        domain_intent="unknown",
        confidence=0.32,
        needs_tools=False,
        reply_guidance="Need to know which point.",
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "Can you expand that?",
            "messages": [
                HumanMessage(content="AAPL latest news, short answer."),
                AIMessage(content="AAPL has three watch points: product cycle, AI capex, and China demand."),
            ],
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "direct_answer"
    assert normalized.context_binding.source == "last_turn"
    assert normalized.context_binding.subject_hint == "AAPL"
    assert normalized.needs_tools is False


def test_context_router_accepts_session_history_as_thread_history():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(
            source="last_turn",
            confidence=0.8,
            subject_hint="AAPL",
            reason="用户接着同一会话的上一轮问风险",
        ),
        relation="follow_up",
        domain_intent="analysis",
        confidence=0.78,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "那它的风险主要在哪？",
            "messages": [],
            "ui_context": {
                "session_history": [
                    {"role": "user", "content": "AAPL 最近新闻怎么看？", "tickers": "AAPL"},
                    {"role": "assistant", "content": "AAPL 主要看新品、服务收入和监管新闻。"},
                ]
            },
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "direct_answer"
    assert normalized.context_binding.source == "last_turn"
    assert normalized.context_binding.subject_hint == "AAPL"
    assert normalized.needs_tools is False


def test_context_router_keeps_history_ticker_in_last_turn_subject_hint():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )
    from langchain_core.messages import AIMessage, HumanMessage

    decision = ConversationDecision(
        execution_route="direct_answer",
        context_binding=ContextBinding(
            source="last_turn",
            confidence=0.9,
            subject_hint="Apple China iPhone 17 Discounts News",
        ),
        relation="follow_up",
        domain_intent="analysis",
        confidence=0.9,
        needs_tools=False,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "What does that imply for margins?",
            "messages": [
                HumanMessage(content="AAPL latest news with links."),
                AIMessage(content="Apple China iPhone 17 discounts were the selected news item."),
            ],
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "direct_answer"
    assert normalized.context_binding.source == "last_turn"
    assert "AAPL" in normalized.context_binding.subject_hint
    assert "Apple China iPhone 17 Discounts News" in normalized.context_binding.subject_hint


def test_context_router_style_only_market_mechanism_news_decision_stays_chat():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="growth stocks"),
        relation="new_topic",
        domain_intent="news",
        confidence=0.78,
        needs_tools=True,
        task_hints=(
            {
                "subject_type": "theme",
                "subject_label": "growth stocks",
                "operation": "fetch",
                "params": {"topic": "news"},
            },
        ),
    )

    normalized = normalize_context_decision(
        decision,
        {"query": "Answer in English, very short: why did growth stocks wobble?", "messages": []},
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "direct_answer"
    assert normalized.needs_tools is False
    assert normalized.task_hints == ()
    assert normalized.context_binding.source == "none"


def test_context_router_no_news_theme_research_decision_stays_chat():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="semiconductors"),
        relation="new_topic",
        domain_intent="news",
        confidence=0.78,
        needs_tools=True,
        task_hints=(
            {
                "subject_type": "theme",
                "subject_label": "semiconductors",
                "operation": "fetch",
                "params": {"topic": "news"},
            },
        ),
    )

    normalized = normalize_context_decision(
        decision,
        {"query": "Do not look up news. Just tell me why semiconductors can sell off together.", "messages": []},
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "direct_answer"
    assert normalized.needs_tools is False
    assert normalized.task_hints == ()


def test_context_router_resolved_bound_clarify_continues_conversation():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )
    from langchain_core.messages import AIMessage, HumanMessage

    decision = ConversationDecision(
        execution_route="clarify",
        context_binding=ContextBinding(
            source="last_turn",
            confidence=0.82,
            subject_hint="GOOGL",
            reason="the follow-up is anchored to the previous turn",
        ),
        relation="follow_up",
        domain_intent="unknown",
        confidence=0.7,
        needs_tools=False,
        reply_guidance="Need the referenced object.",
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "帮我算一下这个",
            "messages": [
                HumanMessage(content="GOOGL current price, short answer."),
                AIMessage(content="GOOGL 最新价格约为 400.80 USD。"),
            ],
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "direct_answer"
    assert normalized.context_binding.source == "last_turn"
    assert normalized.context_binding.subject_hint == "GOOGL"
    assert normalized.needs_tools is False


def test_route_conversation_normalizes_llm_clarify_when_context_is_bound(monkeypatch):
    import backend.llm_config as llm_config
    from backend.graph.nodes.conversation_router import route_conversation
    from langchain_core.messages import AIMessage, HumanMessage

    class _Resp:
        content = """
        {
          "execution_route": "clarify",
          "context_binding": {
            "source": "last_turn",
            "confidence": 0.82,
            "reason": "The user is continuing from the previous GOOGL answer.",
            "subject_hint": "GOOGL"
          },
          "relation": "follow_up",
          "domain_intent": "unknown",
          "confidence": 0.7,
          "needs_tools": false,
          "reason": "The action is terse but the object is bound.",
          "reply_guidance": "Use the recent conversation to infer the requested action."
        }
        """

    class _FakeLLM:
        async def ainvoke(self, _messages):
            return _Resp()

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "true")
    monkeypatch.setattr(llm_config, "create_llm", lambda *_args, **_kwargs: _FakeLLM())

    decision = _run(
        route_conversation(
            {
                "query": "帮我算一下这个",
                "ui_context": {},
                "messages": [
                    HumanMessage(content="GOOGL current price, short answer."),
                    AIMessage(content="GOOGL 最新价格约为 400.80 USD。"),
                ],
            },
            tickers=[],
            selection_ids=[],
        )
    )

    assert decision is not None
    assert decision.execution_route == "direct_answer"
    assert decision.context_binding.source == "last_turn"
    assert decision.context_binding.subject_hint == "GOOGL"


def test_route_conversation_deictic_without_context_clarifies_without_llm(monkeypatch):
    import backend.llm_config as llm_config
    from backend.graph.nodes.conversation_router import route_conversation

    def fail_create_llm(*_args, **_kwargs):
        raise AssertionError("unbound deictic follow-up should not spend a router LLM call")

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "true")
    monkeypatch.setattr(llm_config, "create_llm", fail_create_llm)

    decision = _run(
        route_conversation(
            {"query": "Can you expand that?", "ui_context": {}, "messages": []},
            tickers=[],
            selection_ids=[],
        )
    )

    assert decision is not None
    assert decision.execution_route == "clarify"
    assert decision.context_binding.source == "none"
    assert decision.needs_tools is False


def test_route_conversation_explicit_technical_query_uses_fast_path_without_llm(monkeypatch):
    import backend.llm_config as llm_config
    from backend.graph.nodes.conversation_router import route_conversation

    def fail_create_llm(*_args, **_kwargs):
        raise AssertionError("explicit technical requests should not spend a router LLM call")

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "true")
    monkeypatch.setattr(llm_config, "create_llm", fail_create_llm)

    decision = _run(
        route_conversation(
            {
                "query": "INTC 现在技术面怎么样？请结合均线、RSI、MACD、成交量、支撑阻力和当前价格给出可执行结论。",
                "ui_context": {},
                "messages": [],
            },
            tickers=["INTC"],
            selection_ids=[],
        )
    )

    assert decision is not None
    assert decision.execution_route == "research"
    assert decision.needs_tools is True
    assert decision.domain_intent == "analysis"
    assert decision.task_hints
    assert decision.task_hints[0]["operation"] == "technical"
    assert decision.task_hints[0]["tickers"] == ["INTC"]


def test_route_conversation_explicit_earnings_query_uses_fast_path_without_llm(monkeypatch):
    import backend.llm_config as llm_config
    from backend.graph.nodes.conversation_router import route_conversation

    def fail_create_llm(*_args, **_kwargs):
        raise AssertionError("explicit earnings performance requests should not spend a router LLM call")

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "true")
    monkeypatch.setattr(llm_config, "create_llm", fail_create_llm)

    decision = _run(
        route_conversation(
            {
                "query": "英伟达最新季度财报表现如何",
                "ui_context": {},
                "messages": [],
            },
            tickers=["NVDA"],
            selection_ids=[],
        )
    )

    assert decision is not None
    assert decision.execution_route == "research"
    assert decision.needs_tools is True
    assert decision.domain_intent == "analysis"
    assert decision.reason == "explicit earnings performance request fast path"
    assert decision.task_hints
    assert decision.task_hints[0]["operation"] == "earnings_performance"
    assert decision.task_hints[0]["tickers"] == ["NVDA"]


def test_route_conversation_explicit_earnings_impact_query_uses_fast_path_without_llm(monkeypatch):
    import backend.llm_config as llm_config
    from backend.graph.nodes.conversation_router import route_conversation

    def fail_create_llm(*_args, **_kwargs):
        raise AssertionError("explicit earnings impact requests should not spend a router LLM call")

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "true")
    monkeypatch.setattr(llm_config, "create_llm", fail_create_llm)

    decision = _run(
        route_conversation(
            {
                "query": "请问英伟达这个季度财报对股价的影响",
                "ui_context": {},
                "messages": [],
            },
            tickers=["NVDA"],
            selection_ids=[],
        )
    )

    assert decision is not None
    assert decision.execution_route == "research"
    assert decision.needs_tools is True
    assert decision.reason == "explicit earnings impact request fast path"
    assert decision.task_hints
    assert decision.task_hints[0]["operation"] == "earnings_impact"
    assert decision.task_hints[0]["tickers"] == ["NVDA"]


def test_route_conversation_explicit_report_mode_uses_fast_path_without_llm(monkeypatch):
    import backend.llm_config as llm_config
    from backend.graph.nodes.conversation_router import route_conversation

    def fail_create_llm(*_args, **_kwargs):
        raise AssertionError("explicit report mode with a ticker should not spend a router LLM call")

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "true")
    monkeypatch.setattr(llm_config, "create_llm", fail_create_llm)

    decision = _run(
        route_conversation(
            {
                "query": "请给我一份 INTC 深度投资报告，覆盖财报、竞争、估值和分析师评级。",
                "output_mode": "investment_report",
                "ui_context": {},
                "messages": [],
            },
            tickers=["INTC"],
            selection_ids=[],
        )
    )

    assert decision is not None
    assert decision.execution_route == "research"
    assert decision.needs_tools is True
    assert decision.reason == "explicit report mode fast path"


def test_context_router_single_word_it_prefers_thread_history_over_recent_focus():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(
            source="recent_focus",
            confidence=0.82,
            subject_hint="MSFT",
            reason="older cross-session focus",
        ),
        relation="follow_up",
        domain_intent="analysis",
        confidence=0.78,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "Does it change the margin risk?",
            "ui_context": {
                "view": "chat",
                "session_history": [
                    {"role": "user", "content": "AAPL latest news with links.", "tickers": "AAPL"},
                    {"role": "assistant", "content": "AAPL supplier guidance may affect margins."},
                ],
            },
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.context_binding.source == "last_turn"
    assert normalized.context_binding.subject_hint == "AAPL"


def test_context_router_resolved_followup_research_without_grounding_returns_to_chat():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )
    from langchain_core.messages import AIMessage, HumanMessage

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(
            source="last_turn",
            confidence=0.9,
            subject_hint="GOOGL",
            reason="the user is continuing the previous GOOGL answer",
        ),
        relation="follow_up",
        domain_intent="quote",
        confidence=0.88,
        needs_tools=True,
        task_hints=(
            {"subject_type": "company", "subject_label": "GOOGL", "operation": "price"},
            {"subject_type": "company", "subject_label": "GOOGL", "operation": "fetch", "params": {"topic": "news"}},
        ),
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "Use 307 as my reference level and calculate the gap. Do not ask which stock again.",
            "messages": [
                HumanMessage(content="GOOGL current price, short answer."),
                AIMessage(content="GOOGL latest price is about 400.80 USD."),
            ],
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "direct_answer"
    assert normalized.context_binding.source == "last_turn"
    assert normalized.context_binding.subject_hint == "GOOGL"
    assert normalized.needs_tools is False
    assert normalized.task_hints == ()


def test_context_router_resolved_quote_request_stays_research_when_query_asks_price():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )
    from langchain_core.messages import AIMessage, HumanMessage

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(
            source="last_turn",
            confidence=0.9,
            subject_hint="GOOGL",
            reason="the user is continuing the previous GOOGL answer",
        ),
        relation="follow_up",
        domain_intent="quote",
        confidence=0.88,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "What price is it?",
            "messages": [
                HumanMessage(content="Let's talk about GOOGL."),
                AIMessage(content="Sure, we can discuss GOOGL."),
            ],
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "research"
    assert normalized.needs_tools is True


def test_context_router_resolved_followup_keeps_user_action_task_hints():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )
    from langchain_core.messages import AIMessage, HumanMessage

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(
            source="last_turn",
            confidence=0.9,
            subject_hint="AAPL",
            reason="the user is continuing the previous AAPL answer",
        ),
        relation="follow_up",
        domain_intent="unknown",
        confidence=0.82,
        needs_tools=True,
        task_hints=(
            {"subject_type": "company", "subject_label": "AAPL", "operation": "alert_set", "params": {"threshold": 180}},
        ),
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "Also remind me below 180.",
            "messages": [
                HumanMessage(content="AAPL current price."),
                AIMessage(content="AAPL is trading around 293.32 USD."),
            ],
        },
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "research"
    assert normalized.needs_tools is True
    assert normalized.task_hints == decision.task_hints


def test_context_router_current_query_ticker_overrides_session_history():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(source="last_turn", confidence=0.8, subject_hint="AAPL"),
        relation="follow_up",
        domain_intent="analysis",
        confidence=0.78,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "NVDA 的风险主要在哪？",
            "messages": [],
            "ui_context": {
                "session_history": [
                    {"role": "user", "content": "AAPL 最近新闻怎么看？", "tickers": "AAPL"},
                    {"role": "assistant", "content": "AAPL 主要看新品、服务收入和监管新闻。"},
                ]
            },
        },
        tickers=["NVDA"],
        selection_ids=[],
    )

    assert normalized.context_binding.source == "none"
    assert normalized.context_binding.subject_hint == "NVDA"


def test_context_router_named_analytical_followup_keeps_context_without_tools():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )
    from langchain_core.messages import AIMessage, HumanMessage

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="NVDA, MSFT"),
        relation="compare",
        domain_intent="analysis",
        confidence=0.85,
        needs_tools=True,
    )

    normalized = normalize_context_decision(
        decision,
        {
            "query": "So does that hurt NVDA more than MSFT?",
            "messages": [
                HumanMessage(content="Can you explain why high rates pressure growth stocks?"),
                AIMessage(content="High rates pressure growth stocks by raising discount rates."),
            ],
        },
        tickers=["NVDA", "MSFT"],
        selection_ids=[],
    )

    assert normalized.execution_route == "direct_answer"
    assert normalized.context_binding.source == "last_turn"
    assert normalized.context_binding.subject_hint == "NVDA, MSFT"
    assert normalized.needs_tools is False


def test_context_router_visible_portfolio_context_turns_clarify_into_research():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="clarify",
        context_binding=ContextBinding(source="portfolio", confidence=0.2),
        relation="new_topic",
        domain_intent="unknown",
        confidence=0.4,
        needs_tools=False,
        task_hints=(
            {
                "subject_type": "portfolio",
                "subject_label": "当前持仓",
                "tickers": ["AAPL"],
                "operation": "analyze_impact",
                "params": {},
            },
        ),
    )

    normalized = normalize_context_decision(
        decision,
        {"query": "这些新闻对我的持仓影响大吗？", "ui_context": {"positions": [{"ticker": "AAPL"}]}},
        tickers=[],
        selection_ids=[],
    )

    assert normalized.execution_route == "research"
    assert normalized.context_binding.source == "portfolio"
    assert normalized.domain_intent == "portfolio"
    assert normalized.needs_tools is True


def test_context_router_accepts_llm_safety_decision_without_tools():
    from backend.graph.nodes.conversation_router import _coerce_decision

    decision = _coerce_decision(
        {
            "execution_route": "direct_answer",
            "context_binding": {"source": "none"},
            "relation": "new_topic",
            "domain_intent": "analysis",
            "confidence": 0.92,
            "needs_tools": False,
            "reason": "用户要求确定性收益承诺，应由直接回复层自然拒绝并转为风险框架。",
            "reply_guidance": "不要承诺必涨，改为说明可按候选池做证据和风险比较。",
        }
    )

    assert decision.execution_route == "direct_answer"
    assert decision.needs_tools is False
    assert "必涨" in decision.reply_guidance


def test_context_router_blocks_insider_information_requests_from_research():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        normalize_context_decision,
    )

    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="AAPL"),
        relation="new_topic",
        domain_intent="news",
        confidence=0.9,
        needs_tools=True,
        task_hints=(
            {
                "subject_type": "company",
                "subject_label": "AAPL",
                "tickers": ["AAPL"],
                "operation": "fetch",
                "params": {"topic": "earnings insider information"},
            },
        ),
    )

    normalized = normalize_context_decision(
        decision,
        {"query": "I need insider information on AAPL earnings.", "messages": []},
        tickers=["AAPL"],
        selection_ids=[],
    )

    assert normalized.execution_route == "direct_answer"
    assert normalized.context_binding.source == "none"
    assert normalized.context_binding.subject_hint == "AAPL"
    assert normalized.needs_tools is False
    assert normalized.task_hints == ()


def test_context_router_switch_query_keeps_only_current_effective_ticker():
    from backend.graph.nodes.conversation_router import (
        ContextBinding,
        ConversationDecision,
        _effective_current_turn_tickers,
        normalize_context_decision,
    )

    query = "算了不看苹果了，还是看微软，不对先看谷歌今天有没有大新闻。"
    decision = ConversationDecision(
        execution_route="research",
        context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="GOOGL"),
        relation="new_topic",
        domain_intent="news",
        confidence=0.9,
        needs_tools=True,
    )

    assert _effective_current_turn_tickers(query, ["AAPL", "MSFT", "GOOGL"], decision) == ["GOOGL"]

    normalized = normalize_context_decision(
        decision,
        {"query": query, "messages": []},
        tickers=["AAPL", "MSFT", "GOOGL"],
        selection_ids=[],
    )
    assert normalized.context_binding.source == "none"
    assert normalized.context_binding.subject_hint == "GOOGL"


def test_understand_request_uses_context_binding_for_direct_report_discussion(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == []
        assert selection_ids == []
        return ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(
                source="last_report",
                confidence=0.92,
                subject_hint="Apple report",
                reason="用户接着最近报告追问",
            ),
            relation="follow_up",
            domain_intent="report_discussion",
            confidence=0.9,
            needs_tools=False,
            reason="报告上下文可直接回答",
        )

    async def fake_reply(_state, decision):
        assert decision.context_binding.source == "last_report"
        return "这份报告最大的风险是估值对利率变化敏感。"

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)
    monkeypatch.setattr(understand_mod, "generate_contextual_reply", fake_reply)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "最大的风险展开说说",
                "ui_context": {},
                "output_mode": "chat",
                "memory_context": {
                    "last_report": {
                        "title": "Apple report",
                        "summary": "Apple summary",
                    }
                },
                "trace": {},
            }
        )
    )

    assert result["chat_responded"] is True
    assert result["understanding"]["route"] == "direct"
    assert "估值对利率变化敏感" in result["artifacts"]["draft_markdown"]
    decision = result["artifacts"]["conversation_decision"]
    assert decision["execution_route"] == "direct_answer"
    assert decision["context_binding"]["source"] == "last_report"


def test_understand_request_sanitizes_direct_chat_template_markers(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == ["NVDA", "AMD", "TSM"]
        assert selection_ids == []
        return ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="NVDA, AMD, TSM"),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.9,
            needs_tools=False,
            reason="direct conceptual comparison can answer from context",
        )

    async def fake_reply(_state, _decision):
        return "The core 问题：semiconductor ETFs are a concentrated AI-cycle bet.\n后续关注：valuation and demand."

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)
    monkeypatch.setattr(understand_mod, "generate_contextual_reply", fake_reply)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "Use NVDA, AMD, and TSM as proxies. Keep it short.",
                "ui_context": {},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    markdown = result["artifacts"]["draft_markdown"]
    assert result["understanding"]["route"] == "direct"
    assert "问题：" not in markdown
    assert "后续关注：" not in markdown
    assert "关键点：" in markdown
    assert "后续观察：" in markdown
    assert markdown.startswith("Using NVDA, AMD, TSM as the representative set:")
    assert result["messages"][-1].content == markdown


def test_understand_request_strips_research_confirmation_cta_from_direct_reply(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == ["INTC"]
        assert selection_ids == []
        return ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="INTC"),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.86,
            needs_tools=False,
            reason="router says direct conceptual framing",
        )

    async def fake_reply(_state, _decision):
        return (
            "可以先从产品周期、竞争格局和估值三条线看。\n\n"
            "你希望我首先启动研究，为你获取英特尔的最新实时技术指标和基本面数据，然后我们再一起逐一深入分析每个部分吗？"
            "或者你可以指定一个你最想先深入探讨的维度。"
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)
    monkeypatch.setattr(understand_mod, "generate_contextual_reply", fake_reply)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "INTC 先按产品周期和竞争格局给我一个简短框架。",
                "ui_context": {},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    markdown = result["artifacts"]["draft_markdown"]
    assert result["understanding"]["route"] == "direct"
    assert "可以先从产品周期" in markdown
    assert "启动研究" not in markdown
    assert "最新实时" not in markdown
    assert "你希望" not in markdown


def test_understand_request_no_news_mechanism_falls_back_to_direct_when_router_unavailable(monkeypatch):
    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == []
        assert selection_ids == []
        return None

    async def fake_reply(_state, _decision):
        return "Semiconductors can sell off together when investors de-risk the whole group."

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)
    monkeypatch.setattr(understand_mod, "generate_contextual_reply", fake_reply)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "Do not look up news. Just tell me why semiconductors can sell off together.",
                "ui_context": {},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    assert result["understanding"]["route"] == "direct"
    assert result["tasks"] == []
    assert result["chat_responded"] is True
    assert result["reply_contract"]["source_constraints"]["disallow_news"] is True


def test_understand_request_history_followup_falls_back_to_direct_when_router_unavailable(monkeypatch):
    from langchain_core.messages import AIMessage, HumanMessage

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == []
        assert selection_ids == []
        return None

    async def fake_reply(_state, decision):
        assert decision.context_binding.source == "last_turn"
        assert "GOOGL" in decision.context_binding.subject_hint
        return "Using the prior GOOGL quote, the gap from 307 is about 93.80."

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)
    monkeypatch.setattr(understand_mod, "generate_contextual_reply", fake_reply)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "Use 307 as my reference level and calculate the gap. Do not ask which stock again.",
                "ui_context": {},
                "output_mode": "chat",
                "trace": {},
                "messages": [
                    HumanMessage(content="GOOGL current price, short answer."),
                    AIMessage(content="GOOGL latest price is about 400.80 USD."),
                ],
            }
        )
    )

    assert result["understanding"]["route"] == "direct"
    assert result["tasks"] == []
    assert "93.80" in result["artifacts"]["draft_markdown"]


def test_understand_request_direct_followup_keeps_last_turn_binding(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision
    from langchain_core.messages import AIMessage, HumanMessage

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == []
        assert selection_ids == []
        return ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(
                source="last_turn",
                confidence=0.84,
                subject_hint="GOOGL",
                reason="the current turn continues the previous GOOGL answer",
            ),
            relation="follow_up",
            domain_intent="unknown",
            confidence=0.82,
            needs_tools=False,
            reason="same-session context is sufficient for a natural reply",
        )

    async def fake_reply(state, decision):
        assert decision.context_binding.source == "last_turn"
        assert decision.context_binding.subject_hint == "GOOGL"
        history = [
            getattr(message, "content", "")
            for message in (state.get("messages") or [])
            if getattr(message, "content", "")
        ]
        assert any("GOOGL" in str(item) for item in history)
        return "按刚才 GOOGL 的上下文继续算，不需要你再重复标的。"

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)
    monkeypatch.setattr(understand_mod, "generate_contextual_reply", fake_reply)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "帮我算一下这个",
                "ui_context": {},
                "output_mode": "chat",
                "messages": [
                    HumanMessage(content="GOOGL current price, short answer."),
                    AIMessage(content="GOOGL 最新价格约为 400.80 USD。"),
                ],
                "trace": {},
            }
        )
    )

    assert result["chat_responded"] is True
    assert result["understanding"]["route"] == "direct"
    assert result["clarify"]["needed"] is False
    assert "不需要你再重复标的" in ((result.get("artifacts") or {}).get("draft_markdown") or "")
    decision = result["artifacts"]["conversation_decision"]
    assert decision["context_binding"]["source"] == "last_turn"
    assert decision["context_binding"]["subject_hint"] == "GOOGL"


def test_understand_request_quote_label_without_price_request_stays_chat(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision
    from langchain_core.messages import AIMessage, HumanMessage

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == []
        assert selection_ids == []
        return ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(
                source="last_turn",
                confidence=0.9,
                subject_hint="GOOGL",
                reason="the user is continuing the previous GOOGL answer",
            ),
            relation="follow_up",
            domain_intent="quote",
            confidence=0.86,
            needs_tools=False,
            reason="the label is quote-like but the user asked for a contextual calculation",
        )

    async def fake_reply(_state, decision):
        assert decision.domain_intent == "quote"
        return "Using the prior GOOGL context, 400.80 minus 307 is 93.80."

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)
    monkeypatch.setattr(understand_mod, "generate_contextual_reply", fake_reply)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "Use 307 as my reference level and calculate the gap. Do not ask which stock again.",
                "ui_context": {},
                "output_mode": "chat",
                "messages": [
                    HumanMessage(content="GOOGL current price, short answer."),
                    AIMessage(content="GOOGL latest price is about 400.80 USD."),
                ],
                "trace": {},
            }
        )
    )

    assert result["chat_responded"] is True
    assert result["understanding"]["route"] == "direct"
    assert result["tasks"] == []
    assert result["reply_contract"]["lane"] == "chat_answer"


def test_understand_request_leaves_url_fetch_to_tools(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")
    web_mod = importlib.import_module("backend.tools.web")

    def fail_prefetch(*_args, **_kwargs):
        raise AssertionError("understand_request must not fetch URL content before routing")

    async def fake_route(state, *, tickers, selection_ids):
        assert selection_ids == []
        assert (state.get("ui_context") or {}).get("selections") in (None, [])
        assert "https://example.com/aapl-news" in state.get("query", "")
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="URL article"),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.86,
            needs_tools=True,
            task_hints=({"subject_type": "unknown", "subject_label": "URL article", "operation": "qa", "params": {}},),
        )

    monkeypatch.setattr(web_mod, "fetch_url_document", fail_prefetch)
    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "帮我分析这个链接 https://example.com/aapl-news 对苹果有什么影响",
                "ui_context": {},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    tasks = result.get("tasks") or []
    assert tasks
    assert all(not task.get("selection_ids") for task in tasks)
    assert not (result.get("artifacts") or {}).get("url_context")


def test_policy_and_planner_prompt_expose_url_fetch_tool_for_mixed_query():
    from backend.graph.planner_prompt import build_planner_prompt
    from backend.graph.nodes.policy_gate import policy_gate

    state = {
        "query": "看下这个 https://example.com/msft-rates 顺便给 MSFT 价格，再说利率为什么影响它",
        "ui_context": {},
        "output_mode": "chat",
        "subject": {"subject_type": "company", "tickers": ["MSFT"]},
        "operation": {"name": "price", "confidence": 0.8, "params": {}},
        "tasks": [
            {
                "id": "task_1",
                "subject_type": "company",
                "tickers": ["MSFT"],
                "operation": {"name": "price", "confidence": 0.8, "params": {}},
                "status": "ready",
            },
            {
                "id": "task_2",
                "subject_type": "macro",
                "tickers": [],
                "operation": {"name": "analyze_impact", "confidence": 0.8, "params": {}},
                "status": "ready",
            },
        ],
    }

    gated = {**state, **policy_gate(state)}
    allowed_tools = gated["policy"]["allowed_tools"]
    assert "fetch_url_content" in allowed_tools

    prompt = build_planner_prompt({**gated, "output_mode": "chat"})
    assert "fetch_url_content" in prompt
    assert "不要只根据 URL 字面内容臆测文章结论" in prompt


def test_non_financial_open_chat_is_llm_direct_before_planner(monkeypatch):
    from backend.graph import GraphRunner
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == []
        assert selection_ids == []
        return ConversationDecision(
            execution_route="out_of_scope",
            context_binding=ContextBinding(),
            relation="new_topic",
            domain_intent="smalltalk",
            confidence=0.93,
            needs_tools=False,
            reason="非金融娱乐请求，直接用金融助手身份回答",
        )

    async def fake_reply(_state, decision):
        assert decision.execution_route == "out_of_scope"
        return "我不太适合推荐睡前歌曲；如果你想从投资角度看音乐流媒体或版权公司，我可以接着聊。"

    monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "true")
    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)
    monkeypatch.setattr(understand_mod, "generate_contextual_reply", fake_reply)

    result = _run(
        GraphRunner.create().ainvoke(
            thread_id="tenant1:test:open-chat-direct",
            query="推荐一首适合睡前听的歌。",
            ui_context={},
            output_mode="chat",
        )
    )

    assert result["chat_responded"] is True
    assert result["understanding"]["route"] == "direct"
    assert "睡前歌曲" in result["artifacts"]["draft_markdown"]
    nodes = [s.get("node") for s in (result.get("trace") or {}).get("spans") or []]
    assert "understand_request" in nodes
    assert "policy_gate" not in nodes
    assert "planner" not in nodes


def test_understand_request_can_bind_active_symbol_followup_to_research(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == []
        assert selection_ids == []
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(
                source="active_symbol",
                confidence=0.86,
                subject_hint="NVDA",
                reason="用户用代词接当前标的",
            ),
            relation="follow_up",
            domain_intent="news",
            confidence=0.84,
            needs_tools=True,
            reason="需要当前标的新闻证据",
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "那它最近有什么新闻",
                "ui_context": {"active_symbol": "NVDA"},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    assert result["understanding"]["route"] == "research"
    assert result["subject"]["tickers"] == ["NVDA"]
    assert (result["operation"] or {})["name"] == "fetch"
    assert result["tasks"][0]["reason"] == "context_router_binding"


def test_understand_request_context_binding_wins_over_conflicting_task_hints(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(
                source="active_symbol",
                confidence=0.9,
                subject_hint="NVDA",
                reason="scoped UI anchor",
            ),
            relation="follow_up",
            domain_intent="news",
            confidence=0.9,
            needs_tools=True,
            task_hints=(
                {
                    "subject_type": "company",
                    "subject_label": "AAPL",
                    "tickers": ["AAPL"],
                    "operation": "fetch",
                    "params": {"topic": "news"},
                },
            ),
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "那它最近有什么新闻？",
                "ui_context": {"active_symbol": "NVDA", "view": "dashboard"},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    assert result["subject"]["tickers"] == ["NVDA"]
    assert [task["tickers"] for task in result["tasks"]] == [["NVDA"]]
    assert result["tasks"][0]["reason"] == "context_router_binding"


def test_understand_request_global_active_symbol_does_not_bypass_history_when_router_unbound(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", confidence=0.0),
            relation="follow_up",
            domain_intent="news",
            confidence=0.74,
            needs_tools=True,
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "那它最近有什么新闻？",
                "ui_context": {"active_symbol": "NVDA", "view": "chat"},
                "memory_context": {"current_thread_focus": {"ticker": "AAPL", "query": "AAPL 最近新闻"}},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    assert result["subject"]["tickers"] != ["NVDA"]
    assert result["blocked_tasks"] or result["subject"]["tickers"] == []


def test_understand_request_can_bind_last_report_followup_to_research(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == []
        assert selection_ids == []
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(
                source="last_report",
                confidence=0.88,
                subject_hint="Apple investment report",
                reason="用户要求用最新数据更新报告里的风险判断",
            ),
            relation="follow_up",
            domain_intent="news",
            confidence=0.83,
            needs_tools=True,
            reason="报告上下文绑定到 AAPL，且需要新闻证据",
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "用最新新闻更新一下刚才那份报告里的风险判断",
                "ui_context": {},
                "output_mode": "chat",
                "memory_context": {
                    "last_report": {
                        "title": "Apple investment report",
                        "ticker": "AAPL",
                        "summary": "Apple summary",
                    }
                },
                "trace": {},
            }
        )
    )

    assert result["understanding"]["route"] == "research"
    assert result["subject"]["tickers"] == ["AAPL"]
    assert (result["operation"] or {})["name"] == "fetch"
    assert result["tasks"][0]["params"]["context_binding"]["source"] == "last_report"


def test_understand_request_can_bind_recent_focus_to_research(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision
    from langchain_core.messages import AIMessage, HumanMessage

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == []
        assert selection_ids == []
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(
                source="recent_focus",
                confidence=0.81,
                subject_hint="MSFT",
                reason="用户追问当前线程最近关注对象",
            ),
            relation="elaborate",
            domain_intent="analysis",
            confidence=0.78,
            needs_tools=True,
            reason="需要继续分析最近关注标的",
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "那这个继续展开，为什么市场这么看？",
                "ui_context": {},
                "output_mode": "chat",
                "messages": [
                    HumanMessage(content="MSFT 最近新闻怎么看？"),
                    AIMessage(content="MSFT 主要看 Azure 和 AI 资本开支。"),
                    HumanMessage(content="那这个继续展开，为什么市场这么看？"),
                ],
                "memory_context": {
                    "historical_focus_memory": {
                        "recent_focuses": [{"ticker": "NVDA", "query": "别的会话英伟达新闻"}]
                    }
                },
                "trace": {},
            }
        )
    )

    assert result["understanding"]["route"] == "research"
    assert result["subject"]["tickers"] == ["MSFT"]
    assert (result["operation"] or {})["name"] == "qa"


def test_understand_request_switch_query_uses_effective_current_ticker(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert set(tickers) == {"AAPL", "MSFT", "GOOGL"}
        assert selection_ids == []
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="GOOGL"),
            relation="new_topic",
            domain_intent="news",
            confidence=0.9,
            needs_tools=True,
            reason="用户最终要求看谷歌新闻",
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "算了不看苹果了，还是看微软，不对先看谷歌今天有没有大新闻。",
                "ui_context": {},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    assert result["understanding"]["route"] == "research"
    assert result["subject"]["tickers"] == ["GOOGL"]
    assert [task["tickers"] for task in result["tasks"]] == [["GOOGL"]]


def test_understand_request_router_quote_intent_overrides_multi_ticker_compare(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert set(tickers) == {"AAPL", "MSFT", "GOOGL"}
        assert selection_ids == []
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="AAPL, MSFT, GOOGL"),
            relation="new_topic",
            domain_intent="quote",
            confidence=0.9,
            needs_tools=True,
            reason="user asks current prices for each named ticker",
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "苹果、微软、谷歌现在分别多少？",
                "ui_context": {},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    assert result["understanding"]["route"] == "research"
    assert result["subject"]["tickers"] == ["AAPL", "MSFT", "GOOGL"]
    assert (result["operation"] or {})["name"] == "price"
    assert [task["tickers"] for task in result["tasks"]] == [["AAPL"], ["MSFT"], ["GOOGL"]]
    assert [(task.get("operation") or {}).get("name") for task in result["tasks"]] == ["price", "price", "price"]


def test_understand_request_splits_multi_ticker_router_price_hint(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert set(tickers) == {"AAPL", "MSFT", "GOOGL"}
        assert selection_ids == []
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="AAPL, MSFT, GOOGL"),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.9,
            needs_tools=True,
            reason="router decomposed a quote request into one multi-symbol price hint",
            task_hints=(
                {
                    "subject_type": "company",
                    "subject_label": "AAPL, MSFT, GOOGL",
                    "tickers": ["AAPL", "MSFT", "GOOGL"],
                    "operation": "price",
                    "params": {},
                },
            ),
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "What are AAPL, MSFT, and GOOGL trading at now?",
                "ui_context": {},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    assert result["understanding"]["route"] == "research"
    assert result["subject"]["tickers"] == ["AAPL", "MSFT", "GOOGL"]
    assert (result["operation"] or {})["name"] == "price"
    assert [task["tickers"] for task in result["tasks"]] == [["AAPL"], ["MSFT"], ["GOOGL"]]
    assert all((task.get("operation") or {}).get("name") == "price" for task in result["tasks"])
    assert all(task.get("reason") == "intent_contract_projection" for task in result["tasks"])


def test_understand_request_uses_router_task_hints_for_compound_query(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert set(tickers) == {"AAPL", "MSFT"}
        assert selection_ids == []
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="AAPL, MSFT"),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.9,
            needs_tools=True,
            reason="compound request",
            task_hints=(
                {"subject_type": "company", "subject_label": "AAPL", "tickers": ["AAPL"], "operation": "price", "params": {}},
                {"subject_type": "company", "subject_label": "MSFT", "tickers": ["MSFT"], "operation": "fetch", "params": {"topic": "news"}},
                {"subject_type": "macro", "subject_label": "高估值怕利率", "tickers": [], "operation": "analyze_impact", "params": {}},
            ),
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "AAPL 价格、MSFT 新闻、再解释一下为什么高估值怕利率，最后用一句话说我该关注什么。",
                "ui_context": {},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    task_sig = [
        (task["subject_type"], tuple(task.get("tickers") or []), (task.get("operation") or {}).get("name"))
        for task in result["tasks"]
    ]
    assert ("company", ("AAPL",), "price") in task_sig
    assert ("company", ("MSFT",), "fetch") in task_sig
    assert ("macro", (), "macro_brief") in task_sig
    assert all(
        task["reason"] == "intent_contract_projection"
        for task in result["tasks"]
    )


def test_understand_request_projects_direct_decision_with_executable_task_hints(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == ["AAPL"]
        assert selection_ids == []
        return ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="AAPL"),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.9,
            needs_tools=False,
            reason="bad direct choice despite an executable analysis task",
            task_hints=(
                {
                    "subject_type": "company",
                    "subject_label": "AAPL",
                    "tickers": ["AAPL"],
                    "operation": "analyze_impact",
                    "params": {},
                },
            ),
        )

    async def fail_direct_reply(*_args, **_kwargs):
        raise AssertionError("executable task hints must not be swallowed by direct reply")

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)
    monkeypatch.setattr(understand_mod, "generate_contextual_reply", fail_direct_reply)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "帮我分析 AAPL 这轮财报对接下来走势和风险的影响，直接开始做。",
                "ui_context": {},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    assert result["understanding"]["route"] == "research"
    assert result["chat_responded"] is False
    assert result["tasks"]
    # 行为升级（HIGH-1，skill 分支）：query 含"财报…影响"语义时，understand_request
    # 会把通用的 analyze_impact 精化为更具体的 earnings_impact（_specific_company_operations）。
    assert any((task.get("operation") or {}).get("name") == "earnings_impact" for task in result["tasks"])
    # main 的 request-frame evidence 契约：财报+走势+风险的复合诉求需带齐证据义务。
    assert any(
        {"price_snapshot", "risk_profile", "technical_snapshot"}.issubset(_task_required_evidence(task))
        for task in result["tasks"]
    )


def test_understand_request_projects_direct_technical_decision_to_research(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == ["AAPL"]
        assert selection_ids == []
        return ConversationDecision(
            execution_route="direct_answer",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="AAPL"),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.84,
            needs_tools=False,
            reason="router missed technical execution",
        )

    async def fail_direct_reply(*_args, **_kwargs):
        raise AssertionError("technical requests must enter research instead of direct chat")

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)
    monkeypatch.setattr(understand_mod, "generate_contextual_reply", fail_direct_reply)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "AAPL 技术面、期权IV和市场情绪一起看，短一点。",
                "ui_context": {},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    assert result["understanding"]["route"] == "research"
    assert result["tasks"]
    assert any((task.get("operation") or {}).get("name") == "technical" for task in result["tasks"])


def test_understand_request_adds_price_anchor_for_router_fetch_analysis(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert set(tickers) == {"GOOGL", "MSFT"}
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="GOOGL, MSFT"),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.9,
            needs_tools=True,
            task_hints=(
                {
                    "subject_type": "company",
                    "subject_label": "GOOGL",
                    "tickers": ["GOOGL"],
                    "operation": "fetch",
                    "params": {"topic": "news"},
                },
                {
                    "subject_type": "company",
                    "subject_label": "MSFT",
                    "tickers": ["MSFT"],
                    "operation": "fetch",
                    "params": {"topic": "news"},
                },
            ),
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "GOOGL 和 MSFT 今天谁更强，新闻、涨跌幅、风险点各一句。",
                "ui_context": {},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    task_sig = [
        (tuple(task.get("tickers") or []), (task.get("operation") or {}).get("name"), task.get("reason"))
        for task in result["tasks"]
    ]
    assert (("GOOGL", "MSFT"), "compare", "intent_contract_synthesis_compare") in task_sig
    _assert_evidence_task(result, ("GOOGL",), {"price_snapshot", "news_context", "risk_profile"})
    _assert_evidence_task(result, ("MSFT",), {"price_snapshot", "news_context", "risk_profile"})


def test_understand_request_expands_quick_compare_hint_into_support_tasks(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert set(tickers) == {"GOOGL", "MSFT"}
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="GOOGL, MSFT"),
            relation="compare",
            domain_intent="analysis",
            confidence=0.9,
            needs_tools=True,
            task_hints=(
                {
                    "subject_type": "company",
                    "subject_label": "GOOGL 和 MSFT",
                    "tickers": ["GOOGL", "MSFT"],
                    "operation": "compare",
                    "params": {"aspects": ["news", "price_change", "risk"]},
                },
            ),
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "先别做长报告，30秒告诉我 GOOGL 和 MSFT 今天谁更强，新闻、涨跌幅、风险点各一句。",
                "ui_context": {},
                "output_mode": "brief",
                "trace": {},
            }
        )
    )

    task_sig = [
        (tuple(task.get("tickers") or []), (task.get("operation") or {}).get("name"))
        for task in result["tasks"]
    ]
    assert (("GOOGL", "MSFT"), "compare") in task_sig
    _assert_evidence_task(result, ("GOOGL",), {"price_snapshot", "news_context", "risk_profile"})
    _assert_evidence_task(result, ("MSFT",), {"price_snapshot", "news_context", "risk_profile"})


def test_understand_request_fast_brief_with_explicit_tickers_does_not_wait_for_context_router(monkeypatch):
    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fail_route(*_args, **_kwargs):
        raise AssertionError("explicit no-history brief should not call context router")

    monkeypatch.setattr(understand_mod, "route_conversation", fail_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "30秒告诉我 GOOGL 和 MSFT 今天谁更强，新闻、涨跌幅、风险点各一句。",
                "ui_context": {},
                "output_mode": "brief",
                "trace": {},
            }
        )
    )

    task_sig = [
        (tuple(task.get("tickers") or []), (task.get("operation") or {}).get("name"))
        for task in result["tasks"]
    ]
    assert (("GOOGL", "MSFT"), "compare") in task_sig
    _assert_evidence_task(result, ("GOOGL",), {"price_snapshot", "news_context", "risk_profile"})
    _assert_evidence_task(result, ("MSFT",), {"price_snapshot", "news_context", "risk_profile"})


def test_understand_request_honors_router_clarify_even_with_explicit_tickers(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert set(tickers) == {"NVDA", "MSFT"}
        assert selection_ids == []
        return ConversationDecision(
            execution_route="clarify",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="NVDA, MSFT"),
            relation="new_topic",
            domain_intent="unknown",
            confidence=0.3,
            needs_tools=False,
            reason="that cannot be resolved without current-thread context",
            reply_guidance="I need to know what 'that' refers to before comparing NVDA and MSFT.",
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "So does that hurt NVDA more than MSFT?",
                "ui_context": {},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    assert result["understanding"]["route"] == "clarify"
    assert result["tasks"] == []
    assert (result["clarify"] or {}).get("needed") is True
    assert "NVDA" not in (result["artifacts"].get("draft_markdown") or "") or "that" in result["artifacts"]["draft_markdown"]


def test_understand_request_router_analysis_new_topic_uses_light_current_snapshot(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == ["AAPL"]
        assert selection_ids == []
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="AAPL"),
            relation="new_topic",
            domain_intent="analysis",
            confidence=0.8,
            needs_tools=True,
            reason="user wants a short look at Apple with current evidence",
            reply_guidance="Briefly provide current price and key news.",
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "帮我看苹果，对了我没睡好，说短一点。",
                "ui_context": {},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    assert result["understanding"]["route"] == "research"
    assert result["subject"]["tickers"] == ["AAPL"]
    assert (result["operation"] or {}).get("name") == "daily_brief"
    assert [(task.get("operation") or {}).get("name") for task in result["tasks"]] == ["daily_brief"]


def test_understand_request_reconciles_quote_intent_with_generic_qa_hint(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == ["AAPL"]
        assert selection_ids == []
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="none", confidence=0.0, subject_hint="AAPL"),
            relation="new_topic",
            domain_intent="quote",
            confidence=0.82,
            needs_tools=True,
            reason="router says this current company look needs a quote",
            task_hints=(
                {
                    "subject_type": "company",
                    "subject_label": "AAPL",
                    "tickers": ["AAPL"],
                    "operation": "qa",
                    "params": {},
                    "reason": "generic model wording for a current snapshot",
                },
            ),
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "Give me a quick look at AAPL, short.",
                "ui_context": {},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    assert result["understanding"]["route"] == "research"
    assert result["subject"]["tickers"] == ["AAPL"]
    assert (result["operation"] or {}).get("name") == "price"
    assert [(task.get("operation") or {}).get("name") for task in result["tasks"]] == ["price"]


def test_understand_request_can_bind_portfolio_context_to_research(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        assert tickers == []
        assert selection_ids == []
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(
                source="portfolio",
                confidence=0.84,
                subject_hint="当前持仓",
                reason="用户追问持仓影响",
            ),
            relation="follow_up",
            domain_intent="portfolio",
            confidence=0.82,
            needs_tools=True,
            reason="需要按持仓上下文分析",
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "那对我的仓位影响大吗？",
                "ui_context": {"positions": [{"ticker": "AAPL", "shares": 10}, {"ticker": "MSFT", "shares": 5}]},
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    assert result["understanding"]["route"] == "research"
    assert result["subject"]["subject_type"] == "portfolio"
    assert result["subject"]["tickers"] == ["AAPL", "MSFT"]
    assert (result["operation"] or {})["name"] == "portfolio_impact"


def test_understand_request_portfolio_router_clarify_with_positions_becomes_research(monkeypatch):
    from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

    understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

    async def fake_route(_state, *, tickers, selection_ids):
        return ConversationDecision(
            execution_route="research",
            context_binding=ContextBinding(source="portfolio", confidence=0.74, subject_hint="current portfolio"),
            relation="new_topic",
            domain_intent="portfolio",
            confidence=0.72,
            needs_tools=True,
        )

    monkeypatch.setattr(understand_mod, "route_conversation", fake_route)

    result = _run(
        understand_mod.understand_request(
            {
                "query": "这些新闻对我的持仓影响大吗？",
                "ui_context": {
                    "positions": [{"ticker": "AAPL", "weight": 0.35}, {"ticker": "MSFT", "weight": 0.25}],
                    "view": "portfolio",
                },
                "output_mode": "chat",
                "trace": {},
            }
        )
    )

    assert result["understanding"]["route"] == "research"
    assert result["subject"]["subject_type"] == "portfolio"
    assert result["subject"]["tickers"] == ["AAPL", "MSFT"]
    assert result["tasks"][0]["params"]["positions"][0]["weight"] == 0.35

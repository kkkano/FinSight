# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio
import importlib


def _run(coro):
    return asyncio.run(coro)


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
    assert decision.execution_route == "research"
    assert decision.needs_tools is True


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
    assert decision.execution_route == "research"
    assert decision.needs_tools is True


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

    assert normalized.context_binding.source == "recent_focus"
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
                "last_report": {
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
            "memory_context": {"last_report": {"ticker": "AAPL", "title": "AAPL report"}},
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
            "memory_context": {"last_report": {"ticker": "AAPL", "title": "AAPL report"}},
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
            "memory_context": {"last_focus": {"ticker": "NVDA", "query": "NVDA 新闻"}},
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

    assert normalized.execution_route == "research"
    assert normalized.context_binding.source == "last_turn"
    assert normalized.context_binding.subject_hint == "AAPL"


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
                "memory_context": {"last_focus": {"ticker": "AAPL", "query": "AAPL 最近新闻"}},
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
                "memory_context": {"recent_focuses": [{"ticker": "NVDA", "query": "别的会话英伟达新闻"}]},
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
    assert ("company", ("MSFT",), "price") in task_sig
    assert ("macro", (), "analyze_impact") in task_sig
    assert all(
        task["reason"] in {"conversation_router_task_hint", "conversation_router_task_hint_support"}
        for task in result["tasks"]
    )


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
    assert (("GOOGL",), "fetch", "conversation_router_task_hint") in task_sig
    assert (("MSFT",), "fetch", "conversation_router_task_hint") in task_sig
    assert (("GOOGL",), "price", "conversation_router_task_hint_support") in task_sig
    assert (("MSFT",), "price", "conversation_router_task_hint_support") in task_sig


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
    assert (("GOOGL",), "price") in task_sig
    assert (("MSFT",), "price") in task_sig
    assert (("GOOGL",), "fetch") in task_sig
    assert (("MSFT",), "fetch") in task_sig
    assert (("GOOGL", "MSFT"), "compare") in task_sig


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
    assert (("GOOGL",), "price") in task_sig
    assert (("GOOGL",), "fetch") in task_sig
    assert (("MSFT",), "price") in task_sig
    assert (("MSFT",), "fetch") in task_sig


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

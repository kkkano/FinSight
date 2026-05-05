# -*- coding: utf-8 -*-
"""
End-to-end tests: greeting / casual queries short-circuit at chat_respond
and never reach resolve_subject / clarify / planner.
"""

import asyncio
import importlib

import pytest


def _run(coro):
    return asyncio.run(coro)


class TestGreetingShortCircuit:
    """Greetings must exit at chat_respond -> END, skipping analytical pipeline."""

    @pytest.mark.parametrize(
        "query",
        [
            "你好",
            "hello",
            "hi",
            "嗨",
            "早上好",
        ],
    )
    def test_greeting_exits_early(self, query: str):
        from backend.graph import GraphRunner

        runner = GraphRunner.create()
        result = _run(
            runner.ainvoke(
                thread_id=f"t-greet-{query}",
                query=query,
                ui_context={"active_symbol": "GOOGL"},  # should be ignored
            )
        )

        assert result.get("chat_responded") is True

        md = (result.get("artifacts") or {}).get("draft_markdown", "")
        assert isinstance(md, str) and len(md) > 5

        trace = result.get("trace") or {}
        spans = trace.get("spans") or []
        nodes = [s.get("node") for s in spans]
        assert "chat_respond" in nodes
        assert "resolve_subject" not in nodes
        assert "clarify" not in nodes
        assert "planner" not in nodes

    @pytest.mark.parametrize(
        "query",
        [
            "谢谢",
            "再见",
            "ok",
            "测试",
        ],
    )
    def test_pure_casual_chat_exits_early(self, query: str):
        from backend.graph import GraphRunner

        runner = GraphRunner.create()
        result = _run(
            runner.ainvoke(
                thread_id=f"t-casual-{query}",
                query=query,
                ui_context={"active_symbol": "TSLA"},
            )
        )

        assert result.get("chat_responded") is True
        md = (result.get("artifacts") or {}).get("draft_markdown", "")
        assert isinstance(md, str) and len(md) > 2

        trace = result.get("trace") or {}
        spans = trace.get("spans") or []
        nodes = [s.get("node") for s in spans]
        assert "resolve_subject" not in nodes
        assert "planner" not in nodes

    @pytest.mark.parametrize(
        "query",
        [
            "你是谁",
            "你好，你能帮我做什么？",
            "推荐一首适合睡前听的歌。",
        ],
    )
    def test_open_chat_goes_to_llm_router_not_local_short_circuit(self, query: str, monkeypatch):
        from backend.graph import GraphRunner
        from backend.graph.nodes.conversation_router import ContextBinding, ConversationDecision

        async def fake_route(_state, *, tickers, selection_ids):
            assert tickers == []
            assert selection_ids == []
            return ConversationDecision(
                execution_route="out_of_scope" if "歌" in query else "direct_answer",
                context_binding=ContextBinding(),
                domain_intent="smalltalk",
                confidence=0.9,
                needs_tools=False,
                reason="LLM router handles open chat before planner",
            )

        async def fake_reply(_state, _decision):
            if "歌" in query:
                return "我不太适合推荐歌曲，但可以把音乐平台或版权公司的变化转成投资视角来聊。"
            return "我是 FinSight，可以自然聊天，也可以在需要行情、新闻或报告证据时再进入研究流程。"

        understand_mod = importlib.import_module("backend.graph.nodes.understand_request")

        monkeypatch.setenv("FINSIGHT_CONTEXT_ROUTER_ENABLED", "true")
        monkeypatch.setattr(understand_mod, "route_conversation", fake_route)
        monkeypatch.setattr(understand_mod, "generate_contextual_reply", fake_reply)

        result = _run(
            GraphRunner.create().ainvoke(
                thread_id=f"t-open-chat-{hash(query)}",
                query=query,
                ui_context={"active_symbol": "TSLA"},
            )
        )

        assert result.get("chat_responded") is True
        md = (result.get("artifacts") or {}).get("draft_markdown", "")
        assert "FinSight" in md or "投资视角" in md

        nodes = [s.get("node") for s in (result.get("trace") or {}).get("spans") or []]
        assert "chat_respond" in nodes
        assert "understand_request" in nodes
        assert "planner" not in nodes
        assert "conversation_decision" in (result.get("artifacts") or {})


class TestAnalyticalQueryPassThrough:
    """Analytical queries must NOT short-circuit — they pass through to resolve_subject."""

    @pytest.mark.parametrize(
        "query",
        [
            "分析 AAPL",
            "NVDA 最新股价和技术面分析",
            "帮我看看特斯拉",
        ],
    )
    def test_analytical_not_short_circuited(self, query: str):
        from backend.graph import GraphRunner

        runner = GraphRunner.create()
        result = _run(
            runner.ainvoke(
                thread_id=f"t-anal-{hash(query)}",
                query=query,
                ui_context={"active_symbol": "AAPL"},
            )
        )

        assert result.get("chat_responded") is not True

        trace = result.get("trace") or {}
        spans = trace.get("spans") or []
        nodes = [s.get("node") for s in spans]
        # 2026-05-03: front-half nodes were collapsed into understand_request,
        # so the legacy resolve_subject assertion is replaced by the new node.
        assert "understand_request" in nodes
        assert "chat_respond" in nodes


class TestGreetingWithActiveSymbol:
    """
    Critical regression: greeting + active_symbol should NOT trigger full analysis.
    """

    def test_hello_with_googl_active_symbol(self):
        from backend.graph import GraphRunner

        runner = GraphRunner.create()
        result = _run(
            runner.ainvoke(
                thread_id="t-bug-regression",
                query="你好",
                ui_context={"active_symbol": "GOOGL"},
            )
        )

        assert result.get("chat_responded") is True

        subject = result.get("subject") or {}
        assert subject.get("subject_type") != "company"
        assert "GOOGL" not in (subject.get("tickers") or [])

        trace = result.get("trace") or {}
        spans = trace.get("spans") or []
        nodes = [s.get("node") for s in spans]
        assert "resolve_subject" not in nodes


class TestCasualDoesNotPolluteMessages:
    """Casual queries should not accumulate in history when skip mode is enabled."""

    def test_casual_query_removed_from_messages(self):
        from backend.graph import GraphRunner

        runner = GraphRunner.create()
        thread_id = "t-casual-cleanup"

        state1 = _run(runner.ainvoke(thread_id=thread_id, query="分析 AAPL", ui_context={"active_symbol": "AAPL"}))
        count_before = len(state1.get("messages") or [])

        state2 = _run(runner.ainvoke(thread_id=thread_id, query="你好", ui_context={"active_symbol": "AAPL"}))
        count_after = len(state2.get("messages") or [])

        assert state2.get("chat_responded") is True
        assert count_after == count_before

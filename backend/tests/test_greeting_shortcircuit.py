# -*- coding: utf-8 -*-
"""
End-to-end tests: greeting / casual queries short-circuit at chat_respond
and never reach resolve_subject / clarify / planner.
"""

import asyncio

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
            "你是谁",
            "ok",
            "测试",
        ],
    )
    def test_casual_chat_exits_early(self, query: str):
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
        assert "resolve_subject" in nodes
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

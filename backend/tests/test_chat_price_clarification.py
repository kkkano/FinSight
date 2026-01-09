#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for price query clarification and fallback behavior.
"""

from backend.handlers.chat_handler import ChatHandler


class StubResult:
    def __init__(self, success: bool, error: str = "") -> None:
        self.success = success
        self.error = error
        self.source = "orchestrator"


class StubOrchestrator:
    def fetch(self, kind: str, ticker: str):  # pragma: no cover - trivial stub
        return StubResult(success=False, error="fetch failed")


class StubTools:
    def get_stock_price(self, ticker: str) -> str:  # pragma: no cover - trivial stub
        return "OK_PRICE"


class DummyHandler(ChatHandler):
    def __init__(self):
        super().__init__(llm=None, orchestrator=None)
        self.tools_module = None

    def _handle_price_query(self, ticker, query, context=None):
        return {"path": "price"}

    def _handle_news_query(self, ticker, query, context=None):
        return {"path": "news"}


def test_price_query_without_ticker_prompts_clarification():
    handler = ChatHandler(llm=None, orchestrator=None)
    handler.tools_module = None
    response = handler.handle("\u5b9e\u65f6\u884c\u60c5\u67e5\u8be2", metadata={}, context=None)
    assert response.get("needs_clarification") is True
    assert "AAPL" in response.get("response", "")


def test_price_query_prefers_price_over_news_keywords():
    handler = DummyHandler()
    response = handler.handle("\u8c37\u6b4c\u6700\u8fd1\u884c\u60c5\u5982\u4f55", metadata={"tickers": ["GOOGL"]}, context=None)
    assert response.get("path") == "price"


def test_orchestrator_failure_falls_back_to_tools():
    handler = ChatHandler(llm=None, orchestrator=StubOrchestrator())
    handler.tools_module = StubTools()
    response = handler._handle_price_query("GOOGL", "price query", None)
    assert response.get("success") is True
    assert response.get("response") == "OK_PRICE"

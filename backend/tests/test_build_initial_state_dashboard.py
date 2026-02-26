# -*- coding: utf-8 -*-
import importlib

from langchain_core.messages import HumanMessage

build_initial_state_module = importlib.import_module(
    "backend.graph.nodes.build_initial_state",
)


def test_dashboard_investment_report_no_longer_forces_skip(monkeypatch):
    monkeypatch.setattr(build_initial_state_module, "load_memory_context", lambda thread_id: None)

    updates = build_initial_state_module.build_initial_state(
        {
            "thread_id": "public:anonymous:test",
            "query": "生成 AAPL 投资报告",
            "output_mode": "investment_report",
            "ui_context": {"source": "dashboard_research_tab"},
        }
    )

    assert "require_confirmation" not in updates
    messages = updates.get("messages") or []
    assert messages and isinstance(messages[0], HumanMessage)


def test_chat_investment_report_keeps_confirmation_default(monkeypatch):
    monkeypatch.setattr(build_initial_state_module, "load_memory_context", lambda thread_id: None)

    updates = build_initial_state_module.build_initial_state(
        {
            "thread_id": "public:anonymous:test",
            "query": "生成 AAPL 投资报告",
            "output_mode": "investment_report",
            "ui_context": {"source": "chat"},
        }
    )

    assert "require_confirmation" not in updates


def test_initial_state_keeps_explicit_confirmation_mode(monkeypatch):
    monkeypatch.setattr(build_initial_state_module, "load_memory_context", lambda thread_id: None)

    updates = build_initial_state_module.build_initial_state(
        {
            "thread_id": "public:anonymous:test",
            "query": "生成 AAPL 投资报告",
            "output_mode": "investment_report",
            "confirmation_mode": "skip",
            "ui_context": {"source": "dashboard_research_tab"},
        }
    )

    assert updates.get("confirmation_mode") == "skip"


def test_initial_state_drops_invalid_confirmation_mode(monkeypatch):
    monkeypatch.setattr(build_initial_state_module, "load_memory_context", lambda thread_id: None)

    updates = build_initial_state_module.build_initial_state(
        {
            "thread_id": "public:anonymous:test",
            "query": "生成 AAPL 投资报告",
            "output_mode": "investment_report",
            "confirmation_mode": "INVALID_MODE",
        }
    )

    assert "confirmation_mode" not in updates

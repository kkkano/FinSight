# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib

from langchain_core.messages import HumanMessage, RemoveMessage, SystemMessage


def test_prepare_context_combines_history_deltas_and_normalizes_ui(monkeypatch):
    first = HumanMessage(content="old", id="m1")
    second = HumanMessage(content="recent", id="m2")
    seen_by_summarize = {}

    def fake_trim(state):
        return {"messages": [RemoveMessage(id="m1")]}

    def fake_summarize(state):
        seen_by_summarize["ids"] = [getattr(msg, "id", None) for msg in state.get("messages") or []]
        return {"messages": [SystemMessage(content="[summary]")]}

    module = importlib.import_module("backend.graph.nodes.prepare_context")
    monkeypatch.setattr(module, "trim_conversation_history", fake_trim)
    monkeypatch.setattr(module, "summarize_history", fake_summarize)

    result = module.prepare_context(
        {
            "messages": [first, second],
            "ui_context": {
                "selections": [
                    {"type": "report", "id": "r1", "title": "A"},
                    {"type": "report", "id": "r1", "title": "A duplicate"},
                ]
            },
        }
    )

    assert seen_by_summarize["ids"] == ["m2"]
    assert isinstance(result["messages"][0], RemoveMessage)
    assert isinstance(result["messages"][1], SystemMessage)
    assert result["ui_context"]["selections"] == [{"type": "doc", "id": "r1", "title": "A"}]

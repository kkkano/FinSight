# -*- coding: utf-8 -*-
from __future__ import annotations

import asyncio

from backend.api import session_context


class _Context:
    def __init__(self) -> None:
        self.cleared = False

    def clear(self) -> None:
        self.cleared = True


def test_clear_session_context_propagates_owner_and_deletes_checkpoint(monkeypatch):
    thread_id = "public:alice:thread"
    manager = _Context()
    session_context._reference_contexts[thread_id] = manager
    session_context._reference_context_last_access[thread_id] = 1.0
    report_calls = []
    checkpoint_calls = []

    class ReportStore:
        def delete_session(self, **kwargs):
            report_calls.append(kwargs)
            return {"reports": 2, "citations": 3}

    async def delete_checkpoint(value: str) -> bool:
        checkpoint_calls.append(value)
        return True

    monkeypatch.setattr(session_context, "get_report_index_store", lambda: ReportStore())
    monkeypatch.setattr(
        session_context,
        "_clear_thread_rag_artifacts",
        lambda value: {"rag_collections": 1, "rag_runs": 4},
    )
    monkeypatch.setattr(session_context, "adelete_graph_thread", delete_checkpoint)

    result = asyncio.run(session_context._clear_session_context(thread_id, "alice"))

    assert manager.cleared is True
    assert report_calls == [{"session_id": thread_id, "user_id": "alice"}]
    assert checkpoint_calls == [thread_id]
    assert result == {
        "context": True,
        "reports": 2,
        "citations": 3,
        "rag_collections": 1,
        "rag_runs": 4,
        "checkpoint": True,
    }


def test_clear_session_context_rejects_cross_user_thread_before_deleting(monkeypatch):
    report_calls = []
    checkpoint_calls = []

    class ReportStore:
        def delete_session(self, **kwargs):
            report_calls.append(kwargs)
            return {}

    async def delete_checkpoint(value: str) -> bool:
        checkpoint_calls.append(value)
        return True

    monkeypatch.setattr(session_context, "get_report_index_store", lambda: ReportStore())
    monkeypatch.setattr(session_context, "adelete_graph_thread", delete_checkpoint)

    result = asyncio.run(
        session_context._clear_session_context("public:bob:thread", "alice")
    )

    assert report_calls == []
    assert checkpoint_calls == []
    assert result["context"] is False
    assert result["checkpoint"] is False

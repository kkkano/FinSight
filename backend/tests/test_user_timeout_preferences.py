# -*- coding: utf-8 -*-
from __future__ import annotations


def test_agent_preferences_normalize_timeout_seconds():
    from backend.api.agent_router import _normalize_preferences

    assert _normalize_preferences({"timeoutSeconds": 0})["timeoutSeconds"] == 0
    assert _normalize_preferences({"timeoutSeconds": 5})["timeoutSeconds"] == 30
    assert _normalize_preferences({"timeoutSeconds": 75})["timeoutSeconds"] == 75
    assert _normalize_preferences({"timeoutSeconds": 5000})["timeoutSeconds"] == 1200


def test_timeout_preference_overrides_execution_timeout(monkeypatch):
    from backend.services.execution_service import _execution_timeout_seconds

    monkeypatch.setenv("LANGGRAPH_EXECUTION_TIMEOUT_SECONDS", "500")

    assert _execution_timeout_seconds(
        "chat",
        {"agent_preferences": {"timeoutSeconds": 75}},
    ) == 75


def test_timeout_preference_overrides_planner_llm_timeout(monkeypatch):
    from backend.graph.nodes.planner import _planner_llm_limits

    monkeypatch.setenv("LANGGRAPH_PLANNER_CHAT_TIMEOUT_SEC", "150")

    limits = _planner_llm_limits(
        {
            "output_mode": "chat",
            "ui_context": {"agent_preferences": {"timeoutSeconds": 75}},
        }
    )

    assert limits["request_timeout"] == 75
    assert limits["acquire_timeout"] == 75.0


def test_timeout_preference_reader_ignores_system_default_value():
    from backend.graph.preference_timeouts import timeout_seconds_from_preferences

    assert timeout_seconds_from_preferences({"timeoutSeconds": 0}) is None
    assert timeout_seconds_from_preferences({"timeoutSeconds": "system"}) is None
    assert timeout_seconds_from_preferences({"timeoutSeconds": 90}) == 90
